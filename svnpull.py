#! /usr/bin/env python
#
# # Simple script that will pull packages from SVN, clean them up,
#  then copy them into the current git repository
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
import logging
import os.path
import stat
import sys
import re

from glogger import logger
from svnutils import svn_co_tag_and_commit, load_svn_path_exceptions


def map_package_names_to_paths():
    # # @brief Map package names to a source path
    #  @return Dictionary of package name to package path mappings
    package_path_dict = {}
    for root, dirs, files in os.walk("."):
        if "CMakeLists.txt" in files:
            root = root.lstrip("./")
            path, package = os.path.split(root)
            package_path_dict[package] = root
            # logger.debug("Mapped path {0} to package {1}".format(root, package))
    return package_path_dict


def get_svn_path_from_tag_name(svn_package, package_path_dict):
    # # @brief Map a package's SVN tag name to a path in SVN from which
    #  we will import the package
    #  @return tuple with package name and SVN import path
    try:
        package_name = svn_package.split("-")[0]
        if svn_package in package_path_dict:
            return svn_package, package_path_dict[svn_package], "trunk"
        if svn_package.endswith("branch"):
            return package_name, package_path_dict[package_name], os.path.join("branches", svn_package)
        if re.search(r'(-\d\d){3,4}', svn_package):
            return package_name, package_path_dict[package_name], os.path.join("tags", svn_package)
    except KeyError:
        pass
    logger.error("Failed to find a matching package path in your checkout "
                 "for SVN package {0} or you used an invalid package specification "
                 "(see --help). Make sure your git checkout "
                 "contains the package you wish to pull an SVN revision onto.".format(svn_package))
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="Pull SVN package revisions from SVN and apply them "
                                     "to the current AtlasOffline git repository. Run this script from "
                                     "the root of the git repository to be updated.")
    parser.add_argument('svnpackages', nargs="+",
                        help="SVN packages to import, where a simple package name is interpreted as the "
                        "trunk of the package, a package tag maps to the usual SVN tag and "
                        "a tag name ending in 'branch' is considered a development branch"
                        "(e.g. xAODMuon maps to Event/xAOD/xAODMuon/trunk, "
                        "xAODMuon-00-18-01 maps to Event/xAOD/xAODMuon/tags/xAODMuon-00-18-01 "
                        "and xAODMuon-00-11-04-branch maps to Event/xAOD/xAODMuon/branches/xAODMuon-00-11-04-branch).")
    parser.add_argument('--svnroot', metavar='SVNDIR',
                        help="Location of the SVN repository (defaults to %(default)s)",
                        default="svn+ssh://svn.cern.ch/reps/atlasoff")
    parser.add_argument('--svnfilterexceptions', '--sfe', metavar="FILE",
                        help="File listing path globs to exempt from SVN import filter (lines with '+PATH') or "
                        "to always reject (lines with '-PATH'); default %(default)s. Use NONE to have no exceptions.",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlasoffline-exceptions.txt"))
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    svn_path_accept, svn_path_reject = load_svn_path_exceptions(args.svnfilterexceptions)

    # Check that we do seem to be in a git repository
    try:
        if not stat.S_ISDIR(os.stat(".git").st_mode):
            raise RuntimeError
    except OSError, RuntimeError:
        logger.error("Please run this script from the root of your git repository")
        sys.exit(1)
    gitrepo = os.getcwd()

    # Map package names to paths
    package_path_dict = map_package_names_to_paths()

    # Now loop over each package we were given
    for svn_package in args.svnpackages:
        package_name, package, svn_package_path = get_svn_path_from_tag_name(svn_package, package_path_dict)
        logger.debug("Will import {0} to {1}".format(os.path.join(package, svn_package_path), package_path_dict[package_name]))
        svn_co_tag_and_commit(args.svnroot, gitrepo, package, svn_package_path,
                              svn_path_accept=svn_path_accept, svn_path_reject=svn_path_reject, commit=False)


if __name__ == '__main__':
    main()
