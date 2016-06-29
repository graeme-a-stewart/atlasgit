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
from atutils import check_output_with_retry, get_current_git_tags, author_string, recursive_delete
from atutils import switch_to_branch, get_flattened_git_tag


def branch_exists(gitrepo, branch):
    branches = get_current_git_tags(gitrepo)
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


def branch_builder(gitrepo, branch, tag_diff_files, svn_metadata_cache, parentbranch=None, skipreleasetag=False):
    '''Main branch builder function'''
    os.chdir(gitrepo)
    tag_list = get_current_git_tags(gitrepo)
    if not parentbranch:
        logger.info("Switching to branch {0}".format(branch))
        switch_to_branch(branch, orphan=True)
    else:
        parent, commit = parentbranch.split(":")
        check_output_with_retry(("git", "checkout", parent, commit), retries=1)
        check_output_with_retry(("git", "checkout", "-b", branch), retries=1)

    for tag_diff_file in tag_diff_files:
        with open(tag_diff_file) as tag_diff_fh:
            tag_diff = json.load(tag_diff_fh)

            last_base_release = None
            for release in tag_diff:
                if release["meta"]["type"] == "base":
                    last_base_release = release
                tag_list = get_current_git_tags(gitrepo)
                logger.info("Processing release {0}".format(release["release"]))
                release_tag = os.path.join("release", release["release"])
                if release_tag in tag_list and not skipreleasetag:
                    logger.info("Release tag {0} already made - skipping".format(release_tag))
                    continue
                
                # Reconstruct release by adding each tag
                import_list = {}
                for package, tag in release["diff"]["add"].iteritems():
                    package_name = os.path.basename(package)
                    if package_name not in svn_metadata_cache:
                        logger.debug("Package {0} not found - assuming restricted import".format(package_name))
                        continue
                    if tag == "trunk":
                        tag_index = "trunk"
                    else:
                        tag_index = os.path.join("tags", tag)
                    for revision in svn_metadata_cache[package_name]["svn"][tag_index]:
                        import_tag = get_flattened_git_tag(package, tag, revision)
                        if import_tag not in tag_list:
                            logger.debug("import tag {0} not found - assuming restricted import".format(import_tag))
                            continue
                        branch_import_tag = get_flattened_git_tag(package, tag, revision, branch)
                        logger.debug("Considering import of {0} to {1} (at revision {2})".format(branch_import_tag, branch, revision))
                        # To ensure that reverts of packages to older versions are processed
                        # correctly on release branches we never skip the import of a package
                        # into a cache, unless skipreleasetag=True, which is for rebuilding
                        # the master branch 
                        if branch_import_tag in tag_list and skipreleasetag:
                            logger.info("import of {0} ({1} r{2}) onto {3} done - skipping".format(package, tag, revision, branch))
                            continue
                        import_element = {"package": package, "import_tag": import_tag, "tag": tag, 
                                          "branch_import_tag": branch_import_tag}
                        logger.debug("Will import {0} to {1}".format(import_element, branch))
                        if revision in import_list:
                            import_list[revision].append(import_element)
                        else:
                            import_list[revision] = [import_element]

                sorted_import_revisions = import_list.keys()
                sorted_import_revisions.sort(cmp=lambda x,y: cmp(int(x), int(y)))
                
                pkg_processed = 0
                for revision in sorted_import_revisions:
                    for pkg_import in import_list[revision]:
                        check_output_with_retry(("git", "checkout", pkg_import["import_tag"], pkg_import["package"]))
                        # Done - now commit and tag
                        if logger.level <= logging.DEBUG:
                            cmd = ["git", "status"]
                            logger.debug(check_output_with_retry(cmd))
                        check_output_with_retry(("git", "add", "-A", pkg_import["package"]))
                        staged = check_output_with_retry(("git", "diff", "--name-only", "--staged"))
                        if len(staged) == 0: # Nothing staged, so skip
                            logger.info("Package {0} - no changes staged, skipping".format(pkg_import["package"]))
                            continue
                        msg = "{0} imported onto {1}".format(pkg_import["package"], branch)
                        if pkg_import["tag"] == "trunk":
                            msg += " (trunk r{0})".format(revision)
                        else:
                            msg += " ({0})".format(pkg_import["tag"])
                        cmd = ["git", "commit", "--allow-empty", "-m", msg]
                        cmd.append("--author='{0}'".format(author_string(release["meta"]["author"])))
                        cmd.append("--date={0}".format(int(release["meta"]["timestamp"])))
                        os.environ["GIT_COMMITTER_DATE"] = str(release["meta"]["timestamp"])
                        check_output_with_retry(cmd, retries=1)
                        if pkg_import["branch_import_tag"] not in tag_list:
                            check_output_with_retry(("git", "tag", pkg_import["branch_import_tag"]), retries=1)
                        logger.info("Committed {0} ({1}) onto {2} for {3}".format(pkg_import["package"], 
                                                                                  pkg_import["tag"], branch, release["release"]))
                        pkg_processed += 1

                for package in release["diff"]["remove"]:
                    if last_base_release and package in last_base_release["diff"]["add"]:
                        logger.info("Reverting {0} to base release version {1}".format(package, last_base_release["release"]))
                        import_tag = os.path.join("import", "tag", last_base_release["diff"]["add"][package])
                        check_output_with_retry(("git", "checkout", import_tag, package))
                    else:
                        logger.info("Removing {0} from {1}".format(package, branch))
                        recursive_delete(package)
                    check_output_with_retry(("git", "add", "-A"))
                    cmd = ["git", "commit", "--allow-empty", "-m", "{0} deleted from {1}".format(package, branch)]
                    pkg_processed += 1

                if release["meta"]["type"] != "snapshot" and not skipreleasetag:
                    if release["meta"]["nightly"]:
                        stub = "nightly"
                    else:
                        stub = "release"
                    check_output_with_retry(("git", "tag", os.path.join(stub, release["meta"]["name"])), retries=1)
                    logger.info("Tagged release {0} ({1} packages processed)".format(release["release"], pkg_processed))
                else:
                    logger.info("Processed release {0} (no tag; {1} packages processed)".format(release["release"], pkg_processed))


def main():
    parser = argparse.ArgumentParser(description='git branch constructor')
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="Location of git repository")
    parser.add_argument('branchname',
                        help="Git branch name to build")
    parser.add_argument('--tagdiff', metavar="FILE", nargs="+", default=[], required=True,
                        help="Tagdiff files to use to build git branch from")
    parser.add_argument('--parentbranch', metavar="BRANCH:COMMIT",
                        help="If branch does not yet exist, use this BRANCH to make it from at COMMIT")
    parser.add_argument('--svnmetadata', metavar="FILE",
                        help="File with SVN metadata per SVN tag in the git repository - using this option "
                        "allows the branch to be made from the correct point in the parent branch history. "
                        "By default GITREPO.svn.metadata will be used, if it exists.")
    parser.add_argument('--skipreleasetag', action="store_true",
                        help="Do not create a git tag for this release, nor skip processing if a release tag "
                        "exists - use this option to add packages to a 'secondary' branch from the main "
                        "release branch. Set true by default if the target branch is 'master'.")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    gitrepo = os.path.abspath(args.gitrepo)
    branch = args.branchname
    tag_diffs = [ os.path.abspath(fname) for fname in args.tagdiff ]
    
    if branch == "master":
        args.skipreleasetag = True
    
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
    
    # Main branch reconstruction function
    branch_builder(gitrepo, args.branchname, tag_diffs, svn_metadata_cache, args.parentbranch, args.skipreleasetag)
    

if __name__ == '__main__':
    main()
