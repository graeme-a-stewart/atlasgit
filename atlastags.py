#! /usr/bin/env python
#
# Parse list of release tags known to NICOS to reconstruct package
# histories coherently along a release BRANCH
#
# Copyright (c) Graeme Andrew Stewart <graeme.a.stewart@gmail.com>
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
# 
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
# 
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import datetime
import json
import logging
import os
import os.path
import re
import sys

from glogger import logger


def get_release_name(release_file_path):
    ## @brief a NICOS tag file to get tags and projects for this build.
    #  @param release_file_path Path to file with NICOS tags for the release of interest
    #  @return Tuple of release name, plus boolen if the release is a nightly 
    #  (thus @c False for a numbered release)
    with open(release_file_path) as release_file:
        for line in release_file:
            if line.startswith("#release"):
                # This is a numbered release_file_path
                release_match = re.match(r"#release\s([\d\.]+)", line)
                if release_match:
                    return release_match.group(1), False
            elif line.startswith("#tags for"):
                # This is a nightly
                release_match = re.match(r"#tags for\s([\d\.]+)", line)
                if release_match:
                    return release_match.group(1), True
        logger.error("Failed to parse release_file_path name from tag file {0}".format(release_file_path))
        raise RuntimeError("Failed to find release name")


def parse_release_data(release_file_path):
    ## @brief Parse release data from the NICOS tag file
    #  @param release_file_path Path to file with NICOS tags for the release of interest
    #  @return Dictionary of values for the different release properties
    timestamp = os.stat(release_file_path).st_mtime
    release_name, nightly_flag = get_release_name(release_file_path)
    release_elements = release_name.split(".")
    if len(release_elements) < 3:
        raise RuntimeError("Weird release: {0}".format(release_name))
    if len(release_elements) == 3:
        rel_type = "base"
        cache_number = 0
    elif len(release_elements) == 4:
        rel_type = "cache"
        cache_number = release_elements[3]
    major = release_elements[0]
    minor = release_elements[1]
    patch = release_elements[1]
    release_desc = {"name": release_name,
                    "major": release_elements[0],
                    "minor": release_elements[1],
                    "patch": release_elements[2],
                    "cache": cache_number,
                    "type": rel_type,
                    "timestamp": timestamp,
                    "nightly": nightly_flag,
                    "author": "ATLAS Librarian <alibrari@cern.ch>"
                    }
    logger.debug(release_desc)
    return release_desc


def parse_tag_file(release_file_path):
    ## @brief Open a NICOS tag file and extract the package tags
    #  @param release_file_path Path to file with NICOS tags for the release of interest
    #  @return Dictionary keyed by package, with each value a dictionary with @c tag and @project
    #  information for the package
    release_package_dict = {}
    with open(release_file_path) as tag_file:
        for line in tag_file:
            line = line.strip()
            if len(line) == 0 or line.startswith("#"):
                continue
            try:
                (package, tag, project) = line.split(" ")
            except ValueError:
                continue
            # Gaudi packages live in a separate project, so don't add them
            if project == "GAUDI":
                continue
            # "Release" and "RunTime" packages live inside the Release path
            if (package.endswith("Release") or package.endswith("RunTime") or 
                package.startswith("Atlas") or package.startswith("DetCommon")) and "/" not in package:
                package = os.path.join("Projects", package)
            logger.debug("Found package {0}, tag {1} in project {2}".format(package, tag, project))
            release_package_dict[package] = {"tag": tag, 
                                             "project": project,}
    return release_package_dict


