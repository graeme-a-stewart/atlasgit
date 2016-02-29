#! /usr/bin/env python
#
# Build a git release branch from a tagdiff history of
# numbered ATLAS release builds
#

import argparse
import json
import logging
import os
import os.path
import shutil
import sys

from asvn2git import check_output_with_retry 
from glogger import logger

def git_change_to_branch(gitrepo, branch, branch_point=None):
    os.chdir(gitrepo)
    cmd = ["git", "checkout", "-b", branch]
    if branch_point:
        cmd.append(branch_point)
    logger.info("Creating branch with {0}".format(cmd))
    check_output_with_retry(cmd)


def branch_builder(gitrepo, branch, tag_diff_files, svn_metadata_cache=None):
    '''Main branch builder function'''
    branch_made = False
    for tag_diff_file in tag_diff_files:
        with open(tag_diff_file) as tag_diff_fh:
            tag_diff = json.load(tag_diff_fh)
            
        if not branch_made:
            # Need to find and set the point as which we want to branch from master
            tag_to_branch_at = None
            youngest_svn_revision = -1
            if svn_metadata_cache:
                for package, tag in tag_diff[0]["diff"]["add"].iteritems():
                    if svn_metadata_cache[package][os.path.join("tags", tag)]["revision"] > youngest_svn_revision:
                        youngest_svn_revision = svn_metadata_cache[package][os.path.join("tags", tag)]["revision"]
                        tag_to_branch_at = os.path.join("import", "tag", tag)
            logger.info("Tag to branch from master at is {0} (SVN revision {1})".format(tag_to_branch_at, youngest_svn_revision))
            git_change_to_branch(gitrepo, branch, tag_to_branch_at)
            branch_made = True
        
        # "Flush" state of the release - the first base release will rebuild the
        # initial contents
        for entry in os.listdir(gitrepo):
            if entry.startswith("."):
                continue
            entry = os.path.join(gitrepo, entry)
            if os.path.isfile(entry):
                os.unlink(entry)
            elif os.path.isdir(entry):
                shutil.rmtree(entry)
        
        # Now cycle over package tags and update the content of the branch
        for release in tag_diff:
            logger.info("Processing release {0}".format(release["release"]))
            for package, tag in release["diff"]["add"].iteritems():
                check_output_with_retry(("git", "checkout", os.path.join("import", "tag", tag), package))
                
            check_output_with_retry(("git", "add", "-A"))
            check_output_with_retry(("git", "commit", "--allow-empty", "-m", "Release {0}".format(release["release"])))
            check_output_with_retry(("git", "tag", os.path.join("release", release["release"])))
            logger.info("Tagged release {0}".format(release["release"]))


def main():
    parser = argparse.ArgumentParser(description='git branch constructor')
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="Location of git repository")
    parser.add_argument('branchname',
                        help="git branch name to build")
    parser.add_argument('tagdiff', metavar="FILE", nargs="+", 
                        help="tagdiff files to use to build git branch from")
    parser.add_argument('--svnmetadata', metavar="FILE",
                        help="File with SVN metadata per SVN tag in the git repository - using this option "
                        "allows the branch to be made from the correct point in the master branch history")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    gitrepo = os.path.abspath(args.gitrepo)
    branch = args.branchname
    
    # Load SVN metadata cache - this is the fastest way to query the SVN ordering in which tags
    # were made
    if args.svnmetadata:
        with open(args.svnmetadata) as cache_fh:
            svn_metadata_cache = json.load(cache_fh)        
    else:
        svn_metadata_cache = None
    
    # Main branch reconstruction function
    branch_builder(gitrepo, args.branchname, args.tagdiff, svn_metadata_cache)
    

if __name__ == '__main__':
    main()