#! /usr/bin/env python
#
# # SVN utility functions used by atlasgit scripts
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

import fnmatch
import logging
import os
import os.path
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as eltree

from glogger import logger
from atutils import check_output_with_retry, changelog_diff, author_string, get_flattened_git_tag


def author_info_lookup(author_name):
    try:
        cmd = ["phonebook", "--login", author_name, "--terse", "firstname", "--terse", "surname", "--terse", "email"]
        author_info = check_output_with_retry(cmd, retries=1).strip().split(";")
        return {"name": " ".join(author_info[:2]), "email": author_info[2]}
    except IndexError:
        raise RuntimeError("Had a problem decoding phonebook info for '{0}'".format(author_name))


def svn_tag_cmp(tag_x, tag_y):
    # # @brief Special sort for svn paths, which always places trunk after any tags
    if tag_x == "trunk":
         return 1
    elif tag_y == "trunk":
        return -1
    return cmp(tag_x, tag_y)


def scan_svn_tags_and_get_metadata(svnroot, svn_packages, svn_metadata_cache, author_metadata_cache, all_package_tags=False):
    # # @brief Get SVN metadata for each of the package tags we're interested in
    #  @param svnroot URL of SVN repository
    #  @param svn_packages Dictionary of packages and tags to process
    #  @param svn_metadata_cache SVN metadata cache
    #  @param author_metadata_cache author metadata cache with name and email for commits
    #  @param all_package_tags Boolean flag triggering import of all package tags in SVN

    # First we establish the list of tags which we need to deal with.
    for package, package_tags in svn_packages.iteritems():
        logger.info("Preparing package {0} (base tags: {1})".format(package, package_tags))
        if all_package_tags:
            oldest_tag = svn_packages[package][0]
            tags = get_all_package_tags(svnroot, package)
            try:
                package_tags.extend(tags[tags.index(oldest_tag) + 1:])
            except ValueError:
                logger.error("Oldest release tag ({0}) for package {1} not found in SVN!".format(oldest_tag, package))
                sys.exit(1)
        # We need to now sort the package tags and remove any duplicates
        ordered_tags = list(set(package_tags))
        ordered_tags.sort(cmp=svn_tag_cmp)
        svn_packages[package] = ordered_tags

    # Now iterate over the required tags and ensure we have the necessary metadata
    for package, package_tags in svn_packages.iteritems():
        package_name = os.path.basename(package)
        package_path = os.path.dirname(package)
        for tag in package_tags:
            # Do we have metadata?
            if package_name not in svn_metadata_cache:
                svn_metadata_cache[package_name] = {"path": package_path, "svn": {}}
            try:
                if tag == "trunk":
                    # We always need to get the metadata for trunk tags as we need to
                    # know the current revision
                    svn_metadata = svn_get_path_metadata(svnroot, package, tag)
                    if tag not in svn_metadata_cache[package_name]["svn"]:
                        svn_metadata_cache[package_name]["svn"][tag] = {svn_metadata["revision"]: svn_metadata}
                    elif svn_metadata["revision"] not in svn_metadata_cache[package_name]["svn"][tag]:
                        svn_metadata_cache[package_name]["svn"][tag][svn_metadata["revision"]] = svn_metadata
                elif tag not in svn_metadata_cache[package_name]["svn"]:
                    svn_metadata = svn_get_path_metadata(svnroot, package, tag)
                    svn_metadata_cache[package_name]["svn"][tag] = {svn_metadata["revision"]: svn_metadata}
                else:
                    svn_metadata = svn_metadata_cache[package_name]["svn"][tag].values()[0]
                if svn_metadata["author"] not in author_metadata_cache:
                    try:
                        author_metadata_cache[svn_metadata["author"]] = author_info_lookup(svn_metadata["author"])
                    except RuntimeError, e:
                        logger.info("Failed to get author information for {0}: {1}".format(package, e))
                        author_metadata_cache[svn_metadata["author"]] = {"name": svn_metadata["author"],
                                                                         "email": "{0}@cern.ch".format(svn_metadata["author"])}
            except RuntimeError:
                logger.warning("Failed to get SVN metadata for {0}".format(os.path.join(package, tag)))


