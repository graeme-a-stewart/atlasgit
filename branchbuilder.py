#! /usr/bin/env python
#
# Author: Graeme A Stewart <graeme.andrew.stewart@cern.ch>
#
# Copyright (C) 2017 CERN for the benefit of the ATLAS collaboration
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
## Build a git release branch from a tagdiff history of
# numbered ATLAS release builds

import argparse
import json
import logging
import os
import os.path
import pprint
import shutil
import sys

from glogger import logger
from atutils import check_output_with_retry, get_current_git_tags, author_string, recursive_delete, branch_exists
from atutils import switch_to_branch, get_flattened_git_tag, changelog_diff, package_compare, is_svn_branch_tag
from atutils import git_release_tag

def backskip_filter(tagfiles):
    ## @brief Reverse order parse a set of tagfiles and reject those
    #  where procesing would require a backskip in time
    #  @param tagfiles List of tag files
    #  #return Filtered list of tagfiles with backskips removed
    last_timestamp = 0
    last_release = ""
    tagfiles_copy = tagfiles[:]
    tagfiles_copy.reverse()
    for tagfile in tagfiles_copy:
        with open(tagfile) as tagfile_fh:
            release_data = json.load(tagfile_fh)
        if last_timestamp and release_data["release"]["timestamp"] > last_timestamp:
            logger.info("Vetoing release {0} (from {1}) because of "
                        "backskip for {2}".format(release_data["release"]["name"], tagfile, last_release))
            tagfiles.remove(tagfile)
            continue
        last_timestamp = release_data["release"]["timestamp"]
        last_release = release_data["release"]["name"]
        logger.info("Accepted release {0} at {1}".format(last_release, last_timestamp))
    return tagfiles


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


def prepare_branch_point(branch, parentbranch=None):
    ## @brief Using information about the target branch and any parent
    #  switch to the correct point in history to start/continue
    #  @param branch Target branch name
    #  @param parentbranch If creating a new branch, this is the @c BRANCH:COMMIT_ID of 
    #  where to make the new branch from; syntax @c BRANCH:@FILE and @c BRANCH:@TIMESTAMP
    #  is also supported, where the timestamp will be used to find the branch directly
    #  (and can be taken from @c JSON release data in @c FILE) 
    if not parentbranch or branch_exists(branch):
        logger.info("Switching to branch {0}".format(branch))
        switch_to_branch(branch, orphan=True)
    else:
        parent, commit = parentbranch.split(":")
        check_output_with_retry(("git", "checkout", parent), retries=1) # needed?
        if commit.startswith("@"):
            timestamp = commit[1:]
            # If this maps to a file, try to open it as a release JSON, otherwise treat it as
            # a plain timestamp
            if os.access(timestamp, os.F_OK):
                logger.info("Taking branching timestamp from file {0}".format(timestamp))
                with open(timestamp) as fh:
                    branch_point_release = json.load(fh)
                timestamp = branch_point_release["release"]["timestamp"]
            logger.info("Using timestamp {0} for branch point".format(timestamp))
            commit = check_output_with_retry(["git", "log", "--until", str(timestamp), "-n1", "--pretty=format:%H"],
                                             retries=1).strip()
            logger.info("Mapped timestamp {0} to commit {1}".format(timestamp, commit))
        check_output_with_retry(("git", "checkout", commit), retries=1)
        check_output_with_retry(("git", "checkout", "-b", branch), retries=1)


def get_current_release_tag_dict(tag_list, branch):
    ## @brief Return a dictionary, keyed by package name that can be used to keep
    #  track of unprocessed tags (which will need subsequent removal/revert from the release)
    #  @param tag_list List of (all) git tags
    #  @param branch Name of release branch to get tags for
    #  @return Dictonary of the form {package_name : {'git_tag': current_git_tag, 'svn_tag': svn_tag }, ...}
    release_tag_dict = {}
    release_prefix = os.path.join(branch, "import")
    for tag in tag_list:
        if not tag.startswith(release_prefix):
            continue
        package_tag = os.path.basename(tag)
        package_name = package_tag.split("-", 1)[0]
        release_tag_dict[package_name] = {"svn_tag": package_tag, "git_tag": tag}
    if logger.level <= logging.DEBUG:
        pprint.pprint(release_tag_dict)
    return release_tag_dict


