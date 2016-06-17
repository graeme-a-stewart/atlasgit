#! /usr/bin/env python
#
## Prototype migration script from atlasoff to git,
#  moving sets of package tags identified with releases
#  to branches, and making tags for identified release
#  builds
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

## Note on data structures used:
#
# svn_metadata_cache is a dictionary keyed by package name, with value as a dictionary,
#  containing "path" and "svn" entries. The "svn" element is then 
#  keyed by svn subpath (trunk or tag/blah-XX-YY-ZZ), value dictionary keyed by revision (as trunk
#  can have many revisions, in principle) and a final value dictionary with date, revsion
#  and author key-value pairs, e.g.,
#  {
#   "PyJobTransformsCore": {
#     "path": "Tools",
#     "svn": 
#       "tags/PyJobTransformsCore-00-09-43": {
#         "735942": {
#           "date": "2016-04-08T16:35:02",
#           "revision": 735942,
#           "author": "alibrari"
#         }
#       },
#       "trunk": {
#         "735943": {
#           "date": "2016-04-08T16:35:05",
#           "revision": 735943,
#           "author": "alibrari"
#         }
#       }
#     },
#     ...
#   }

import argparse
import json
import logging
import os
import os.path
import pprint
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as eltree

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


def tag_cmp(tag_x, tag_y):
    ## @brief Special sort for svn paths, which always places trunk after any tags 
    if x=="trunk":
         return 1
    elif y=="trunk":
        return -1
    return cmp(tag_x, tag_y)

def scan_svn_tags_and_get_metadata(svnroot, svn_packages, svn_metadata_cache, all_package_tags=False):
    ## @brief Get SVN metadata for each of the package tags we're interested in
    #  @param svnroot URL of SVN repository
    #  @param svn_packages Dictionary of packages and tags to process
    #  @param svn_metadata_cache SVN metadata cache
    #  @param all_package_tags Boolean flag triggering import of all package tags in SVN
 
    # First we establish the list of tags which we need to deal with.
    for package, package_tags in svn_packages.iteritems():
        logger.info("Preparing package {0} (base tags: {1})".format(package, package_tags))
        if all_package_tags:
            oldest_tag = svn_packages[package][0]
            tags = get_all_package_tags(svnroot, package)
            try:
                package_tags.extend(tags[tags.index(oldest_tag)+1:])
            except ValueError:
                logger.error("Oldest release tag ({0}) for package {1} not found in SVN!".format(oldest_tag, package))
                sys.exit(1)
        # We need to now sort the package tags and remove any duplicates
        ordered_tags = list(set(package_tags))
        ordered_tags.sort(cmp = tag_cmp)
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
                if tag=="trunk":
                    # We always need to get the metadata for trunk tags as we need to
                    # know the current revision
                    svn_metadata = svn_get_path_metadata(svnroot, package, tag)
                    if svn_metadata["revision"] not in svn_metadata_cache[package_name]["svn"]:
                        svn_metadata_cache[package_name]["svn"][svn_metadata["revision"]] = svn_metadata
                elif tag not in svn_metadata_cache[package_name]["svn"]:
                    svn_metadata = svn_get_path_metadata(svnroot, package, tag)
                    svn_metadata_cache[package]["svn"][tag][svn_metadata["revision"]] = svn_metadata
            except RuntimeError:
                logger.warning("Failed to get SVN metadata for {0}".format(os.path.join(package, tag)))


def svn_get_path_metadata(svnroot, package, package_path, revision=None):
    ## @brief Get SVN metadata and return as a simple dictionary keyed on date, author and commit revision
    logger.info("Querying SVN metadeta for {0}".format(os.path.join(package, package_path)))
    cmd = ["svn", "info", os.path.join(svnroot, package, package_path), "--xml"]
    svn_info = check_output_with_retry(cmd)
    tree = eltree.fromstring(svn_info)
    return {
            "date": tree.find(".//date").text.rsplit(".",1)[0], # Strip off sub-second part
            "author": tree.find(".//author").text,
            "revision": int(tree.find(".//commit").attrib['revision']),
            }


