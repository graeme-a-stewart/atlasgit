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

## Use this script to merge analysis releases into dev(val) tags to create
#  a development super release

import argparse
import json
import logging
import os

from glogger import logger

def main():
    parser = argparse.ArgumentParser(description='Merge releases to create a super-release')
    parser.add_argument('targetrelease', metavar='RELEASE',
                        help="Target release")
    parser.add_argument('mergerelease', metavar='RELEASE', nargs="+",
                        help="Releases to merge into target")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    with open(args.targetrelease) as target:
        target_release_data = json.load(target)

    for release in args.mergerelease:
        with open(release) as merge:
            merge_release_data = json.load(merge)
        for package_path, package_data in merge_release_data["tags"].iteritems():
            if package_path not in target_release_data["tags"]:
                target_release_data["tags"][package_path] = package_data
                logger.info("Merged {0} at tag {1} from {2}".format(package_path, package_data["svn_tag"], release))
            else:
                logger.debug("Package {0} already exists in target".format(package_path))
    
    try:
        os.rename(args.targetrelease, args.targetrelease + ".bak")
        with open(args.targetrelease, "w") as output_fh:
            json.dump(target_release_data, output_fh, indent=2)
    except OSError, e:
        logger.error("Error while rewriting target file {0}: {1}".format(args.targetrelease, e))


if __name__ == '__main__':
    main()
