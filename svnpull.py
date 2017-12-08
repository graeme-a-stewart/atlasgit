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
import os
import os.path
import shutil
import stat
import subprocess
import sys
import re
import textwrap
import tempfile
import time

from glogger import logger
logger.setLevel(logging.WARNING)


def check_output_with_retry(cmd, retries=2, wait=10, ignore_fail=False, dryrun=False):
    ## @brief Multiple attempt wrapper for subprocess.check_call (especially remote SVN commands can bork)
    #  @param cmd list or tuple of command line parameters
    #  @param retries Number of attempts to execute successfully
    #  @param wait Sleep time after an unsuccessful execution attempt
    #  @param ignore_fail Do not raise an exception if the command fails
    #  @param dryrun If @c True do not actually execute the command, only print it and return an empty string
    #  @return String containing command output
    if dryrun:
        logger.info("Dryrun mode: {0}".format(cmd))
        return ""
    success = failure = False
    tries = 0
    start = time.time()
    while not success and not failure:
        tries += 1
        try:
            logger.debug("Calling {0}".format(cmd))
            output = subprocess.check_output(cmd)
            success = True
        except subprocess.CalledProcessError:
            if ignore_fail:
                success = True
                output = ""
                continue
            logger.warning("Attempt {0} to execute {1} failed".format(tries, cmd))
            if tries > retries:
                failure = True
            else:
                time.sleep(wait)
    if failure:
        raise RuntimeError("Repeated failures to execute {0}".format(cmd))
    logger.debug("Executed in {0}s".format(time.time() - start))
    return output


def find_git_root():
    ## @brief Search for a git repository root from cwd
    found_git = False
    start = searching = os.getcwd()
    while True:
        if os.path.isdir(".git"):
            found_git = True
            break
        else:
            os.chdir("..")
            if os.getcwd() == searching:  # Hit filesystem root
                break
            searching = os.getcwd()

    os.chdir(start)
    if found_git and git_repo_ok(os.path.join(searching, ".git")):
        logger.debug("Found .git for repository root here: {0}".format(searching))
        return searching

    logger.debug("No valid .git found descending from {0}".format(start))
    return None


def git_repo_ok(path="."):
    ## @brief Check if a directory seems to contain a valid git repository
    #  @param path Path to check
    #  @return Boolean, @c True if the repo seems valid
    entries = os.listdir(path)
    try:
        if (os.path.isfile(os.path.join(path, "HEAD")) and
            os.path.isdir(os.path.join(path, "objects")) and
            os.path.isdir(os.path.join(path, "refs"))):
            return True
    except OSError:
        return False
    return False

def load_exceptions_file(filename, reject_changelog=False):
    ## @brief Parse and return path globbing exceptions file
    #  @param filename File containing exceptions
    #  @param reject_changelog Special flag used by svnpull to ensure that
    #  ChangeLog files are rejected (in a normal svn2git they are accepted,
    #  onto the import branches, but then excluded specially from the
    #  release branches)
    #  @return Tuple of path globs to accept and globs to reject, converted to regexps
    path_accept = []
    path_reject = []
    if filename != "NONE":
        with open(filename) as filter_file:
            logger.info("Loaded import exceptions from {0}".format(filename))
            for line in filter_file:
                line = line.strip()
                if reject_changelog and ("ChangeLog" in line):
                    logger.debug("Found ChangeLog line, which will be forced to reject: {0}".format(line))
                    line = "- */ChangeLog"
                if line.startswith("#") or line == "":
                    continue
                if line.startswith("-"):
                    path_reject.append(re.compile(fnmatch.translate(line.lstrip("- "))))
                else:
                    path_accept.append(re.compile(fnmatch.translate(line.lstrip("+ "))))
    logger.debug("Glob accept: {0}".format([ m.pattern for m in path_accept ]))
    logger.debug("Glob reject: {0}".format([ m.pattern for m in path_reject ]))
    return path_accept, path_reject


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