def svn_cache_revision_dict_init(svn_metadata_cache):
    ## @brief Build a dictionary keyed by SVN revision and indicating which tags changed there
    #  @param svn_metadata_cache SVN metadata cache
    #  @return Cache revision dictionary with value list of packages and tags
    svn_cache_revision_dict = {}
    for package_name in svn_metadata_cache:
        for tag in svn_metadata_cache[package_name]["svn"]:
            for revision in svn_metadata_cache[package_name][tag]["svn"]:
                element = {"package": os.path.join(svn_metadata_cache[package_name]["path"], package) ,"tag": tag}
                if revision in svn_cache_revision_dict:
                    svn_cache_revision_dict[revision].append(element)
                else:
                    svn_cache_revision_dict[revision] = [element]
    return svn_cache_revision_dict


def init_git(gitrepo):
    ## @brief Initialise git repo, if needed
    #  @param gitrepo Git repository path
    if not os.path.exists(gitrepo):
        os.makedirs(gitrepo)
    os.chdir(gitrepo)
    if os.path.exists(os.path.join(gitrepo, ".git")):
        logger.info("Found existing git repo, {0}".format(gitrepo))
        check_output_with_retry(("git", "reset", "--hard"))
    else:
        logger.info("Initialising git repo: {0}".format(gitrepo))
        check_output_with_retry(("git", "init"))


def clean_changelog_diff(logfile):
    ## @brief Return a cleaned up ChangeLog diff - this is only as useful as what the developer wrote!
    o_lines = check_output_with_retry(("git", "diff", "-U0", logfile), retries=1).split("\n")
    o_lines = [ line.lstrip("+") for line in o_lines[6:] if line.startswith("+") and not re.search(r"(\s[MADR]\s+[\w\/\.]+)|(@@)", line) ]
    if len(o_lines) > 40:
        return ["ChangeLog diff too large"]
    return o_lines


def switch_to_branch(branch):
    ## @brief Switch to branch, creating it if necessary
    current_branch = check_output_with_retry(("git", "symbolic-ref", "HEAD", "--short"))
    if branch not in current_branch:
        all_branches = [ line.lstrip(" *").rstrip() for line in check_output_with_retry(("git", "branch", "-l")).split("\n") ]
        if branch in all_branches:
            check_output_with_retry(("git", "checkout", branch))
        else:
            check_output_with_retry(("git", "checkout", "-b", branch))


def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, svn_metadata, branch=None):
    ## @brief Make a temporary space, check out from svn, clean-up, copy and then git commit and tag
    logger.info("processing {0} tag {1} to branch {2}".format(package, tag, branch))
    
    if branch:
        current_branch = check_output_with_retry(("git", "symbolic-ref", "HEAD", "--short"))
        if (branch not in current_branch):
            all_branches = check_output_with_retry(("git", "branch", "-l"))
            if branch in all_branches:
                check_output_with_retry(("git", "checkout", branch))
            else:
                check_output_with_retry(("git", "checkout", "-b", branch))
    
    tempdir = tempfile.mkdtemp()
    full_svn_path = os.path.join(tempdir, package)
    cmd = ["svn", "checkout", "-r", str(svn_metadata["revision"]), os.path.join(svnroot, package, tag), os.path.join(tempdir, package)]
    check_output_with_retry(cmd)

    # Clean out directory of things we don't want to import
    svn_cleanup(full_svn_path)
    
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
    
    os.chdir(gitrepo)

    # get ChangeLog diff
    changelog_diff = None
    cl_file = os.path.join(package, 'ChangeLog')
    if os.path.isfile(cl_file):
        changelog_diff = clean_changelog_diff(cl_file)

    # Commit
    cmd = ["git", "add", "-A", package]
    check_output_with_retry(cmd)
    if logger.level <= logging.DEBUG:
        logger.debug(check_output_with_retry(("git", "status")))
    cmd = ["git", "commit", "--allow-empty", "-m", "{0} - r{1}".format(os.path.join(package, tag), svn_metadata['revision'])]
    if svn_metadata:
        cmd.extend(("--author='{0}'".format(author_string(svn_metadata["author"])), 
                    "--date={0}".format(svn_metadata["date"])))
        os.environ["GIT_COMMITTER_DATE"] = svn_metadata["date"]

    if changelog_diff:
        cmd.extend(("-m","Diff in ChangeLog:\n" + '\n'.join(changelog_diff)))
    check_output_with_retry(cmd)
    cmd = ["git", "tag", "-a", get_flattened_git_tag(package, tag, svn_metadata["revision"]), "-m", ""]
    check_output_with_retry(cmd)
    
    # Clean up
    shutil.rmtree(tempdir)
    