def find_packages_for_update(release_data, tag_list, branch, svn_metadata_cache, release_tag_unprocessed, only_forward=False):
    ## @brief Find packages that need updates, comparing release tag content with
    #  git import tags already made
    #  @param release_data Release tag content dictionary
    #  @param tag_list List of current git tags
    #  @param branch Git branch being constructed
    #  @param svn_metadata_cache Usual cache data for SVN stuff
    #  @param release_tag_unprocessed Dictionary with current "tag" metadata, useful to mark up import
    #  @param only_forward If @c True then never revert a package to a previous version or import a branch tag
    #  @return Tuple of tag import dictionary, and a list of all "processed" packages
    
    ## Loop over all packages in a release and see if the package
    # - is missing from the svn metadata cache (so skip)
    # - is already imported at current HEAD (so skip)
    # - is new or updated (so mark for import)
    # Final construct is the import_list dictionary
    import_list = {}
    packages_considered = []
    for package, package_data in release_data["tags"].iteritems():
        package_name = os.path.basename(package)
        packages_considered.append(package_name)
        package_tag = package_data["svn_tag"]
        if package_name not in svn_metadata_cache:
            logger.debug("Package {0} not found - assuming restricted import".format(package_name))
            continue
        if package_tag == "trunk":
            svn_meta_tag_key = "trunk"
        else:
            svn_meta_tag_key = os.path.join("tags", package_tag)

        for revision in svn_metadata_cache[package_name]["svn"][svn_meta_tag_key]:
            git_import_tag = get_flattened_git_tag(package, package_tag, revision)
            if git_import_tag not in tag_list:
                logger.debug("Import tag {0} not found - assuming restricted import".format(git_import_tag))
                continue
            branch_import_tag = get_flattened_git_tag(package, package_tag, revision, branch)
            logger.debug("Considering import of {0} ({1}@r{2}) to {3} "
                         "for release {4}".format(branch_import_tag, package_tag, revision, branch, release_data["release"]["name"]))
            if branch_import_tag in tag_list:
                logger.info("Import of {0} ({1} r{2}) onto {3} done - skipping".format(package, package_tag, revision, branch))
                continue
            if only_forward:
                if package_name in release_tag_unprocessed and package_compare(release_tag_unprocessed[package_name]["svn_tag"], package_tag) != -1:
                    logger.info("Import of {0} onto {1} is blocked - onlyforward option will not downgrade tags".format(package_tag, branch))
                    continue
            ## @note The structure of the dictionary used to direct the import of a package is:
            #  "package": full package path
            #  "package_name": package basename (for convenience)
            #  "git_import_tag": the git import tag that identifies the import of the version of this package
            #  "svn_tag": the SVN tag corresponding to this package version
            #  "svn_revision": the SVN revision for this package version
            #  "branch_import_tag": the git import tag that will be created to stamp this import as done
            #  "svn_meta_tag_key": the key used in the SVN metadata dictionary to get SVN metadata
            #  "current_branch_import_tag": the git tag indicating the current version of this package 
            import_element = {"package": package, 
                              "package_name": os.path.basename(package),
                              "git_import_tag": git_import_tag, 
                              "svn_tag": package_tag, 
                              "svn_revision": revision,
                              "branch_import_tag": branch_import_tag, "svn_meta_tag_key": svn_meta_tag_key, 
                              "current_branch_import_tag": release_tag_unprocessed[package_name]["git_tag"] if package_name in release_tag_unprocessed else None}
            logger.debug("Will import {0} to {1}".format(import_element, branch))
            if revision in import_list:
                import_list[revision].append(import_element)
            else:
                import_list[revision] = [import_element]

    return import_list, packages_considered


