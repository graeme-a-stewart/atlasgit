#! /usr/bin/env python
#
# Author: Graeme A Stewart <graeme.andrew.stewart@cern.ch>
#
# Copyright (C) 2017 CERN for the benefit of the ATLAS collaboration
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

## Simple script to manage comparisons between release tag files

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