def diff_release_tags(old, new, allow_removal=False):
    ## @brief Return a structured dictionary describing the difference between releases
    #  @param old Tag lists for older release (can be @c None, in which case all new release
    #  tags are considered added)
    #  @param new Tag lists for newer release 
    #  @param allow_removal If missing tags in the new release are considred to be removed
    #  packages (@c True) or simply unchanged (@c False). This is set to @True
    #  for diffing base relesases; for a base to cache comparison it should be @c False 
    #  @return Dictionary with two keys, @c add and @c remove; @c add dictionary value is a 
    #  dictionary keyed by package, with value the updated tag; @remove dictionary is
    #  list of packages that have been removed
    rel_diff = {"add": {}, "remove": []}
    if old:
        logger.debug("Tag difference from {0} to {1} (removal: {2})".format(old["release"]["name"],
                                                                            new["release"]["name"],
                                                                            allow_removal))
    else:
        logger.debug("Tag base from {0}".format(new["release"]["name"]))
        
    if old:
        for package in new["tags"]:
            if package in old["tags"]:
                if new["tags"][package]["tag"] == old["tags"][package]["tag"]:
                    continue
                logger.debug("Package {0} changed from tag {1} to {2}".format(package, 
                                                                              old["tags"][package]["tag"],
                                                                              new["tags"][package]["tag"]))
                rel_diff["add"][package] = new["tags"][package]["tag"]
            else:
                logger.debug("Package {0} added at tag {1}".format(package, 
                                                                   new["tags"][package]["tag"]))
                rel_diff["add"][package] = new["tags"][package]["tag"]
        if allow_removal:
            rel_diff["remove"] = list(set(old["tags"].keys()) - set(new["tags"].keys()))
            logger.debug("These packages removed: {0}".format(rel_diff["remove"]))
    else:
        for package in new["tags"]:
            rel_diff["add"][package] = new["tags"][package]["tag"]
    return rel_diff


def cache_overlap_removal(release_diff, base_release, last_cache):
    ## @brief Remove and update packages vz a viz the last cache release
    #  @param release_diff output from @c diff_release_tags finction
    #  @param base_release tag lists from base release for this cache
    #  @param last_cache tag lists from cache release
    #  @return None (@c release_diff is updated as side effect)
    for package in last_cache["tags"]:
        # Remove packages that stayed the same between caches
        if package in release_diff["add"] and release_diff["add"][package] == last_cache["tags"][package]["tag"]:
            del(release_diff["add"][package])

        if package not in release_diff["add"]:
            # Package was removed from the cache - revert to base tag or remove completely
            try:
                release_diff["add"][package] = base_release["tags"][package]["tag"]
            except KeyError:
                release_diff["remove"].append(package)


def find_best_arch(base_path):
    ## @brief Find the "best" achitecture when various NICOS architectures are available
    #  for a particular release ("opt" release is preferred)
    #  @param base_path Directory path to NICOS architecture subdirectories
    #  @return Chosen architecture
    best_arch = None
    arch = os.listdir(base_path)
    if len(arch) == 1:
        best_arch = arch[0]
    else:
        opt_arch = [ a for a in arch if a.endswith("opt") ]
        if len(opt_arch) == 1:
            best_arch = opt_arch[0]
        else:
            opt_arch.sort()
            best_arch = opt_arch[0]
    if not best_arch:
        logger.error("Failed to find a good architecture from {0}".format(base_path))
        sys.exit(1)
    logger.debug("Best archfile for {0} is {1} (chosen from {2})".format(base_path, best_arch, len(arch)))
    return best_arch


def find_best_tagfile(arch_path):
    ## @brief Find the newest tag file when various NICOS tag files are available
    #  for a particular release
    #  @param arch_path Directory path to NICOS tag files
    #  @return Chosen tag file
    tag_files = os.listdir(arch_path)
    tag_files.sort()
    logger.debug("Best tagfile for {0} is {1} (chosen from {2})".format(arch_path, tag_files[-1], len(tag_files)))
    return(tag_files[-1])


def get_tag_file(base_path):
    ## @brief Walk down the NICOS path, finding the "best" tag file to take
    #  which means the highest gcc version, the opt build and the youngest tag file)
    #  @param base_path Directory base with architecture subdirectories containing tag files
    best_arch = find_best_arch(base_path)
    best_tag_file = find_best_tagfile(os.path.join(base_path, best_arch))
    return (os.path.join(base_path, best_arch, best_tag_file))


def find_nicos_from_base(nicos_path, base_release):
    ## @brief Find base release and cache release tag files when only a base release number
    #  is given
    #  @param nicos_path Base path to NICOS tag file area
    #  @param base_release Base release number A.B.X (e.g., 21.0.1)
    #  @return list of tag files for base and caches, in release numbered order
    tag_files = []
    if not os.path.isdir(os.path.join(nicos_path, base_release)):
        logger.error("Searching for NICOS tags from base release {0}, but no NICOS directory for this release was found!")
        sys.exit(1)

    # Process base release first
    tag_files.append(get_tag_file(os.path.join(nicos_path, base_release)))

    # Now find the caches and sort them
    cache_list = []
    dir_list = os.listdir(nicos_path)
    release_match = "{0}\.(\d+)$".format(os.path.basename(base_release).replace(".", r"\."))
    for entry in dir_list:
        if re.match(release_match, entry):
            cache_list.append(entry)
    cache_list.sort(cmp=lambda x,y: cmp(int(x.split(".")[3]), int(y.split(".")[3])))
    logger.debug("Found ordered list of production caches: {0}".format(cache_list))
    
    # And get tag files...
    for cache in cache_list:
        tag_files.append(get_tag_file(os.path.join(nicos_path, cache)))

    return tag_files