def do_package_import(pkg_import, svn_metadata_cache, author_metadata_cache, release_name="unknown", branch="unknown", 
                      dryrun=False, commit_date="now"):
    ## @brief Import a package's SVN tag onto the current git branch
    #  updating the corresponding git tags
    #  @param pkg_import package import dictionary (see find_packages_for_update for the
    #  structure)
    #  @param svn_metadata_cache The standard metadata cache from SVN
    #  @param author_metadata_cache Cached author data
    #  @param release_name Name of current release being built (used only for generating log messages)
    #  @param branch Current branch name (used only for generating log messages)
    #  @param dryrun Boolean, if @c true then don't actually act
    #  @param commit_date Choices for setting committer date 
    logger.info("Migrating {0} from {1} to {2} for {3}...".format(pkg_import["package"], 
                                                          pkg_import["current_branch_import_tag"], 
                                                          pkg_import["svn_tag"], release_name))
    # Need to wipe out all contents in case files were removed from package
    if not dryrun:
        recursive_delete(pkg_import["package"])
    check_output_with_retry(("git", "checkout", pkg_import["git_import_tag"], pkg_import["package"]), dryrun=dryrun)
    # Splat Changelog file - we do not want these on the production branches
    try:
        os.remove(os.path.join(pkg_import["package"], "ChangeLog"))
    except OSError:
        pass
    # Done - now commit and tag
    if logger.level <= logging.DEBUG:
        cmd = ["git", "status"]
        logger.debug(check_output_with_retry(cmd))
    check_output_with_retry(("git", "add", "-A", pkg_import["package"]), dryrun=dryrun)
    staged = check_output_with_retry(("git", "diff", "--name-only", "--staged"), dryrun=dryrun)
    if len(staged) == 0 and (not dryrun): 
        # Nothing staged, so skip doing any commit, but do make the import tag for this branch
        # so that we don't repeat this step again
        logger.warning("Package {0} - no changes staged for {1}, " 
                       "git tagging and skipping commit".format(pkg_import["package"], release_name))
        check_output_with_retry(("git", "tag", pkg_import["branch_import_tag"]), retries=1, dryrun=dryrun)
        return

    rev_meta = svn_metadata_cache[pkg_import["package_name"]]["svn"][pkg_import["svn_meta_tag_key"]][pkg_import["svn_revision"]]
    msg = rev_meta["msg"]
    if pkg_import["svn_tag"] == "trunk":
        msg += " (trunk r{0})".format(rev_meta["revision"])
    else:
        msg += " ({0})".format(pkg_import["svn_tag"])
    cl_diff = changelog_diff(pkg_import["package"],
                             from_tag="/".join(pkg_import["current_branch_import_tag"].split("/")[1:]) if pkg_import["current_branch_import_tag"] else None,
                             to_tag=pkg_import["git_import_tag"])
    if cl_diff:
        msg += "\n\n" + "\n".join(cl_diff)
    cmd = ["git", "commit", "-m", msg]
    author = author_string(rev_meta["author"], author_metadata_cache)
    cmd.append("--author='{0}'".format(author))
    cmd.append("--date={0}".format(rev_meta["date"]))
    
    if commit_date == "author":
        os.environ["GIT_COMMITTER_DATE"] = rev_meta["date"]
    check_output_with_retry(cmd, retries=1, dryrun=dryrun)
    if commit_date == "author":
        del os.environ["GIT_COMMITTER_DATE"]
    
    check_output_with_retry(("git", "tag", pkg_import["branch_import_tag"]), retries=1, dryrun=dryrun)
    if pkg_import["current_branch_import_tag"]:
        check_output_with_retry(("git", "tag", "-d", pkg_import["current_branch_import_tag"]), retries=1, dryrun=dryrun)
    logger.info("Committed {0} ({1}) onto {2} for {3}".format(pkg_import["package"], 
                                                              pkg_import["svn_tag"], branch, release_name))