def svn_cleanup(svn_path):
    ## @brief Cleanout files we do not want to import into git
    shutil.rmtree(os.path.join(svn_path, ".svn"))
    
    # File size veto
    for root, dirs, files in os.walk(svn_path):
        for name in files:
            filename = os.path.join(root, name)
            try:
                if os.stat(filename).st_size > 100*1024:
                    if "." in name and name.rsplit(".", 1)[1] in ("cxx", "py", "h", "java", "cc", "c", "icc", "cpp", "hpp", "hh"):
                        logger.info("Source file {0} is too large, but importing anyway".format(filename))
                    elif name in ("ChangeLog"):
                        logger.info("Repo file {0} is too large, but importing anyway".format(filename))
                    else:
                        logger.warning("File {0} is too large - not importing".format(filename))
                        os.remove(filename)
                if name.startswith("."):
                    logger.warning("File {0} starts with a '.' - not importing".format(filename))
                    os.remove(filename)
            except OSError, e:
                logger.warning("Got OSError treating {0}: {1}".format(filename, e))


def get_current_git_tags(gitrepo):
    ## @brief Return a list of current git tags
    os.chdir(gitrepo)
    cmd = ["git", "tag", "-l"]
    return check_output_with_retry(cmd).split("\n")


def get_tags_from_diffs(tag_diff_files, svn_path_accept):
    ## @brief Parse packages and package tags from release diff files
    svn_package_tags = {}
    for tag_diff_file in tag_diff_files:
        with open(tag_diff_file) as tag_diff_fh:
            tag_diff_dict = json.load(tag_diff_fh)
            for entry in tag_diff_dict:
                logger.info("Parsing release {0} from {1}".format(entry["release"], tag_diff_file))
                for package, tag in entry["diff"]["add"].iteritems():
                    if len(svn_path_accept) > 0:
                        accept = False
                        for path in svn_path_accept:
                            if package.startswith(path):
                                accept = True
                                break
                        if not accept:
                            continue
                    # Add in the standard "tags" path 
                    tag = os.path.join("tags", tag)
                    if package in svn_package_tags:
                        svn_package_tags[package].add(tag)
                    else:
                        svn_package_tags[package] = set((tag,))
    # Now convert back to list and sort tags...
    for package in svn_package_tags:
        svn_package_tags[package] = list(svn_package_tags[package])
        svn_package_tags[package].sort()
    return svn_package_tags

        
def get_flattened_git_tag(package, tag, revision):
    ## @brief Construct a git tag to signal the import of a particular SVN tag or revision
    if tag == "trunk":
        return os.path.join("import", "trunk","{0}-r{1}".format(os.path.basename(package), revision))
    return os.path.join("import", "tag", os.path.basename(tag))

def author_string(author):
    ## @brief Write a formatted commit author string
    #  @note if we have a valid email keep it as is, but otherwise assume it's a ME@cern.ch address
    if re.search(r"<[a-zA-Z0-9-]+@[a-zA-Z0-9-]+>", author):
        return author
    elif re.match(r"[a-zA-Z0-9]+$", author):
        return "{0} <{0}@cern.ch>".format(author)
    return author


