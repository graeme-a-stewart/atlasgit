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

## Take a set of release tag files and given them back in chronological
#  order

import argparse
import json
import logging
import time

from glogger import logger

def main():
    parser = argparse.ArgumentParser(description='Return release list chronologically ordered')
    parser.add_argument('release', metavar='RELEASE', nargs="+",
                        help="Release tag files")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    release_list = []
    for release in args.release:
        with open(release) as rel_fh:
            release_data = json.load(rel_fh)
        release_list.append((release, release_data))

    release_list.sort(cmp=lambda x, y: cmp(x[1]["release"]["timestamp"], y[1]["release"]["timestamp"]))

    if logger.isEnabledFor(logging.DEBUG):
        for release_tuple in release_list:
            logger.debug("Release {0} built {1}".format(release_tuple[1]["release"]["name"],
                                                        time.asctime(time.localtime(release_tuple[1]["release"]["timestamp"]))))

    for release_tuple in release_list:
        print release_tuple[0],
    print


if __name__ == '__main__':
    main()