def branch_builder(gitrepo, branch, tag_files, svn_metadata_cache, author_metadata_cache,
                   parentbranch=None, baserelease=None,
                   skipreleasetag=False, dryrun=False, only_forward=False, commit_date="now"):
    ## @brief Main branch builder function
    #  @param gitrepo The git repository location
    #  @param branch The git branch to work on
    #  @param tag_files The plain tag content files to process
    #  @param svn_metadata_cache The standard metadata cache from SVN
    #  @param author_metadata_cache Cached author data
    #  @param parentbranch If creating a new branch, this is the BRANCH:COMMIT_ID of where to make the new branch from
    #  @param skipreleasetag If @c True then skip creating git tags for each processed release
    #  @param dryrun If @c True, do nothing except print commands that would have been executed
    #  @param only_forward If @c True then never revert a package to a previous version or import a branch tag 
    #  @param commit_date Choice for commit date when building branches
    
    # Prepare - chdir and then make sure we are on the correct branch
    os.chdir(gitrepo)
    prepare_branch_point(branch, parentbranch)            

    # Main loop starts here, with one pass for each tag file we are processing
    for tag_file in tag_files:
        with open(tag_file) as tag_file_fh:
            release_data = json.load(tag_file_fh)

        tag_list = get_current_git_tags(gitrepo)
        current_release_tags = get_current_release_tag_dict(tag_list, branch) # Markers for which packages have been processed
        logger.info("Processing release {0} ({1} current tags)".format(release_data["release"]["name"], len(current_release_tags)))
        release_tag = git_release_tag(release_data["release"], branch)
        if release_tag in tag_list and not skipreleasetag:
            logger.info("Release tag {0} already made - skipping".format(release_tag))
            continue

        if commit_date == "release":
            logger.info("Setting committer date to {0:.0f}".format(release_data["release"]["timestamp"]))
            os.environ["GIT_COMMITTER_DATE"] = "{0:.0f}".format(release_data["release"]["timestamp"])
        
        # Find which packages need updated for this new tag content file
        import_list, packages_considered = find_packages_for_update(release_data, tag_list, branch, 
                                                                    svn_metadata_cache, current_release_tags, only_forward)

        ## Sort the list of tags to be imported by SVN revision number for a
        #  more or less sensible package by package commit history
        sorted_import_revisions = import_list.keys()
        sorted_import_revisions.sort(cmp=lambda x,y: cmp(int(x), int(y)))

        ## Now loop over all the packages we have to import and update them
        pkg_processed = 0
        for revision in sorted_import_revisions:
            for pkg_import in import_list[revision]:
                pkg_processed += 1
                do_package_import(pkg_import, svn_metadata_cache, author_metadata_cache, release_name=release_data["release"]["name"], 
                                  branch=branch, dryrun=dryrun, commit_date=commit_date)
                logger.info("Processed {0}/{1} revisions".format(pkg_processed, len(import_list)))


        ## After all packages are updated, look for packages which present in the last
        #  release, but not this one, so they need to be removed
        new_current_release_tags = get_current_release_tag_dict(tag_list, branch) # Updated package list after upgrade
        packages_to_remove = []
        packages_to_revert = {}
        for package_name, old_package_state in current_release_tags.iteritems():
            if package_name in packages_considered:
                logger.debug("Package {0} was processed for {1}".format(package_name, release_data["release"]["name"]))
                continue
            ## @note We have a package that was not "considered" in the current release.
            #  If we don't have a baserelease then this has been removed, so we zap it.
            #  If there is a baserelease... 
            #   ...and this package is not in it, it was in the cache, then was removed, so zap it.
            #   ...and this package is in it, then compare the versions and "revert" to the base 
            #      release version if they are different.
            if baserelease:
                base_package_version = None
                for package, base_package_data in baserelease["tags"].iteritems():
                    if base_package_data["package_name"] == package_name:
                        base_package_version = base_package_data
                        break
                if base_package_version:
                    if base_package_version["svn_tag"] == old_package_state["svn_tag"]:
                        logger.debug("Package {0} remains at base release version {1}".format(base_package_data["package_name"],
                                                                                              base_package_version["svn_tag"]))
                        packages_considered.append(package_name) # Flag we dealt this package
                    else:
                        logger.info("Package {0} was removed from cache - reverting to base "
                                    "release version {1}".format(base_package_data["package_name"],
                                                     base_package_version["svn_tag"]))
                        package_name = base_package_data["package_name"]
                        svn_meta_tag_key = os.path.join("tags", base_package_version["svn_tag"])
                        svn_revision = svn_metadata_cache[package_name]["svn"][svn_meta_tag_key].keys()[0]
                        git_import_tag = get_flattened_git_tag(package, base_package_version["svn_tag"], svn_revision)
                        packages_to_revert[package_name] = {"package": package,
                                                            "package_name": os.path.basename(package),
                                                            "git_import_tag": get_flattened_git_tag(package, base_package_version["svn_tag"], svn_revision),
                                                            "svn_tag": base_package_version["svn_tag"],
                                                            "svn_revision": svn_revision,
                                                            "branch_import_tag": get_flattened_git_tag(package, base_package_version["svn_tag"], svn_revision, branch),
                                                            "svn_meta_tag_key": svn_meta_tag_key,
                                                            "current_branch_import_tag": current_release_tags[package_name]["git_tag"]}
                else:
                    logger.info("Package {0} was removed from the cache and is not in the base release".format(package_name))
                    packages_to_remove.append(package_name)
            else:
                logger.info("Package {0} has been removed from the release".format(package_name))
                packages_to_remove.append(package_name)

        if baserelease:
            logger.info("{0} packages have been reverted to their base SVN state".format(len(packages_to_revert)))
            for package_name, revert_data in packages_to_revert.iteritems():
                do_package_import(revert_data, svn_metadata_cache, author_metadata_cache, release_name=release_data["release"]["name"], 
                                  branch=branch, dryrun=dryrun, commit_date=commit_date)

        logger.info("{0} packages have been removed from the release".format(len(packages_to_remove)))
        for package in packages_to_remove:
            logger.info("Removing {0} from {1}".format(package, branch))
            if not dryrun:
                package_path = os.path.join(svn_metadata_cache[package]["path"], package)
                recursive_delete(package_path)
            check_output_with_retry(("git", "add", "-A"), dryrun=dryrun)
            cmd = ["git", "commit", "--allow-empty", "-m", "{0} deleted from {1}".format(package_path, branch)]
            check_output_with_retry(cmd, dryrun=dryrun)
            check_output_with_retry(("git", "tag", "-d", current_release_tags[package]["git_tag"]), retries=1, dryrun=dryrun)
            pkg_processed += 1

        ## Now, finally, tag the release as done
        if not skipreleasetag:
            if release_data["release"]["nightly"]:
                check_output_with_retry(("git", "tag", release_tag), retries=1, dryrun=dryrun)
            else:
                check_output_with_retry(("git", "tag", release_tag, "-a",
                                         "-m", "Tagging release {0}".format(release_data["release"]["name"])), 
                                        retries=1, dryrun=dryrun)
            logger.info("Tagged release {0} as {1} "
                        "({2} packages processed)".format(release_data["release"]["name"],
                                                          release_tag, pkg_processed))
        else:
            logger.info("Processed release {0} (no tag; {1} packages processed)".format(release_data["release"]["name"], pkg_processed))