def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, full_clobber=True,
                          svn_path_accept=[], svn_path_reject=[], revision=None,
                          license_text=None, license_path_accept=[], license_path_reject=[]):
    ## @brief Make a temporary space, check out from svn, clean-up and copy into git checkout
    #  @param svnroot Base path to SVN repository
    #  @param gitrepo Path to git repository to import to
    #  @param package Path to package root (in git and svn)
    #  @param tag Package tag to import (i.e., path after base package path)
    #  @param full_clobber If @c True then all current files are deleted, if false then
    #  only newly imported files are copied to checkout
    #  @param svn_path_accept Paths to force import to git
    #  @param svn_path_reject Paths to force reject from the import
    #  @param license_text List of strings containing the license text to add (if @c False, then no
    #  license file is added)
    #  @param revision Force SVN revision number
    #  @param license_path_accept Paths to force include in license file addition
    #  @param license_path_reject Paths to exclude from license file addition
    msg = "Importing SVN path {0}/{1} to {2}/{0}".format(package, tag, gitrepo)
    logger.info(msg)

    tempdir = tempfile.mkdtemp()
    full_svn_path = os.path.join(tempdir, package)
    cmd = ["svn", "checkout"]
    if revision:
        cmd.extend(["-r", str(revision)])
    cmd.extend([os.path.join(svnroot, package, tag), os.path.join(tempdir, package)])
    check_output_with_retry(cmd, retries=1, wait=3)

    # Clean out directory of things we don't want to import
    svn_cleanup(full_svn_path, svn_co_root=tempdir,
                svn_path_accept=svn_path_accept, svn_path_reject=svn_path_reject)

    # Remove SVN '$Id:' lines from source files (FIXME: what files are affected, *.[Cc], *.cxx, *.h[h]*, etc.?)
    svn_strip_Id(full_svn_path, svn_co_root=tempdir)
    
    # If desired, inject a licence into the source code
    if license_text:
        svn_license_injector(full_svn_path, svn_co_root=tempdir, license_text=license_text,
                             license_path_accept=license_path_accept, license_path_reject=license_path_reject)

    # Copy to git
    full_git_path = os.path.join(gitrepo, package)
    package_root, package_name = os.path.split(full_git_path)
    if full_clobber:
        try:
            # We need to be a little more sophisticated here,
            # as the doxygen change on the master branch of
            # git rewrote docs/mainpage.h to docs/packagedoc.h
            # So we do need to keep that file as least, if it is
            # not in the SVN pull area
            pkgdoc = os.path.join(package, "doc", "packagedoc.h")
            if os.access(pkgdoc, os.R_OK):
                dest_dir = os.path.join(full_svn_path, "doc")
                if not os.access(os.path.join(dest_dir, "packagedoc.h"), os.R_OK):
                    try:
                        os.makedirs(os.path.join(full_svn_path, "doc"))
                    except OSError:
                        pass
                    shutil.copy2(pkgdoc, dest_dir)
                    logger.info("Doxygen file packagedoc.h was backed up before overwrite")
            shutil.rmtree(full_git_path, ignore_errors=True)
            os.makedirs(package_root)
        except OSError:
            pass
        logger.info("Replacing complete current git checkout with {0}".format(os.path.join(package, tag)))
        shutil.move(full_svn_path, package_root)
    else:
        for root, dirs, files in os.walk(full_svn_path):
            for name in files:
                src_filename = os.path.join(root, name)
                dst_filename = os.path.join(src_filename[len(tempdir) + 1:])
                logger.info("Pulling {0} into git checkout".format(dst_filename))
                if not os.access(os.path.basename(dst_filename), os.R_OK):
                    os.makedirs(os.path.basename(dst_filename))
                shutil.copy2(src_filename, dst_filename)

    # Clean up
    shutil.rmtree(tempdir)

