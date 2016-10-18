## General utilities used by the atlastags scripts
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

import json
import os
import os.path
import re
import shutil
import subprocess
import time

from glogger import logger

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
    logger.debug("Executed in {0}s".format(time.time()-start))
    return output


def recursive_delete(directory=None):
    '''Delete all files in the repository working copy'''
    if not directory:
        directory="."
    try:
        for entry in os.listdir(directory):
            if entry.startswith("."):
                continue
            entry = os.path.join(directory, entry)
            if os.path.isfile(entry):
                os.unlink(entry)
            elif os.path.isdir(entry):
                shutil.rmtree(entry)
    except OSError:
        pass


def get_current_git_tags(gitrepo=None):
    ## @brief Return a list of current git tags
    if gitrepo:
        os.chdir(gitrepo)
    cmd = ["git", "tag", "-l"]
    return check_output_with_retry(cmd).split("\n")


def get_flattened_git_tag(package, svntag, revision, branch=None):
    ## @brief Construct a git tag to signal the import of a particular SVN tag or revision
    #  @param Package path
    #  @param svntag SVN tag (or @c trunk)
    #  @param revision SVN revision number
    #  @param branch Create tag for a specific branch import (if present)
    if svntag == "trunk":
        git_tag = os.path.join("import","{0}-r{1}".format(os.path.basename(package), revision))
    else:
        git_tag = os.path.join("import", os.path.basename(svntag))
    if branch:
        git_tag = os.path.join(branch, git_tag)
    return git_tag


def changelog_diff(package, staged=False):
    ## @brief Return a cleaned up ChangeLog diff - this is only as useful as what the developer wrote!
    #  @param package Path to package
    #  @param staged Diff for staged files, instead of unstaged changes
    #  @return ChangeLog diff (truncated if needed) 
    truncate_lines = 20
    o_lines = []
    cl_file = os.path.join(package, 'ChangeLog')
    if os.path.isfile(cl_file):
        exists = check_output_with_retry(("git", "ls-tree", "HEAD", cl_file), ignore_fail=True, retries=0)
        if exists:
            cmd = ["git", "diff", "-U0"]
            if staged:
                cmd.append("--staged")
            cmd.append(cl_file)
            o_lines = check_output_with_retry(cmd, retries=1).split("\n")
            o_lines = [ line.lstrip("+") for line in o_lines[6:] if line.startswith("+") and not re.search(r"(\s[MADR]\s+[\w\/\.]+)|(@@)", line) ]
            if len(o_lines) > truncate_lines:
                o_lines = o_lines[:truncate_lines]
                o_lines.append("...")
                o_lines.append("(Long ChangeLog diff - truncated)")
            logger.debug("Found {0} line ChangeLog diff".format(len(o_lines)))
        else:
            logger.debug("First package commit - not diffing ChangeLog")
    else:
        logger.debug("ChangeLog file {0} not found".format(cl_file))
    return o_lines


def author_string(author, author_metadata_cache):
    ## @brief Write a formatted commit author string
    #  @param author SVN author name
    #  @param author_metadata_cache Dictionary of names and email addresses
    try:
        return "{0} <{1}>".format(author_metadata_cache[author]["name"], author_metadata_cache[author]["email"])
    except KeyError:
        pass
    
    if re.search(r"<[a-zA-Z0-9-]+@[a-zA-Z0-9-]+>", author):
        return author
    elif re.match(r"[a-zA-Z0-9]+$", author):
        return "{0} <{0}@cern.ch>".format(author)
    return author


def initialise_metadata(cachefile):
    ## @brief Load existing cache file, if it exists, or return empty cache
    #  @param cachefile Name of  cache file (serialised in JSON)
    if os.path.exists(cachefile):
        logger.info("Reloading cache from {0}".format(cachefile))
        with file(cachefile) as md_load:
            svn_metadata_cache = json.load(md_load)
    else:
        svn_metadata_cache = {}
    return svn_metadata_cache


def backup_metadata(svn_metadata_cache, start_cwd, cachefile, start_timestamp_string):
    ## @brief Persistify SVN metadata cache in JSON format
    #  @param svn_metadata_cache SVN metadata cache
    #  @param start_cwd Directory to change to before dumping
    #  @param start_timestamp_string Timestamp backup for previous version of the cache
    os.chdir(start_cwd)
    if os.path.exists(cachefile):
        os.rename(cachefile, cachefile+".bak."+start_timestamp_string)
    with file(cachefile, "w") as md_dump:
        json.dump(svn_metadata_cache, md_dump, indent=2)


