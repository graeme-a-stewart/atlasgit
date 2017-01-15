#! /usr/bin/env python
#
# Make a cross check against the git checkout for files that may have
# been CERN copyrighted and Apache licensed by mistake
#
# Copyright 2017 (c) Graeme Andrew Stewart <graeme.a.stewart@gmail.com>
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
import fnmatch
import logging
import os
import os.path
import re
import sys

from glogger import logger
from svnutils import load_exceptions_file

def license_check_file(filename, git_filename, quiet=False):
    with open(filename) as fh:
        counter = 0
        license_concern = False
        for line in fh:
            counter += 1
            if re.search(r"[Cc]opyright", line):
                # Filter out Apache license statements or ATLAS direct copyright
                # (even though the later is invalid)
                if not ("CERN for the benefit of the ATLAS collaboration" in line or
                        "Atlas Collaboration" in line or
                        "for more information"):
                    if quiet:
                        print "- {0}".format(git_filename)
                    else:
                        logger.warning("Found copyright line in {0} at line {1}: {2}".format(git_filename, counter, line.strip()))
                    license_concern = True
            if re.search(r"[Ll]icense", line):
                # Filter on Apache license statements and misc log messages that
                # contain license
                if not ("Licensed under the Apache License" in line or
                        "You may obtain a copy of the License" in line or
                        "you may not use this file except in compliance" in line or
                        "http://www.apache.org/licenses" in line or
                        "under the License is distributed" in line or
                        "See the License for the specific" in line or
                        "limitations under the License" in line or
                        'for more information.' in line):
                    if quiet:
                        print "- {0}".format(git_filename)
                    else:
                        logger.warning("Found license line in {0} at line {1}: {2}".format(git_filename, counter, line.strip()))
                    license_concern = True
    return 1 if license_concern else 0


def main():
    parser = argparse.ArgumentParser(description="License file checker, parsing a git import and "
                                     "checking for any files that may have had the new ATLAS copyright "
                                     "and license applied in error. All files are listed, filtered by the current "
                                     "exceptions and then checked for statements of license or copyright that "
                                     "indicate a problem.")
    parser.add_argument("--path", help="Path to check (by default check cwd)")
    parser.add_argument('--licenseexceptions', metavar="FILE", help="File listing path globs to exempt from or  "
                        "always apply license file to (same format as --svnfilterexceptions)",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlaslicense-exceptions.txt"))
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")
    parser.add_argument('--quiet', action="store_true", default=False,
                        help="Only print filenames that have issues for adding to the filter file")
    
    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Where to check
    if args.path:
        check_path = args.path
    else:
        check_path = os.getcwd()
    license_path_accept, license_path_reject = load_exceptions_file(args.licenseexceptions)

    worry_files = 0
    for root, dirs, files in os.walk(check_path):
        if os.path.basename(root) == ".git":
            continue
        for name in files:
            extension = name.rsplit(".", 1)[1] if "." in name else ""
            if extension not in ("cxx", "cpp", "icc", "cc", "c", "C", "h", "hpp", "hh", "py", "cmake"):
                continue
            if name == "AtlasInternals.cmake":  # Many false matches, so skip...
                continue
            filename = os.path.join(root, name)
            git_filename = filename[len(check_path) + 1:]
            path_veto = False
            for filter in license_path_reject:
                if fnmatch.fnmatch(git_filename, filter):
                    logger.debug("File {0} was license file vetoed".format(git_filename))
                    path_veto = True
                    break
            for filter in license_path_accept:
                if fnmatch.fnmatch(svn_filename, filter):
                    logger.debug("File {0} was license file forced".format(git_filename))
                    path_veto = False
                    break
            if path_veto:
                continue
            worry_files += license_check_file(filename, git_filename, args.quiet)

    if worry_files:
        logger.warning("Found {0} concerning files".format(worry_files))
        sys.exit(1)

    return 0

if __name__ == '__main__':
    main()
