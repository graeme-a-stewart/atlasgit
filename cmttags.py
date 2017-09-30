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

## Parse list of release tags from CMT

import argparse
import json
import logging
import os
import os.path
import re
import sys
import time

from glogger import logger

def parse_release_data(release_file_path):
    ## @brief Parse release data from the CMT requirements file
    #  @param release_file_path Path to file for the release of interest
    #  @return Dictionary of values for the different release properties
    timestamp = os.stat(release_file_path).st_mtime
    path_elements = release_file_path.split("/")
    release_name = path_elements[-4]  # This is a bit hacky - limited usecase only
    release_elements = release_name.split(".")
    if len(release_elements) < 3:
        raise RuntimeError("Weird release: {0}".format(release_name))
    if len(release_elements) == 3:
        rel_type = "base"
        minor = None
        subminor = None
        cache_number = 0
    elif len(release_elements) == 4:
        rel_type = "cache"
        minor = release_elements[3]
        subminor = None
    major = release_elements[0]
    minor = release_elements[1]
    patch = release_elements[2]
    release_desc = {"name": release_name,
                    "series": release_elements[0],
                    "flavour": release_elements[1],
                    "major": release_elements[2],
                    "minor": minor,
                    "subminor": subminor,
                    "type": rel_type,
                    "timestamp": timestamp,
                    "nightly": False,
                    "author": "ATLAS Librarian <alibrari@cern.ch>"
                    }
    logger.debug(release_desc)
    return release_desc


def parse_tag_file(release_file_path):
    ## @brief Open a CMT requirements file and extract the package tags
    #  @param release_file_path Path to requirements file for the release of interest
    #  @return Dictionary keyed by package, with each value a dictionary with @c tag and @project
    #  information for the package
    release_package_dict = {}
    with open(release_file_path) as tag_file:
        for line in tag_file:
            line = line.strip()
            logger.debug(line)
            if len(line) == 0 or line.startswith("#"):
                continue
            try:
                (use, package_name, tag, package_path) = line.split()
            except ValueError:
                continue
            if use != "use":
                continue
            release_package_dict[os.path.join(package_path, package_name)] = {"svn_tag": tag,
                 "project": "", "package_name": package_name}
    return release_package_dict


def main():
    parser = argparse.ArgumentParser(description='ATLAS CMT tag parser, grabbing tag content for a CMT cache release. '
                                     'This is quite a hacky script, only filling in the gaps in NICOS knowledge for '
                                     'ATLAS P1HLT caches.')
    parser.add_argument('release', metavar='RELEASE',
                        help="CMT requirements file to parse")
    parser.add_argument('--tagdir', default="tagdir",
                        help="output directory for tag files, each release will generate an entry here (default \"tagdir\")")
    parser.add_argument('--overwrite', action="store_true", default=False,
                        help="Overwrite any exisitng configuration files (otherwise, just skip over)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    release_description = parse_release_data(args.release)
    release_tags = parse_tag_file(args.release)
    logger.info("Processing tags for release {0}".format(release_description["name"]))
    output_file = os.path.join(args.tagdir, release_description["name"])
    if args.overwrite or not os.path.exists(output_file):
        with open(os.path.join(args.tagdir, release_description["name"]), "w") as tag_output:
            json.dump({"release": release_description, "tags": release_tags}, tag_output, indent=2)
    else:
        logger.debug("Skipped writing to {0} - overwrite is false".format(output_file))



if __name__ == '__main__':
    main()
