#! /usr/bin/env python
#
## Generate a tagdiff file from updated trunk tags in SVN
#
#  Use this script to created a tagdiff file that will keep,
#  e.g., the master branch up to date with the latest versions of trunk tags
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

import argparse
import json
import os.path
import time

from glogger import logger
from atutils import check_output_with_retry, get_current_git_tags, initialise_svn_metadata

def main():
    parser = argparse.ArgumentParser(description='Generate tagdiff file for latest SVN trunk tags')
    parser.add_argument('--gitrepo', metavar='GITDIR',
                        help="Location of git repository")
    parser.add_argument('--tdfile', 
                        help="Output file for trunk tag evolution "
                        "(defaults to 'gitrepo.master.tagdiff')")
    parser.add_argument('--svncachefile', metavar='FILE',
                        help="File containing cache of SVN information - default 'gitrepo.svn.metadata'")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")
    
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    if not args.tdfile:
        if args.gitrepo == None:
            logger.error("Either tdfile or gitrepo must be given")
        args.tdfile = os.path.basename(args.gitrepo) + ".master.tagdiff"
    if not args.svncachefile:
        if args.gitrepo == None:
            logger.error("Either tdfile or svncachefile must be given")
        args.svncachefile = os.path.basename(args.gitrepo) + ".svn.metadata"
    
    svn_metadata_cache = initialise_svn_metadata(args.svncachefile)

    release_desc = {"name": "trunk",
                    "major": 0,
                    "minor": 0,
                    "patch": 0,
                    "cache": 0,
                    "type": "snapshot",
                    "timestamp": time.time(),
                    "nightly": True,
                    "author": "ATLAS Librarian <alibrari@cern.ch>"
                    }
    release_diff = {"add": {},
                    "remove": []}
    for package_name, pkg_data in svn_metadata_cache.iteritems():
        release_diff["add"][os.path.join(pkg_data["path"], package_name)] = "trunk"
        
    tagdiff = [{"release": "trunk",
               "diff": release_diff,
               "meta": release_desc},]
    
    with open(args.tdfile, "w") as tagdiff_fp:
        json.dump(tagdiff, tagdiff_fp, indent=2)


if __name__ == '__main__':
    main()
