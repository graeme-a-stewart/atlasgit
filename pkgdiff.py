#! /usr/bin/env python
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
#
# Simple script to manage comparisons between release tag files

import argparse
import json
import logging

from glogger import logger

def main():
    parser = argparse.ArgumentParser(description='Diff tag content of tagdiff files')
    parser.add_argument('action', choices=["missing", "versions"],
                        help="missing: show package paths in release 1, but not in release 2; "
                        "versions: show versions that are different between 1 and 2 (for packages in both)")
    parser.add_argument('tagfile1', metavar='RELEASE',
                        help="Tagfile of first release")
    parser.add_argument('tagfile2', metavar='RELEASE',
                        help="Tagfile of second release")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    with open(args.tagfile1) as tf:
        rel_content1 = json.load(tf)
    with open(args.tagfile2) as tf:
        rel_content2 = json.load(tf)

    package_paths1 = set([ tag_info for tag_info in rel_content1["tags"] ])
    package_paths2 = set([ tag_info for tag_info in rel_content2["tags"] ])

    if args.action == "missing":
        missing_packages = package_paths1 - package_paths2
        for pkg in missing_packages:
            print pkg
    elif args.action == "versions":
        common_packages = package_paths1 & package_paths2
        for pkg in common_packages:
            if rel_content1["tags"][pkg]["svn_tag"] != rel_content2["tags"][pkg]["svn_tag"]:
                print rel_content1["tags"][pkg]["svn_tag"], rel_content2["tags"][pkg]["svn_tag"]

if __name__ == '__main__':
    main()
