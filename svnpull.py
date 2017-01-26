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
import fnmatch
import logging
import os.path
import stat
import sys
import re
import textwrap

from glogger import logger
logger.setLevel(logging.WARNING)
from svnutils import svn_co_tag_and_commit, load_exceptions_file
from atutils import find_git_root


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
    if "+" in svn_package:
        package, svn_path = svn_package.split("+", 1)
        package_name = os.path.basename(package)
        package_path_dict[package_name] = package
        return package_name, package, svn_path
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
                 "contains the package you wish to pull an SVN revision onto "
                 "(or use an advanced package specifier).".format(svn_package))
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description=textwrap.dedent('''\
                                    Pull a package revision from SVN and apply to the current athena
                                    git repository.

                                    Run this script from inside the athena git repository clone to
                                    be updated.

                                    SVN package revisions are usually specified as
                                    - A simple package name, which means import the package trunk,
                                      e.g., xAODMuon imports Event/xAOD/xAODMuon/trunk

                                    - A package tag, which imports that SVN tag, e.g., xAODMuon-00-18-01
                                      imports Event/xAOD/xAODMuon/tags/xAODMuon-00-18-01

                                    Some more advanced specifiers can be used for special cases:
                                    - A tag name + "-branch" will import the corresponding development
                                      branch, e.g., xAODMuon-00-11-04-branch will import
                                      Event/xAOD/xAODMuon/branches/xAODMuon-00-11-04-branch

                                    - A package path + SVN sub path, PACKAGEPATH+SVNSUBPATH, where
                                      PACKAGEPATH is the path to the package root in SVN and git and
                                      SVNSUBPATH is the path to the SVN version to import; e.g.,
                                      Reconstruction/RecJobTransforms+devbranches/RecJobTransforms_RAWtoALL
                                      (note the plus sign!) will import the SVN path
                                      Reconstruction/RecJobTransforms/devbranches/RecJobTransforms_RAWtoALL
                                      to Reconstruction/RecJobTransforms

                                    The final specifier is only needed if the package to be imported is
                                    not in your current git checkout or if you want to import an unusual
                                    SVN revision, such as a development branch.
                                    '''),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('svnpackage', nargs="+",
                        help="SVN package to import, usually a plain package name or tag (see above)")
    parser.add_argument('--files', nargs="+",
                        help="Only package files matching the values specified here are imported (globs allowed). "
                        "This can be used to import only some files from the SVN package and will "
                        "disable the normal --svnfilterexceptions matching.")
    parser.add_argument('--revision', type=int, default=0,
                        help="Work at specific SVN revision number instead of HEAD")
    parser.add_argument('--svnroot', metavar='SVNDIR',
                        help="Location of the SVN repository (defaults to %(default)s)",
                        default="svn+ssh://svn.cern.ch/reps/atlasoff")
    parser.add_argument('--svnfilterexceptions', '--sfe', metavar="FILE",
                        help="File listing path globs to exempt from SVN import filter (lines with '+PATH') or "
                        "to always reject (lines with '-PATH'); default %(default)s. "
                        "It is strongly recommended to keep the default value to ensure consistency "
                        "with the official ATLAS migration.",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlasoffline-exceptions.txt"))
    parser.add_argument('--licensefile', metavar="FILE", help="License file to add to C++ and python source code "
                        "files (default %(default)s). "
                        "It is strongly recommended to keep the default value to ensure consistency "
                        "with the official ATLAS migration. Use NONE to disable if it is really necessary.",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "apache2.txt"))
    parser.add_argument('--licenseexceptions', metavar="FILE", help="File listing path globs to exempt from or  "
                        "always apply license file to (same format as --svnfilterexceptions). "
                        "It is strongly recommended to keep the default value to ensure consistency "
                        "with the official ATLAS migration.",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlaslicense-exceptions.txt"))
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode (default is WARNING)")
    parser.add_argument('--info', action="store_true",
                        help="Switch logging into INFO mode (default is WARNING)")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.info:
        logger.setLevel(logging.INFO)
    if args.debug:
        logger.setLevel(logging.DEBUG)
    svn_path_accept, svn_path_reject = load_exceptions_file(args.svnfilterexceptions, reject_changelog=True)

    if len(args.svnpackage) > 1 and len(args.paths) > 0:
        logger.warning("You have specified multiple SVN packages and to filter on package files "
                       "to import. Make sure your --packagefiles options import the correct "
                       "files in all packages.")

    # Check that we do seem to be in a git repository
    gitrepo = find_git_root()
    if not gitrepo:
        logger.fatal("Not a git repository (or any of the parent directories), run from inside a clone of the athena repository.")
        sys.exit(1)
    os.chdir(gitrepo)

    # License file loading
    if args.licensefile and args.licensefile != "NONE":
        with open(args.licensefile) as lfh:
            license_text = [ line.rstrip() for line in lfh.readlines() ]
    else:
        license_text = None
    if args.licenseexceptions:
        license_path_accept, license_path_reject = load_exceptions_file(args.licenseexceptions)
    else:
        license_path_accept = license_path_reject = []

    # Map package names to paths
    package_path_dict = map_package_names_to_paths()

    # Now loop over each package we were given
    try:
        for svn_package in args.svnpackage:
            package_name, package, svn_package_path = get_svn_path_from_tag_name(svn_package, package_path_dict)
            # If we have a --files option then redo the accept/reject paths here
            # (as the package path needs to be prepended it needs to happen in this loop)
            if args.files:
                svn_path_reject = [re.compile(fnmatch.translate("*"))]
                svn_path_accept = []
                for glob in args.files:
                    package_glob = os.path.join(package_path_dict[package_name], glob)
                    logger.debug("Will accept files matching {0}".format(package_glob))
                    svn_path_accept.append(re.compile(fnmatch.translate(package_glob)))
                logger.debug("{0}".format([ m.pattern for m in svn_path_accept ]))
            logger.debug("Will import {0} to {1}, SVN revision {2}".format(os.path.join(package, svn_package_path),
                                                                           package_path_dict[package_name],
                                                                           "HEAD" if args.revision == 0 else args.revision))
            svn_co_tag_and_commit(args.svnroot, gitrepo, package, svn_package_path,
                                  svn_path_accept=svn_path_accept, svn_path_reject=svn_path_reject, commit=False,
                                  revision=args.revision,
                                  license_text=license_text,
                                  license_path_accept=license_path_accept,
                                  license_path_reject=license_path_reject,
                                  )
    except RuntimeError as e:
        logger.error("Got a RuntimeError raised when processing package {0} ({1}). "
                     "Usually this is caused by a failure to checkout from SVN, meaning you "
                     "specified a package tag that does not exist, or even a package that "
                     "does not exist. See --help for how to specify what to import.".format(svn_package, e))


if __name__ == '__main__':
    main()
