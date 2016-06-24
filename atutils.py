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

def check_output_with_retry(cmd, retries=3, wait=10):
    ## @brief Multiple attempt wrapper for subprocess.check_call (especially remote SVN commands can bork)
    #  @param cmd list or tuple of command line parameters
    #  @param retries Number of attempts to execute successfully
    #  @param wait Sleep time after an unsuccessful execution attempt
    #  @return String containing command output 
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
            logger.warning("Attempt {0} to execute {1} failed".format(tries, cmd))
            if tries >= retries:
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


def author_string(author):
    ## @brief Write a formatted commit author string
    #  @note if we have a valid email keep it as is, but otherwise assume it's a ME@cern.ch address
    if re.search(r"<[a-zA-Z0-9-]+@[a-zA-Z0-9-]+>", author):
        return author
    elif re.match(r"[a-zA-Z0-9]+$", author):
        return "{0} <{0}@cern.ch>".format(author)
    return author


def initialise_svn_metadata(svncachefile):
    ## @brief Load existing cache file, if it exists, or return empty cache
    #  @param svncachefile Name of svn cache file (serialised in JSON)
    if os.path.exists(svncachefile):
        logger.info("Reloading SVN cache from {0}".format(svncachefile))
        with file(svncachefile) as md_load:
            svn_metadata_cache = json.load(md_load)
    else:
        svn_metadata_cache = {}
    return svn_metadata_cache


def backup_svn_metadata(svn_metadata_cache, start_cwd, svncachefile, start_timestamp_string):
    ## @brief Persistify SVN metadata cache in JSON format
    #  @param svn_metadata_cache SVN metadata cache
    #  @param start_cwd Directory to change to before dumping
    #  @param start_timestamp_string Timestamp backup for previous version of the cache
    os.chdir(start_cwd)
    if os.path.exists(svncachefile):
        os.rename(svncachefile, svncachefile+".bak."+start_timestamp_string)
    with file(svncachefile, "w") as md_dump:
        json.dump(svn_metadata_cache, md_dump, indent=2)


def switch_to_branch(branch, orphan=False):
    ## @brief Switch to branch, creating it if necessary
    #  @param branch Branch to switch to or create
    #  @param orphan If @c Ture then create branch as an orphan and delete all current files
    current_branch = check_output_with_retry(("git", "symbolic-ref", "HEAD", "--short"))
    if branch != current_branch:
        all_branches = [ line.lstrip(" *").rstrip() for line in check_output_with_retry(("git", "branch", "-l")).split("\n") ]
        if branch in all_branches:
            check_output_with_retry(("git", "checkout", branch))
        elif not orphan:
            check_output_with_retry(("git", "checkout", "-B", branch))
        else:
            check_output_with_retry(("git", "checkout", "--orphan", branch))
            # Clean up the new branch, deleting all files and clearing the staging area
            recursive_delete(".")
            check_output_with_retry(("git", "rm", "-r", "--cached", "--ignore-unmatch", "."))
            