def svn_cleanup(svn_path, svn_co_root, svn_path_accept=[], svn_path_reject=[]):
    # # @brief Cleanout files we do not want to import into git
    #  @param svn_path Full path to checkout of SVN package
    #  @param svn_co_root Base directory of SVN checkout
    #  @param svn_path_accept List of file path globs to always import to git
    #  @param svn_path_reject List of file path globs to never import to git

    # File size veto
    for root, dirs, files in os.walk(svn_path):
        if ".svn" in dirs:
            shutil.rmtree(os.path.join(root, ".svn"))
            dirs.remove(".svn")
        for name in files:
            filename = os.path.join(root, name)
            svn_filename = filename[len(svn_co_root) + 1:]
            path_accept_match = False
            for filter in svn_path_accept:
                if re.match(filter, svn_filename):
                    logger.debug("{0} imported from globbed exception {1}".format(svn_filename, filter.pattern))
                    path_accept_match = True
                    break
            if path_accept_match:
                continue
            try:
                # Rejection always takes precedence
                for filter in svn_path_reject:
                    if re.match(filter, svn_filename):
                        logger.debug("{0} not imported due to {1} filter".format(svn_filename, filter.pattern))
                        os.remove(filename)
                        continue

                if os.lstat(filename).st_size > 100 * 1024:
                    if "." in name and name.rsplit(".", 1)[1] in ("cxx", "py", "h", "java", "cc", "c", "icc", "cpp",
                                                                  "hpp", "hh", "f", "F"):
                        logger.debug("Source file {0} is too large, but importing anyway (source files always imported)".format(filename))
                    else:
                        logger.debug("File {0} is too large - not importing".format(filename))
                        os.remove(filename)
                        continue
                if name.startswith("."):
                    logger.debug("File {0} starts with a '.' - not importing".format(filename))
                    os.remove(filename)
                    continue

            except OSError, e:
                logger.debug("Got OSError (harmless!) treating {0}: {1}".format(filename, e))
    
    # Clean up all empty directories...
    for root, dirs, files in os.walk(svn_path, topdown=False):
        if len(os.listdir(root)) == 0:
            os.rmdir(root)


def svn_strip_Id(svn_path, svn_co_root):
    for root, dirs, files in os.walk(svn_path):
        for name in files:
            filename = os.path.join(root, name)
            svn_filename = filename[len(svn_co_root) + 1:]
            if "." in svn_filename:
               extension = svn_filename.rsplit(".", 1)[1] 
            else:
               extension = ""
            #FIXME: what files were commented with '$Id:'?
            if svn_filename == "Makefile" or extension in ("txt", "cxx", "cpp", "icc", "cc", "c", "C", "h", "hpp", "hh" , "py" , "cmake"):
               try:
                   ifh = open(filename) 
               except:
                   logger.error("can't open {0}. EXIT(1)".format(filename))
                   sys.exit(1)
               first_line = ifh.readline()
               #FIXME: check if $Id: is correctly commented out, e.g. /* $Id: .... */ in .c
               if re.match('^.*\$Id: .*$',first_line):
                   target_filename = filename + ".STRIP"
                   try:
                       ofh = open(target_filename,"w")
                   except:
                       logger.error("can't open {0} in write mode. EXIT(1)".format(target_filename))
                       sys.exit(1)
                   for line in ifh:
                       ofh.write(line)
                   ifh.close()
                   ofh.close()
                   os.rename(target_filename,filename)
               else:
                   ifh.close()


def svn_license_injector(svn_path, svn_co_root, license_text, license_path_accept=[], license_path_reject=[]):
    ## @brief Add license statements to code before import
    #  @param svn_path Filesystem path to cleaned up SVN checkout
    #  @param svn_co_root Base directory of SVN checkout
    #  @param license_text List of strings that comprise the license to apply
    #  @param license_path_accept Paths to force include in license file addition (NOT IMPLEMENTED YET)
    #  @param license_path_reject Paths to exclude from license file addition
    #   license file addition
    for root, dirs, files in os.walk(svn_path):
        for name in files:
            filename = os.path.join(root, name)
            svn_filename = filename[len(svn_co_root) + 1:]
            path_veto = False
            for filter in license_path_reject:
                if re.match(filter, svn_filename):
                    logger.debug("File {0} will not have a license file applied".format(svn_filename, filter.pattern))
                    path_veto = True
                    break
            for filter in license_path_accept:
                if re.match(filter, svn_filename):
                    logger.debug("File {0} will have a license file applied".format(svn_filename, filter.pattern))
                    path_veto = False
                    break
            if path_veto:
                continue
            # Get the file's mode here to then restore it
            try:
                fmode = os.stat(filename).st_mode
                extension = svn_filename.rsplit(".", 1)[1] if "." in svn_filename else ""
                if extension in ("cxx", "cpp", "icc", "cc", "c", "C", "h", "hpp", "hh"):
                    inject_c_license(filename, license_text)
                    os.chmod(filename, fmode)
                elif extension in ("py", "cmake"):
                    inject_py_license(filename, license_text)
                    os.chmod(filename, fmode)
            except OSError, e:
                # Can happen if a file is a softlink to nowhere
                logger.warning("Got an exception on stating {0}: {1}".format(filename, e))


