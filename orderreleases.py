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
# Take a set of release tag files and given them back in chronological
# order

import argparse
import json
import logging

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

    for release_tuple in release_list:
        print release_tuple[0],
    print


if __name__ == '__main__':
    main()