def svn_get_path_metadata(svnroot, package, package_path, revision=None):
    # # @brief Get SVN metadata and return as a simple dictionary keyed on date, author and commit revision
    logger.info("Querying SVN metadata for {0}".format(os.path.join(package, package_path)))
    cmd = ["svn", "info", os.path.join(svnroot, package, package_path), "--xml"]
    svn_info = check_output_with_retry(cmd)
    tree = eltree.fromstring(svn_info)
    info = {"date": tree.find(".//date").text.rsplit(".",1)[0], # Strip off sub-second part
            "author": tree.find(".//author").text,
            "revision": tree.find(".//commit").attrib['revision']}

    cmd = ["svn", "log", os.path.join(svnroot, package, package_path), "-r", info["revision"], "--xml"]
    svn_log = check_output_with_retry(cmd)
    tree = eltree.fromstring(svn_log)
    info["msg"] = tree.find(".//msg").text.strip()
    return info


def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, svn_metadata=None, author_metadata_cache=None, branch=None,
                          svn_path_accept=[], svn_path_reject=[], commit=True,
                          license_text=None, license_exclude=[]):
    # # @brief Make a temporary space, check out from svn, clean-up, copy and then git commit and tag
    #  @param svnroot Base path to SVN repository
    #  @param gitrepo Path to git repository to import to
    #  @param package Path to package root (in git and svn)
    #  @param tag Package tag to import (i.e., path after base package path)
    #  @param svn_metadata SVN metadata cache
    #  @param author_metadata_cache Author name/email cache
    #  @param branch Git branch to switch to before import
    #  @param svn_path_accept Paths to force import to git
    #  @param svn_path_reject Paths to force reject from the import
    #  @param commit Boolean flag to manage commit (can be set to @c False to only checkout and process)
    #  @param license_text List of strings containing the license text to add (if @c False, then no
    #  license file is added)
    #  @param license_exclude Paths to exclude from license file addition
    msg = "Importing SVN path {0}/{1} to {0}".format(package, tag)
    if svn_metadata and tag == "trunk":
        msg += " (r{0})".format(svn_metadata["revision"])
    logger.info(msg)

    if branch:
        logger.info("Switching to branch {0}".format(branch))
        switch_to_branch(args.targetbranch)

    tempdir = tempfile.mkdtemp()
    full_svn_path = os.path.join(tempdir, package)
    cmd = ["svn", "checkout"]
    if svn_metadata:
        cmd.extend(["-r", svn_metadata["revision"]])
    cmd.extend([os.path.join(svnroot, package, tag), os.path.join(tempdir, package)])
    check_output_with_retry(cmd, retries=1, wait=3)

    # Clean out directory of things we don't want to import
    svn_cleanup(full_svn_path, svn_co_root=tempdir,
                svn_path_accept=svn_path_accept, svn_path_reject=svn_path_reject)
    
    # If desired, inject a licence into the source code
    if license_text:
        svn_license_injector(full_svn_path, svn_co_root=tempdir, license_text=license_text, license_exclude=[])

    # Copy to git
    full_git_path = os.path.join(gitrepo, package)
    package_root, package_name = os.path.split(full_git_path)
    try:
        if os.path.isdir(full_git_path):
            shutil.rmtree(full_git_path, ignore_errors=True)
        os.makedirs(package_root)
    except OSError:
        pass
    shutil.move(full_svn_path, package_root)

    if commit:
        # get ChangeLog diff
        cl_diff = changelog_diff(package)

        # Commit
        check_output_with_retry(("git", "add", "-A", package))
        if logger.level <= logging.DEBUG:
            logger.debug(check_output_with_retry(("git", "status")))


        cmd = ["git", "commit", "--allow-empty", "-m", "{0} ({1} - r{2})".
               format(svn_metadata['msg'], tag.replace('tags/','',1), svn_metadata['revision'])]
        if svn_metadata:
            cmd.extend(("--author='{0}'".format(author_string(svn_metadata["author"], author_metadata_cache)),
                        "--date={0}".format(svn_metadata["date"])))
        if cl_diff:
            cmd.extend(("-m", "Diff in ChangeLog:\n" + '\n'.join(cl_diff)))
        check_output_with_retry(cmd)
        cmd = ["git", "tag", "-a", get_flattened_git_tag(package, tag, svn_metadata["revision"]), "-m", ""]
        check_output_with_retry(cmd)

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
                if fnmatch.fnmatch(svn_filename, filter):
                    logger.info("{0} imported from globbed exception {1}".format(svn_filename, filter))
                    path_accept_match = True
                    break
            if path_accept_match:
                continue
            try:
                if os.stat(filename).st_size > 100 * 1024:
                    if "." in name and name.rsplit(".", 1)[1] in ("cxx", "py", "h", "java", "cc", "c", "icc", "cpp",
                                                                  "hpp", "hh", "f", "F"):
                        logger.info("Source file {0} is too large, but importing anyway (source files always imported)".format(filename))
                    else:
                        logger.warning("File {0} is too large - not importing".format(filename))
                        os.remove(filename)
                if name.startswith("."):
                    logger.warning("File {0} starts with a '.' - not importing".format(filename))
                    os.remove(filename)

                # Rejection always overrides the above
                for filter in svn_path_reject:
                    if fnmatch.fnmatch(svn_filename, filter):
                        logger.info("{0} not imported due to {1} filter".format(svn_filename, filter))
                        os.remove(filename)

            except OSError, e:
                logger.warning("Got OSError treating {0}: {1}".format(filename, e))