def main():
    parser = argparse.ArgumentParser(description='SVN to git migrator, ATLAS style')
    parser.add_argument('svnroot', metavar='SVNDIR',
                        help="Location of svn repository root")
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="Location of git repository")
    parser.add_argument('--targetbranch', default="import",
                        help="Target git branch for import (default is 'import')")
    parser.add_argument('--svnpath', metavar='PATH', nargs='+', default=[],
                        help="Restrict actions to this list of paths in the SVN tree (use to "
                        "make small scale tests of the import workflow).")
    parser.add_argument('--tagsfromtagdiff', nargs="+", default=[],
                        help="Read list of tags to import from ATLAS release tagdiff files. If multiple tagdiffs are given "
                        "all will be scanned to find tags to import.")
    parser.add_argument('--intermediatetags', action="store_true", default=False,
                        help="Import all tags from oldest release tag found, instead of just release tags")
    parser.add_argument('--skiptrunk', action="store_true", default=False,
                        help="Skip package trunk during the import (by default, the trunk will alwaye be processed).")
    parser.add_argument('--svncachefile', metavar='FILE',
                        help="File containing cache of SVN information - default 'gitrepo.svn.metadata'")
    parser.add_argument('--importtimingfile', metavar="FILE",
                        help="File to dump SVN->git import timing information - default 'gitrepo-timing.json'")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    # Massage default values
    if not args.svncachefile:
        args.svncachefile = os.path.basename(args.gitrepo) + ".svn.metadata"
    if not args.importtimingfile:
        args.importtimingfile = os.path.basename(args.gitrepo) + "-timing.json"

    # Set svnroot and git repo, get some starting values
    svnroot = args.svnroot
    gitrepo = os.path.abspath(args.gitrepo)
    start_cwd = os.getcwd()
    start_timestamp_string = time.strftime("%Y%m%dT%H%M.%S")
    logger.debug("Set SVN root to {0} and git repo to {1}".format(svnroot, gitrepo))


    ### Main actions start here
    # Setup the git repository
    init_git(gitrepo)
    # Pull current list of tags here, to fast skip any work already done
    switch_to_branch(args.targetbranch)
    current_git_tags = get_current_git_tags(gitrepo)
    
    ## SVN interactions and reloading state    
    # Decide which svn packages we will import
    # Note that if we're pulling the packages from a tag diff file, we also get tags
    # at this point, otherwise the tag list is empty.
    if len(args.tagsfromtagdiff) > 0:
        svn_packages = get_tags_from_diffs(args.tagsfromtagdiff, args.svnpath)
        # Add "trunk" packages, if required
        for package, tags in svn_packages.iteritems():
            if args.skiptrunk is False and "trunk" not in tags:
                tags.append("trunk")
    else:
        raise RuntimeError("Update to trunk tags TODO")


    # Initialise SVN metadata cache with any stored values
    svn_metadata_cache = initialise_svn_metadata(args.svncachefile)

    # Prepare package import
    scan_svn_tags_and_get_metadata(svnroot, svn_packages, svn_metadata_cache, args.intermediatetags)

    # Now presistify metadata cache
    backup_svn_metadata(svn_metadata_cache, start_cwd, args.svncachefile, start_timestamp_string)
    
    # Setup dictionary for keying by SVN revision number
    svn_cache_revision_dict = svn_cache_revision_dict_init(svn_metadata_cache)

    ## git processing actions
    # Process each SVN tag in order
    ordered_revisions = svn_cache_revision_dict.keys()
    ordered_revisions.sort()
    logger.info("Will process {0} SVN revisions in total".format(len(ordered_revisions)))
    counter=0
    timing = []
    
    for rev in ordered_revisions:
        counter+=1
        start=time.time()
        logger.info("SVN Revsion {0} ({1} of {2})".format(rev, counter, len(ordered_revisions)))
        for pkg_tag in svn_cache_revision_dict[rev]:
            if get_flattened_git_tag(pkg_tag["package"], pkg_tag["tag"], rev) in current_git_tags:
                logger.info("Tag {0} exists already - skipping".format(os.path.join(pkg_tag["package"], pkg_tag["tag"])))
                continue
            svn_co_tag_and_commit(svnroot, gitrepo, pkg_tag["package"], pkg_tag["tag"], 
                                  svn_metadata_cache[pkg_tag["package"]]["svn"][pkg_tag["tag"]][rev])
        elapsed = time.time()-start
        logger.info("{0} processed in {1}s".format(counter, elapsed))
        timing.append(elapsed)
        
    if args.importtimingfile:
        os.chdir(start_cwd)
        with open(args.importtimingfile, "w") as time_file:
            json.dump(timing, time_file)

if __name__ == '__main__':
    main()

