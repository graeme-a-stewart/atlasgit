#! /usr/bin/env python
#
# Parse list of release tags known to NICOS to reconstruct package
# histories coherently along a release BRANCH

import argparse
import json
import logging
import os
import os.path
import re
import sys

from glogger import logger


nicos="/afs/cern.ch/atlas/software/dist/nightlies/nicos_work/tags/"

def parse_release_data(release):
    if release.startswith(nicos):
        release = release[len(nicos):]
    release_name = release.split("/")[0]
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
                    }
    logger.debug(release_desc)
    return release_desc


def parse_tag_file(filename):
    release_package_dict = {}
    with open(filename) as tag_file:
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
            if (package.endswith("Release") or package.endswith("RunTime")) and "/" not in package:
                package = os.path.join("Projects", package)
            logger.debug("Found package {0}, tag {1} in project {2}".format(package, tag, project))
            release_package_dict[package] = {"tag": tag, "project": project}
    return release_package_dict
            
def diff_release_tags(old, new, allow_removal=False):
    '''Return a structured dictionary describing the difference between releases.
    Difference has two sections "add" for added/updated tags; "remove" for removed packages.
    If "old" release is "None", difference is the new release as all tags are considered added'''
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
    '''Remove and update packages vz a viz the last cache release'''
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
    tag_files = os.listdir(arch_path)
    tag_files.sort()
    logger.debug("Best tagfile for {0} is {1} (chosen from {2})".format(arch_path, tag_files[-1], len(tag_files)))
    return(tag_files[-1])


def get_tag_file(base_path):
    '''Walk down the NICOS path, finding the "best" tag file to take
    (which means the highest gcc version, the opt build and the youngest tag file)'''
    best_arch = find_best_arch(base_path)
    best_tag_file = find_best_tagfile(os.path.join(base_path, best_arch))
    return (os.path.join(base_path, best_arch, best_tag_file))


def find_nicos_from_base(base_release):
    tag_files = []
    if not os.path.isdir(base_release):
        logger.error("Searching for NICOS tags from base release {0}, but no NICOS directory for this release was found!")
        sys.exit(1)

    # Process base release first
    tag_files.append(get_tag_file(os.path.join(nicos, base_release)))

    # Now find the caches and sort them
    cache_list = []
    base_dir = os.path.dirname(base_release)
    dir_list = os.listdir(base_dir)
    release_match = "{0}\.(\d+)$".format(os.path.basename(base_release).replace(".", r"\."))
    for entry in dir_list:
        if re.match(release_match, entry):
            cache_list.append(entry)
    cache_list.sort(cmp=lambda x,y: cmp(int(x.split(".")[3]), int(y.split(".")[3])))
    logger.debug("Found ordered list of production caches: {0}".format(cache_list))
    
    # And get tag files...
    for cache in cache_list:
        tag_files.append(get_tag_file(os.path.join(base_dir, cache)))

    return tag_files

def main():
    parser = argparse.ArgumentParser(description='ATLAS tag munger, calculating tag evolution across a releases series')
    parser.add_argument('release', metavar='', nargs="+",
                        help="Files containing tag lists (NICOS format). If a base release is givem (e.g., 20.1.3) "
                        "the script will search for the base release and all caches to build the tagdiff in "
                        "a simple way, without worrying about the details of the NICOS tag files and paths (N.B. "
                        "in the rare cases when there is more than one tag file for a release, the last one will "
                        "be used).")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")
    parser.add_argument('--tagdiffile', required=True,
                        help="output file for tag evolution between releases")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    tags_by_release = {}
    ordered_releases = []
    
    # Case when a single bese release is given - we have to expand this
    if len(args.release) == 1 and re.match(r"(\d+)\.(\d+)\.(\d+)$", args.release[0]):
        nicos_paths = find_nicos_from_base(os.path.join(nicos, args.release[0]))
    else:
        nicos_paths = args.release
    
    for release in nicos_paths:
        if not os.path.exists(release):
            logger.warning("Release tag file {0} does not exist".format(release))
            continue
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
    with open(args.tagdiffile, "w") as tag_output:
        last_base_release = ordered_releases[0]
        last_cache_release = None

        diff = diff_release_tags(None, tags_by_release[last_base_release])
        release_diff_list = [{"release": last_base_release,
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
                                      "diff": diff})
        json.dump(release_diff_list, tag_output, indent=2)


if __name__ == '__main__':
    main()
