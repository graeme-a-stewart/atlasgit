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
# Take several releases and update the tags of the first release to be
# a superset release containing all tags. Note that the releases are
# prioritised, so that only missing tags are added. Package tag verions
# that exist are never downgraded.
#
# Use this script to merge analysis releases into dev(val) tags to create
# a development super release

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
