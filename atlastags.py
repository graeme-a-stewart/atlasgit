#! /usr/bin/env python
#
# Parse list of release tags known to NICOS to reconstruct package
# histories coherently along a release BRANCH

import argparse
import json
import logging
import os
import os.path
import sys

# Setup basic logging
logger = logging.getLogger('atags')
hdlr = logging.StreamHandler(sys.stdout)
frmt = logging.Formatter("%(name)s.%(funcName)s %(levelname)s %(message)s")
hdlr.setFormatter(frmt)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)

def parse_release_data(release):
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
            # Gaudi packages live in a separate project
            if project == "GAUDI":
                continue
            # "Release" packages live inside the Release path
            if package.endswith("Release") and "/" not in package:
                package = os.path.join("Projects", package)
            logger.debug("Found package {0}, tag {1} in project {2}".format(package, tag, project))
            release_package_dict[package] = {"tag": tag, "project": project}
    return release_package_dict
            
def diff_release_tags(old, new, allow_removal=False):
    '''Return a structured dictionary describing the difference between releases.
    If "old" release is "None", difference is the new release as all tags are considered added'''
    rel_diff = {"update": {}, "add": {}, "remove": []}
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
                rel_diff["update"][package] = new["tags"][package]["tag"]
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
    for package in last_cache:
        # Remove packages that stayed the same between caches
        if package in release_diff["update"] and release_diff["update"][package] == last_cache["tags"][package]["tag"]:
            del(release_diff["update"][package])
        elif package in release_diff["add"] and release_diff["add"][package] == last_cache["tags"][package]["tag"]:
            del(release_diff["add"][package])

        if package not in release_diff["update"] and package not in release_diff["add"]:
            # Package was removed from the cache - revert to base tag or remove completely
            try:
                release_diff["update"][package] = base_release["tags"][package]["tag"]
            except KeyError:
                release_diff["remove"].append(package)
            

def main():
    parser = argparse.ArgumentParser(description='ATLAS tag munger, calculating tag evolution across a releases series')
    parser.add_argument('release', metavar='', nargs="+",
                        help="Files containing tag lists (NICOS format)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")
    parser.add_argument('--tagEvolutionFile', required=True,
                        help="output file for tag evolution between releases")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    tags_by_release = {}
    ordered_releases = []
    for release in args.release:
        release_description = parse_release_data(release)
        ordered_releases.append(release_description["name"])
        release_tags = parse_tag_file(release)
        tags_by_release[release_description["name"]] = {"release": release_description,
                                                        "tags": release_tags}

    # Debug...
    if args.debug:
        for (old, new) in zip(ordered_releases[:-1], ordered_releases[1:]):
            diff = diff_release_tags(tags_by_release[old], tags_by_release[new])
            print "{0} -> {1}".format(old, new)
            print "  update: {0} tags".format(len(diff["update"]))
            print "  add: {0} tags".format(len(diff["add"]))
            print "  remove: {0} tags".format(len(diff["remove"]))

    ## Process releases in order, calculating tag differences
    if tags_by_release[ordered_releases[0]]["release"]["type"] != "base":
        logger.error("First release along a series must be a base release (release {0} is {1})".format(ordered_releases[0],
                                                                                                       tags_by_release[ordered_releases[0]]["release"]["type"]))
        sys.exit(1)
    with open(args.tagEvolutionFile, "w") as tag_output:
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
