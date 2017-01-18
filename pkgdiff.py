#! /usr/bin/env python
#
# Simple dump of packages in a tagfile

import argparse
import json
import logging

from glogger import logger

def main():
    parser = argparse.ArgumentParser(description='Diff tag content of tagdiff files')
    parser.add_argument('tagfile1', metavar='RELEASE',
                        help="Tagfile of first release (analysis)")
    parser.add_argument('tagfile2', metavar='RELEASE',
                        help="Tagfile of second release (production)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    with open(args.tagfile1) as tf:
        tag_content1 = json.load(tf)
    with open(args.tagfile2) as tf:
        tag_content2 = json.load(tf)

    pkg1 = set([ tag_info["package_name"] for tag_info in tag_content1["tags"].itervalues() ])
    pkg2 = set([ tag_info["package_name"] for tag_info in tag_content2["tags"].itervalues() ])

    missing_packages = pkg1 - pkg2
    if missing_packages:
        print "Missing packages in 1 but not 2:"
        for pkg in missing_packages:
            print "  ", pkg
    else:
        print "2 contains all packages in 1"

if __name__ == '__main__':
    main()
