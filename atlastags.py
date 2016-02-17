#! /usr/bin/env python
#
# Parse list of release tags known to NICOS to reconstruct package
# histories coherently along a release BRANCH

import argparse
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
            logger.debug("Found package {0}, tag {1} in project {2}".format(package, tag, project))
            release_package_dict[package] = {"tag": tag, "project": project}
    return release_package_dict
            
def diff_release_tags(old, new, allow_removal = False):
    logger.debug("Tag difference from {0} to {1} (removal: {2}".format(old["release"]["name"],
                                                                       new["release"]["name"],
                                                                       allow_removal))
    rel_diff = {"update": {}, "add": {}, "remove": []}
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
    return rel_diff
    

def main():
    parser = argparse.ArgumentParser(description='Tag munger')
    parser.add_argument('release', metavar='', nargs="+",
                        help="Files containing tag lists (NICOS format)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

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
    for (old, new) in zip(ordered_releases[:-1], ordered_releases[1:]):
        diff = diff_release_tags(tags_by_release[old], tags_by_release[new])
        print "{0} -> {1}".format(old, new)
        print "  update: {0} tags".format(len(diff["update"]))
        print "  add: {0} tags".format(len(diff["add"]))
        print "  remove: {0} tags".format(len(diff["remove"]))


if __name__ == '__main__':
    main()