def inject_c_license(filename, license_text):
    ## @brief Add a license file, C style commented
    target_filename = filename + ".license"
    with open(filename) as ifh, open(target_filename, "w") as ofh:
        first_line = ifh.readline()
        # If the first line is a -*- C++ -*- then it has to stay the
        # first line
        if re.search(r"-\*-\s+[cC]\+\+\s+-\*\-", first_line):
            multi_line_c_comment = False
            # Beware of breaking a multi-line C style comment
            if first_line.startswith("/*") and ("*/" not in first_line[2:]):
                first_line = first_line[:-1] + " */\n"
                multi_line_c_comment = True
            ofh.write(first_line)
            ofh.write("\n/*\n")
            for line in license_text:
                ofh.write("  {0}\n".format(line)) if line != "" else ofh.write("\n")
            ofh.write("*/\n\n")
            if multi_line_c_comment:
                ofh.write("/*\n")
        else:
            ofh.write("/*\n")
            for line in license_text:
                ofh.write("  {0}\n".format(line)) if line != "" else ofh.write("\n")
            ofh.write("*/\n\n")
            ofh.write(first_line)
        for line in ifh:
            ofh.write(line)
    os.rename(target_filename, filename)


def inject_py_license(filename, license_text):
    ## @brief Add a license file, python style commented
    target_filename = filename + ".license"
    with open(filename) as ifh, open(target_filename, "w") as ofh:
        first_line = ifh.readline()
        # If the first line is a #! then it has to stay the
        # first line
        if first_line.startswith("#!"):
            ofh.write(first_line)
            ofh.write("\n")
            for line in license_text:
                ofh.write("# {0}\n".format(line)) if line != "" else ofh.write("#\n")
        else:
            for line in license_text:
                ofh.write("# {0}\n".format(line)) if line != "" else ofh.write("#\n")
            ofh.write("\n")
            ofh.write(first_line)
        for line in ifh:
            ofh.write(line)
    os.rename(target_filename, filename)


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

                                    The --files specifier can be used to import only some files or paths
                                    to git, with globs supported, e.g.,

                                      --files src/* MyPackage/*.h share/important_file.py

                                    For consistency all options applied during the primary ATLAS SVN to
                                    git migration are re-applied by default.
                                    '''),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('svnpackage', nargs="+",
                        help="SVN package to import, usually a plain package name or tag (see above)")
    parser.add_argument('--files', nargs="+",
                        help="Only package files matching the values specified here are imported (globs allowed). "
                        "This can be used to import only some files from the SVN package and will "
                        "disable the normal --svnfilterexceptions matching.", default=[])
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
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cerncopy.txt"))
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

    if len(args.svnpackage) > 1 and args.files:
        logger.error("You have specified multiple SVN packages and to filter on package files "
                       "to import, which almost certainly will not work - aborting")
        sys.exit(1)

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
            full_clobber = True
            package_name, package, svn_package_path = get_svn_path_from_tag_name(svn_package, package_path_dict)
            # If we have a --files option then redo the accept/reject paths here
            # (as the package path needs to be prepended it needs to happen in this loop)
            if args.files:
                full_clobber = False
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
            svn_co_tag_and_commit(args.svnroot, gitrepo, package, svn_package_path, full_clobber,
                                  svn_path_accept=svn_path_accept, svn_path_reject=svn_path_reject,
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
        sys.exit(1)

    print textwrap.fill("Pull from SVN succeeded. Use 'git status' to check which files "
                        "have been changed and 'git diff' to review the changes in detail. "
                        "When you are happy with your changes commit with a good commit message - "
                        "as an update has been done from SVN it is recommended to give the "
                        "SVN tag in the one line commit summary.")


if __name__ == '__main__':
    main()