def main():
    parser = argparse.ArgumentParser(description='ATLAS tag munger, calculating tag evolution across a releases series')
    parser.add_argument('release', metavar='RELEASE', nargs="+",
                        help="Files containing tag lists (NICOS format). If a base release is given (e.g., 20.1.3) "
                        "the script will search for the base release and all caches to build the tagdiff in "
                        "a simple way, without worrying about the details of the NICOS tag files and paths (N.B. "
                        "in the rare cases when there is more than one tag file for a release, the last one will "
                        "be used).")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")
    parser.add_argument('--tdfile', '--tagdiffile',
                        help="output file for tag evolution between releases (defaults to A.B.X.tagdiff only for single "
                        "base release use case - otherwise must be specified using this option)")
    parser.add_argument('--nicospath', default="/afs/cern.ch/atlas/software/dist/nightlies/nicos_work/tags/",
                        help="path to NICOS tag files (defaults to usual CERN AFS location)")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    tags_by_release = {}
    ordered_releases = []
    
    # Case when a single bese release is given - we have to expand this
    if len(args.release) == 1 and re.match(r"(\d+)\.(\d+)\.(\d+)$", args.release[0]):
        nicos_paths = find_nicos_from_base(args.nicospath, args.release[0])
        if not args.tdfile:
            args.tdfile = args.release[0] + ".tagdiff"
    else:
        nicos_paths = []
        for path in args.release:
            if os.path.exists(path):
                nicos_paths.append(path)
            elif os.path.exists(os.path.join(args.nicospath, path)):
                nicos_paths.append(os.path.join(args.nicospath, path))
            else:
                logger.error("Path {0} doesn't exist (even after prepending NICOS path)".format(path))
                sys.exit(1)
        if not args.tdfile:
            logger.error("When giving specific NICOS file paths the --tdfile must be specified manually ".format(path))
            sys.exit(1)
            
    
    for release in nicos_paths:
        release_description = parse_release_data(release)
        ordered_releases.append(release_description["name"])
        release_tags = parse_tag_file(release)
        tags_by_release[release_description["name"]] = {"release": release_description,
                                                        "tags": release_tags}
        logger.info("Processed tags for release {0}".format(release_description["name"]))


    ## Process releases in order, calculating tag differences
    if tags_by_release[ordered_releases[0]]["release"]["type"] != "base":
        logger.error("First release along a series must be a base release (release {0} is {1})".format(ordered_releases[0],
                                                                                                       tags_by_release[ordered_releases[0]]["release"]["type"]))
        sys.exit(1)
    with open(args.tdfile, "w") as tag_output:
        last_base_release = ordered_releases[0]
        last_cache_release = None

        diff = diff_release_tags(None, tags_by_release[last_base_release])
        release_diff_list = [{"release": last_base_release,
                              "meta": tags_by_release[last_base_release]["release"],
                              "diff": diff}]
        
        for release in ordered_releases[1:]:
            if tags_by_release[release]["release"]["type"] == "base":
                diff = diff_release_tags(tags_by_release[last_base_release], tags_by_release[release], allow_removal=True)
                last_base_release = release
                last_cache_release = None
            else:
                diff = diff_release_tags(tags_by_release[last_base_release], tags_by_release[release], allow_removal=False)
                # Now look for tags which were the same in the last cache release
                if last_cache_release:
                    cache_overlap_removal(diff, tags_by_release[last_base_release], tags_by_release[last_cache_release])
                last_cache_release = release
            release_diff_list.append({"release": release,
                                      "meta": tags_by_release[release]["release"],
                                      "diff": diff})
        json.dump(release_diff_list, tag_output, indent=2)


if __name__ == '__main__':
    main()