def svn_license_injector(svn_path, svn_co_root, license_text, license_exclude=[]):
    ## @brief Add license statements to code before import
    #  @param svn_path Filesystem path to cleaned up SVN checkout
    #  @param svn_co_root Base directory of SVN checkout
    #  @param license_text List of strings that comprise the license to apply
    #  @param license_exclude List of glob path matches to exclude from
    #   license file addition
    for root, dirs, files in os.walk(svn_path):
        for name in files:
            filename = os.path.join(root, name)
            svn_filename = filename[len(svn_co_root) + 1:]
            path_veto = False
            for filter in license_exclude:
                if fnmatch.fnmatch(svn_filename, filter):
                    logger.info("File {0} will not have a license file applied".format(svn_filename, filter))
                    path_veto = True
                    break
            if path_veto:
                contune
            extension = svn_filename.rsplit(".", 1)[1] if "." in svn_filename else ""
            if extension in ("cxx", "cpp", "icc", "cc", "c", "C", "h", "hpp", "hh"):
                inject_c_license(filename, license_text)
            elif extension == "py":
                inject_py_license(filename, license_text)
                

def inject_c_license(filename, license_text):
    ## @brief Add a license file, C style commented
    target_filename = filename + ".license"
    with open(filename) as ifh, open(target_filename, "w") as ofh:
        print >> ofh, "/*"
        for line in license_text:
            print >> ofh, " ", line
        print >> ofh, "*/\n"
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
            print >> ofh, ""
            for line in license_text:
                print >> ofh, "#", line
            print >> ofh, ""
        else:
            for line in license_text:
                print >> ofh, "#", line
            print >> ofh, ""
            ofh.write(first_line)
        for line in ifh:
            ofh.write(line)
    os.rename(target_filename, filename)


def load_svn_path_exceptions(filename):
    ## @brief Parse and return SVN import exceptions file
    #  @param filename File containing exceptions
    #  @return Tuple of path globs to always accept and globs to always reject
    svn_path_accept = []
    svn_path_reject = []
    if filename != "NONE":
        with open(filename) as svnfilt:
            logger.info("Loaded import exceptions from {0}".format(filename))
            for line in svnfilt:
                line = line.strip()
                if line.startswith("#") or line == "":
                    continue
                if line.startswith("-"):
                    svn_path_reject.append(line.lstrip("- "))
                else:
                    svn_path_accept.append(line.lstrip("+ "))
    logger.debug("Glob accept: {0}".format(svn_path_accept))
    logger.debug("Glob reject: {0}".format(svn_path_reject))
    return svn_path_accept, svn_path_reject
