#! /usr/bin/env python
#
# Utility script that will remove current copyright and license from source
# files and will then reassign copyright to CERN
#

import argparse
import logging
import os
import re
import sys

from glogger import logger
from _ast import Or


def main():
    parser = argparse.ArgumentParser(description='Relicense source file to CERN')
    parser.add_argument('files', nargs="+",
                        help="Files to relicense")
    parser.add_argument('--depth', type=int, default=20,
                        help="Number of lines from start of the file which can be processed (default %(default)s)")
    parser.add_argument('--nolicense', action="store_true",
                        help="If the standard CERN (C) should not be added to the file. This is only "
                        "applied to C, C++ and python files (default apply license)")
    parser.add_argument('--rename', type=bool, default=False,
                        help="If the new file should overwrite the old one (original file renamed .bak) or "
                        "be left as .relicense (default %(default)s)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    for fname in args.files:
        relicense(fname, not args.nolicense, args.rename, depth=args.depth)


def relicense(fname, license=True, rename=False, depth=20):
    logger.info("Processing file {0}".format(fname))
    tmpname = fname + ".relicense"
    fmode = os.stat(fname).st_mode
    with open(fname) as infile, open(tmpname, "w") as outfile:
        source_lines = infile.readlines()

        keep_lines = [ True for l in range(len(source_lines)) ]

        remove_plain_copyright(source_lines, keep_lines, depth)
        remove_gpl_block(source_lines, keep_lines, depth)

        if license:
            add_standard_license(fname, source_lines, keep_lines)

        write_relicensed_file(source_lines, keep_lines, outfile)
        os.chmod(tmpname, fmode)

        if rename:
            os.rename(fname, fname + ".bak")
            os.rename(tmpname, fname)


def write_relicensed_file(source_lines, keep_lines, outfile):
    '''Write out relicensed file'''
    for line, keep in zip(source_lines, keep_lines):
        if keep:
            outfile.write(line)


def remove_plain_copyright(source_lines, keep_lines, depth):
    '''Get rid of plain vanilla copyright lines'''
    idx = 0
    copyre = re.compile(r"//.*copyright.*\([Cc]\)")
    for line in source_lines:
        if copyre.search(line):
            logger.info("Found copyright line to suppress at index {0}: {1}".format(idx + 1, line))
            keep_lines[idx] = False
        if idx > depth:
            break
        idx += 1


def remove_gpl_block(source_lines, keep_lines, depth):
    '''Get rid of GPL license block'''
    gpl_idx = search_from(source_lines, "GNU General Public License", 0, depth)
    if gpl_idx == -1:
        return

    # OK, found a matching line, now search for start and end of block
    start_idx = search_from(source_lines, r"\*\*\*\*\*\*\*\*", gpl_idx, max=10, backwards=True)
    stop_idx = search_from(source_lines, r"\*\*\*\*\*\*\*\*", gpl_idx, max=10, backwards=False)

    if start_idx == -1 or stop_idx == -1:
        logger.warning("Found GPL trigger line, but failed to find start/end of license block")
        return

    logger.info("Found GPL license block to suppress from lines {0} to {1}".format(start_idx + 1, stop_idx + 1))
    for idx in range(start_idx, stop_idx + 1):
        keep_lines[idx] = False


def search_from(source_lines, re_string, start_idx=0, max=20, backwards=False):
    '''Flexibly search for a regexp in a list of lines'''
    current_idx = start_idx
    for i in range(max):
        if re.search(re_string, source_lines[current_idx]):
            logger.debug("Found search line {0} at index {1}".format(re_string, current_idx))
            return current_idx
        if backwards:
            current_idx -= 1
        else:
            current_idx += 1
        if current_idx < 0 or current_idx == len(source_lines):
            break

    # Not found
    return -1


def add_standard_license(fname, source_lines, keep_lines):
    '''Add the standard CERN license if it is missing'''
    if search_from(source_lines, r"Copyright \(C\) 2002-2017 CERN for the benefit of the ATLAS collaboration") != -1:
        logger.info("Standard license already present")
        return
    extension = fname.rsplit(".", 1)[1] if "." in fname else ""
    if extension in ("cxx", "cpp", "icc", "cc", "c", "C", "h", "hpp", "hh"):
        logger.info("Adding C style license")
        add_c_license(source_lines, keep_lines)
    elif extension in ("py", "cmake"):
        logger.info("Adding py style license")
        add_py_license(source_lines, keep_lines)
    
    
def add_c_license(source_lines, keep_lines):
    '''Add a license file, C style commented'''
    target_line = 0
    
    # If the first line is a -*- C++ -*- then it has to stay the first line
    if re.search(r"-\*-\s+[cC]\+\+\s+-\*\-", source_lines[0]):
        # Beware of breaking a multi-line C style comment
        if source_lines[0].startswith("/*") and ("*/" not in source_lines[0][2:]):
            source_lines[0] = source_lines[0][:-1] + " */\n"
            source_lines[1:1] = ["/*\n"]
            keep_lines[1:1] = [True]
        target_line = 1

    source_lines[target_line:target_line] = ["/*\n", "  Copyright (C) 2002-2017 CERN for the benefit of the ATLAS collaboration\n", "*/\n", "\n"]
    keep_lines[target_line:target_line] = [True, True, True, True]
    

def add_py_license(source_lines, keep_lines):
    '''Add a license file, py style'''
    target_line = 1 if source_lines[0].startswith("#!") else 0
    source_lines[target_line:target_line] = ["# Copyright (C) 2002-2017 CERN for the benefit of the ATLAS collaboration\n", "\n"]
    keep_lines[target_line:target_line] = [True, True]
        

if __name__ == '__main__':
    main()