def main():
    parser = argparse.ArgumentParser(description='git branch constructor')
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="Location of git repository")
    parser.add_argument('branchname',
                        help="Git branch name to build")
    parser.add_argument('tagfiles', metavar="TAGFILE", nargs="+", 
                        help="Tag files to use to build git branch from")
    parser.add_argument('--parentbranch', metavar="BRANCH:COMMIT or BRANCH:@TIMESTAMP",
                        help="If branch does not yet exist, use this BRANCH to make it from at COMMIT "
                        "(otherwise an orphaned branch is created). The syntax BRANCH:@TIMESTAMP will "
                        "find the commit closest to the given TIMESTAMP.")
    parser.add_argument('--baserelease', metavar="FILE",
                        help="For cache releases, use this tag file as the content of the base release on which "
                        "the release was a cache")
    parser.add_argument('--svnmetadata', metavar="FILE",
                        help="File with SVN metadata per SVN tag in the git repository. "
                        "By default GITREPO.svn.metadata will be used, if it exists.")
    parser.add_argument('--authorcachefile', metavar='FILE',
                        help="File containing cache of author name and email information - default '[gitrepo].author.metadata'")
    parser.add_argument('--skipreleasetag', action="store_true",
                        help="Do not create a git tag for this release, nor skip processing if a release tag "
                        "exists - use this option to add packages to a branch encapsulating an entire "
                        "release series, like 'master'.")
    parser.add_argument('--onlyforward', action="store_true",
                        help="Process tag files as usual, but never "
                        "downgrade a tag to a previous version. This can be used to reconstruct a master branch "
                        "that only goes forward in revision history (it is very useful for the initial master "
                        "branch constuction). In addition branch series releases that overlap with later releases "
                        "will not be imported so that (again) the master branch does not go backwards in time.")
    parser.add_argument("--commitdate", choices=["now", "release", "author"],
                        help="Strategy for setting git committer date: now - leave as current time; "
                        "release - set to time of the current release being processed; author - "
                        "set to author date, as found from SVN (default %(default)s)", default = "release")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")
    parser.add_argument('--dryrun', action="store_true",
                        help="Perform no actions, but print what would happen")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    gitrepo = os.path.abspath(args.gitrepo)
    branch = args.branchname
    
    # If the onlyforward option is set, then we need to preprocess the list of tag content
    # files in order to ensure that we never jump across time to a previous release series 
    # when making the master branch. This is because the earlier release series will be 
    # branched off from and the later releases on that series really only make sense 
    # for the branch
    if args.onlyforward:
        print args.tagfiles
        args.tagfiles = backskip_filter(args.tagfiles)
        print args.tagfiles    
    tag_files = [ os.path.abspath(fname) for fname in args.tagfiles ]
    
    # If we have a baserelease tag content, then load that here
    if args.baserelease:
        with open(args.baserelease) as br_tags_fh:
            base_tags = json.load(br_tags_fh)
    else:
        base_tags = None
        
    # Load SVN metadata cache - this is the fastest way to query the SVN ordering in which tags
    # were made
    if not args.svnmetadata and os.access(args.gitrepo + ".svn.metadata", os.R_OK):
        args.svnmetadata = args.gitrepo + ".svn.metadata"
    else:
        logger.error("No SVN metadata cache found - cannot proceed")
        sys.exit(1)
    with open(args.svnmetadata) as cache_fh:
        svn_metadata_cache = json.load(cache_fh)
    logger.info("Loaded SVN metadata from {0}".format(args.svnmetadata))
    
    # Load author cache info
    if not args.authorcachefile:
        args.authorcachefile = args.gitrepo + ".author.metadata"
    try:
        with open(args.authorcachefile) as cache_fh:
            author_metadata_cache = json.load(cache_fh)
    except OSError:
        logger.warning("No author metadata found - will proceed without")
        author_metadata_cache = {}
    
    # Main branch reconstruction function
    branch_builder(gitrepo, args.branchname, tag_files, svn_metadata_cache, author_metadata_cache, parentbranch=args.parentbranch, 
                   baserelease=base_tags, skipreleasetag=args.skipreleasetag, dryrun=args.dryrun, only_forward=args.onlyforward,
                   commit_date=args.commitdate)
    

if __name__ == '__main__':
    main()