def switch_to_branch(branch, orphan=False):
    ## @brief Switch to branch, creating it if necessary
    #  @param branch Branch to switch to or create
    #  @param orphan If @c Ture then create branch as an orphan and delete all current files
    current_branch = check_output_with_retry(("git", "symbolic-ref", "HEAD", "--short"))
    if branch != current_branch:
        all_branches = [ line.lstrip(" *") for line in check_output_with_retry(("git", "branch", "-l")).splitlines() ]
        if branch in all_branches:
            check_output_with_retry(("git", "checkout", branch))
        elif not orphan:
            check_output_with_retry(("git", "checkout", "-B", branch))
        else:
            check_output_with_retry(("git", "checkout", "--orphan", branch))
            # Clean up the new branch, deleting all files and clearing the staging area
            recursive_delete(".")
            check_output_with_retry(("git", "rm", "-r", "--cached", "--ignore-unmatch", "."))


def find_best_arch(base_path):
    ## @brief Find the "best" achitecture when various install architectures are available
    #  for a particular release ("opt" release is preferred)
    #  @param base_path Directory path to architecture subdirectories
    #  @return Chosen architecture
    best_arch = None
    logger.debug("Finding best architecture in {0}".format(base_path))
    arch = os.listdir(base_path)
    logger.debug("Choices: {0}".format(" ".join(arch)))
    if len(arch) == 1:
        best_arch = arch[0]
    else:
        opt_arch = [ a for a in arch if a.endswith("opt") ]
        if len(opt_arch) == 1:
            best_arch = opt_arch[0]
        else:
            opt_arch.sort()
            best_arch = opt_arch[0]
    if not best_arch:
        raise RuntimeError("Failed to find a good architecture from {0}".format(base_path))
    logger.debug("Best archfile for {0} is {1} (chosen from {2})".format(base_path, best_arch, len(arch)))
    return best_arch


def release_compare(rel1, rel2):
    ## @brief Provide a release number comparison (for sort) between A.B.X[.Y] releases
    #  @param rel1 String with first release name
    #  @param rel2 String with second release name
    #  @return -1, 0 or 1 depending on comparison
    rel1_el = [ int(bit) for bit in rel1.split(".") ]
    rel2_el = [ int(bit) for bit in rel2.split(".") ]
    return do_version_compare(rel1_el, rel2_el)


def package_compare(pkg1, pkg2):
    ## @brief Provide a release number comparison (sortable) between svn package tags
    #  @param pkg1 First package
    #  @param pkg2 Second package
    #  @return -1, 0 or 1 depending on comparison
    pkg1_el = pkg1.split("-")
    pkg2_el = pkg2.split("-")
    if pkg1_el[0] != pkg2_el[0]:
        # Not the same package - this is meaningless
        raise RuntimeError("Package comparison called for different packages: {0} and {1}".format(pkg1, pkg2))
    pkg1_version_el = [ int(v) for v in pkg1_el[1:] ]
    pkg2_version_el = [ int(v) for v in pkg2_el[1:] ]
    return do_version_compare(pkg1_version_el, pkg2_version_el)


def do_version_compare(v1, v2):
    ## @brief Do a comparison between two iterables returning which one is "greater" then the other
    #  going item by item from the beginning to the end
    #  @param pkg1 First list
    #  @param pkg2 Second list
    #  @return -1, 0 or 1 depending on comparison
    for el in range(0, max(len(v1), len(v2))):
        try:
            if v1[el] > v2[el]:
                return 1
            elif v1[el] < v2[el]:
                return -1
        except IndexError:
            # One of the releases is 'shorter' than the other, and
            # we sort that one as first
            if len(v1) > len(v2):
                return 1
            return -1
    return 0    


def is_svn_branch_tag(svn_tag):
    ## @brief Return true if this tag is a branch tag (i.e., 4 digit)
    #  @param svn_tag tag to test
    #  @return Boolean
    if len(svn_tag.split("-")) > 4:
        return True
    return False


def branch_exists(branch):
    ## @brief Return a boolean if a branch of said name exists
    #  @param branch Branch name to query
    #  @return Boolean (@c True if branch does exist)
    all_branches = [ line.lstrip(" *") for line in check_output_with_retry(("git", "branch", "-l")).splitlines() ]
    if branch in all_branches:
        return True
    return False

