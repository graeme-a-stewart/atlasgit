#! /usr/bin/env python
#
# Build a git release branch from a tagdiff history of
# numbered ATLAS release builds
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
import logging
import os
import os.path
import shutil
import sys

from glogger import logger
from atutils import check_output_with_retry, get_current_git_tags, author_string

def git_change_to_branch(gitrepo, branch, branch_point=None):
    cmd = ["git", "checkout", "-b", branch]
    if branch_point:
        cmd.append(branch_point)
    logger.info("Creating branch with {0}".format(cmd))
    check_output_with_retry(cmd, retries=1)


def branch_exists(gitrepo, branch):
    branches = check_output_with_retry(("git", "branch"), retries=1)
    if branch in branches:
        return True
    return False


def find_youngest_tag(tag_diff, svn_metadata_cache):
    '''Use the svn metadata cache to find the youngest tag in the release''' 
    yougest_tag = None
    youngest_svn_revision = -1
    if svn_metadata_cache:
        for package, tag in tag_diff[0]["diff"]["add"].iteritems():
            if (package in svn_metadata_cache and 
                svn_metadata_cache[package][os.path.join("tags", tag)]["revision"] > youngest_svn_revision):
                youngest_svn_revision = svn_metadata_cache[package][os.path.join("tags", tag)]["revision"]
                yougest_tag = os.path.join("import", "tag", tag)
    logger.info("Tag to branch from master at is {0} (SVN revision {1})".format(yougest_tag, youngest_svn_revision))
    return yougest_tag


def recursive_delete(gitrepo):
    '''Delete all files in the repository working copy'''
    for entry in os.listdir(gitrepo):
        if entry.startswith("."):
            continue
        entry = os.path.join(gitrepo, entry)
        if os.path.isfile(entry):
            os.unlink(entry)
        elif os.path.isdir(entry):
            shutil.rmtree(entry)


def branch_builder(gitrepo, branch, tag_diff_files, svn_metadata_cache, svn_name_path):
    '''Main branch builder function'''
    os.chdir(gitrepo)
    tag_list = get_current_git_tags(gitrepo)
    if branch_exists(gitrepo, branch):
        logger.info("Branch {0} already exists - switching and reseting...".format(branch))
        check_output_with_retry(("git", "checkout", branch), retries=1)
        check_output_with_retry(("git", "reset", "--hard"), retries=1)
        branch_made = True
    elif branch == "master":
        logger.info("Creating new empty master branch")
        check_output_with_retry(("git", "checkout", "--orphan", branch), retries=1)
        recursive_delete(gitrepo)
        branch_made = True
    else:
        branch_made = False
        
    if branch == "master" and len(tag_diff_files) == 0:
        # Special import method for master branch
        trunk_import_revisions = [ os.path.basename(tag) for tag in tag_list 
                           if tag.startswith("import/trunk") and 
                           (os.path.join("copy", "trunk", os.path.basename(tag)) not in tag_list) ]
        trunk_import_revisions.sort(cmp = lambda x,y: cmp(int(x[x.find("-r")+2:]), int(y[y.find("-r")+2:])))
        logger.debug(trunk_import_revisions)

        # Now loop, commit and tag...
        for trunk_rev in trunk_import_revisions:
            package_name = trunk_rev[:trunk_rev.find("-r")]
            package_revision = trunk_rev[trunk_rev.find("-r")+2:]
            package = svn_name_path[package_name]
            check_output_with_retry(("git", "checkout", os.path.join("import", "trunk", trunk_rev), package), retries=1)
            check_output_with_retry(("git", "add", "-A"))
            cmd = ["git", "commit", "--allow-empty", "-m", "{0} (r{1}) commited to {2}".format(package_name, package_revision, branch)]
            cmd.append("--author='{0}'".format(author_string(svn_metadata_cache[package]["trunk"][package_revision]["author"])))
            cmd.append("--date={0}".format(svn_metadata_cache[package]["trunk"][package_revision]["date"]))
            os.environ["GIT_COMMITTER_DATE"] = svn_metadata_cache[package]["trunk"][package_revision]["date"]
            check_output_with_retry(cmd, retries=1)
            check_output_with_retry(("git", "tag", os.path.join("copy", branch, trunk_rev)), retries=1)
            logger.info("Tagged commit of {0}".format(trunk_rev))

    else:
        for tag_diff_file in tag_diff_files:
            with open(tag_diff_file) as tag_diff_fh:
                tag_diff = json.load(tag_diff_fh)
                
            if not branch_made:
                yougest_git_tag = find_youngest_tag(tag_diff, svn_metadata_cache)
                git_change_to_branch(gitrepo, branch, yougest_git_tag)
                branch_made = True
            
            # Now cycle over package tags and update the content of the branch
            for release in tag_diff:
                logger.info("Processing release {0}".format(release["release"]))
                release_tag = os.path.join("release", release["release"])
                if release_tag in tag_list:
                    logger.info("Release tag {0} already made - skipping".format(release_tag))
                    continue
                if release["meta"]["type"] == "base":
                    recursive_delete(gitrepo)
                
                # Reconstruct release by adding each tag
                for package, tag in release["diff"]["add"].iteritems():
                    try:
                        import_tag = os.path.join("import", "tag", tag)
                        if import_tag not in tag_list:
                            logger.warning("import tag {0} not found - assuming restricted import".format(import_tag))
                            continue
                        check_output_with_retry(("git", "checkout", os.path.join("import", "tag", tag), package), retries=1)
                    except RuntimeError:
                        logger.error("git checkout of {0} tag {1} failed (not imported onto master branch?)".format(package, tag))
                
                # Done - now commit and tag
                if logger.level <= logging.DEBUG:
                    cmd = ["git", "status"]
                    logger.debug(check_output_with_retry(cmd))
                check_output_with_retry(("git", "add", "-A"))
                cmd = ["git", "commit", "--allow-empty", "-m", "Release {0}".format(release["release"])]
                cmd.append("--author='{0}'".format(author_string(release["meta"]["author"])))
                cmd.append("--date={0}".format(int(release["meta"]["timestamp"])))
                os.environ["GIT_COMMITTER_DATE"] = str(release["meta"]["timestamp"])
                check_output_with_retry(cmd, retries=1)
                check_output_with_retry(("git", "tag", os.path.join("release", release["release"])), retries=1)
                logger.info("Tagged release {0}".format(release["release"]))


def main():
    parser = argparse.ArgumentParser(description='git branch constructor')
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="Location of git repository")
    parser.add_argument('branchname',
                        help="git branch name to build (default is to add trunk tags to master branch")
    parser.add_argument('--tagdiff', metavar="FILE", nargs="+", default=[],
                        help="tagdiff files to use to build git branch from, this is mandatory unless you "
                        "are building the master branch")
    parser.add_argument('--parentbranch', 
                        help="If branch does not yet exist, select this branch to make it from")
    parser.add_argument('--svnmetadata', metavar="FILE",
                        help="File with SVN metadata per SVN tag in the git repository - using this option "
                        "allows the branch to be made from the correct point in the parent branch history. "
                        "By default GITREPO.svn.metadata will be used, if it exists.")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    gitrepo = os.path.abspath(args.gitrepo)
    branch = args.branchname
    
    if args.branchname != "master" and len(args.tagdiff) == 0: 
        print >>sys.stderr, "--tagdiff files are mandatory when dealing with a release branch"
        sys.exit(1)
    
    # Load SVN metadata cache - this is the fastest way to query the SVN ordering in which tags
    # were made
    if not args.svnmetadata and os.access(args.gitrepo + ".svn.metadata", os.R_OK):
        args.svnmetadata = args.gitrepo + ".svn.metadata"
        logger.info("Found SVN metadata cache here: {0}".format(args.svnmetadata))
    else:
        logger.error("No SVN metadata cache found - cannot proceed")
        sys.exit(1)
    with open(args.svnmetadata) as cache_fh:
        svn_metadata_cache = json.load(cache_fh)
    logger.info("Loaded SVN metadata from {0}".format(args.svnmetadata))
    
    # Now make a map of the package base name back to the repository path
    svn_name_path = {}
    for full_package in svn_metadata_cache.keys():
        svn_name_path[os.path.basename(full_package)] = full_package

    # Main branch reconstruction function
    branch_builder(gitrepo, args.branchname, args.tagdiff, svn_metadata_cache, svn_name_path)
    

if __name__ == '__main__':
    main()
