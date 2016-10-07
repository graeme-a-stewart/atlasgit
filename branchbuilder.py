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
import pprint
import shutil
import sys

from glogger import logger
from atutils import check_output_with_retry, get_current_git_tags, author_string, recursive_delete
from atutils import switch_to_branch, get_flattened_git_tag, changelog_diff


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


def find_packages_for_update(release_data, tag_list, branch, svn_metadata_cache, release_tag_unprocessed):
    ## @brief Find packages that need updates, comparing release tag content with
    #  git import tags already made
    #  @param release_data Release tag content dictionary
    #  @param tag_list List of current git tags
    #  @param branch Git branch being constructed
    #  @param svn_metadata_cache Usual cache data for SVN stuff
    #  @param release_tag_unprocessed Dictionary with current "tag" metadata, useful to mark up import
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
        package_tag = package_data["tag"]
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
            logger.debug("Considering import of {0} (r{1}) to {2} "
                         "for release {3}".format(branch_import_tag, revision, branch, release_data["release"]["name"]))
            if branch_import_tag in tag_list:
                logger.info("Import of {0} ({1} r{2}) onto {3} done - skipping".format(package, package_tag, revision, branch))
                continue
            ## @note The structure of the dictionary used to direct the import of a package is:
            #  "package": full package path
            #  "package_name": package basename (for convenience)
            #  "git_import_tag": the git import tag that identifies the import of the version of this package
            #  "svn_tag": the SVN tag corresponding to this package version
            #  "branch_import_tag": the git import tag that will be created to stamp this import as done
            #  "svn_meta_tag_key": the key used in the SVN metadata dictionary to get SVN metadata
            #  "current_branch_import_tag": the git tag indicating the current version of this package 
            import_element = {"package": package, 
                              "package_name": os.path.basename(package),
                              "git_import_tag": git_import_tag, 
                              "svn_tag": package_tag, 
                              "branch_import_tag": branch_import_tag, "svn_meta_tag_key": svn_meta_tag_key, 
                              "current_branch_import_tag": release_tag_unprocessed[package_name]["git_tag"] if package_name in release_tag_unprocessed else None}
            logger.debug("Will import {0} to {1}".format(import_element, branch))
            if revision in import_list:
                import_list[revision].append(import_element)
            else:
                import_list[revision] = [import_element]

    return import_list, packages_considered


def do_package_import(pkg_import, svn_metadata_cache, author_metadata_cache, release_name="unknown", branch="unknown", dryrun=False):
    ## @brief Import a package's SVN tag onto the current git branch
    #  updating the corresponding git tags
    #  @param pkg_import package import dictionary (see find_packages_for_update for the
    #  structure)
    #  @param svn_metadata_cache The standard metadata cache from SVN
    #  @param author_metadata_cache Cached author data
    #  @param release_name Name of current release being built (used only for generating log messages)
    #  @param branch Current branch name (used only for generating log messages)
    #  @param dryrun Boolean, if @c true then don't actually act
    logger.info("Migrating {0} from {1} to {2} for {3}...".format(pkg_import["package"], 
                                                          pkg_import["current_pkg_tag"], 
                                                          pkg_import["svn_tag"], release_name))
    # Need to wipe out all contents in case files were removed from package
    if not dryrun:
        recursive_delete(pkg_import["package"])
    check_output_with_retry(("git", "checkout", pkg_import["git_import_tag"], pkg_import["package"]), dryrun=dryrun)
    # Done - now commit and tag
    if logger.level <= logging.DEBUG:
        cmd = ["git", "status"]
        logger.debug(check_output_with_retry(cmd))
    check_output_with_retry(("git", "add", "-A", pkg_import["package"]), dryrun=dryrun)
    staged = check_output_with_retry(("git", "diff", "--name-only", "--staged"), dryrun=dryrun)
    if len(staged) == 0 and (not dryrun): # Nothing staged, so skip (how did this happen - the tag did change)
        logger.warning("Package {0} - no changes staged for {1}," 
                       "skipping".format(pkg_import["package"], release_name))
        continue
    msg = "{0} imported onto {1}".format(pkg_import["package"], branch)
    if pkg_import["svn_tag"] == "trunk":
        msg += " (trunk r{0})".format(revision)
    else:
        msg += " ({0})".format(pkg_import["svn_tag"])
    cl_diff = changelog_diff(pkg_import["package"], staged=True)
    if cl_diff:
        msg += "\n\n" + "\n".join(cl_diff)
    cmd = ["git", "commit", "-m", msg]
    author = author_string(svn_metadata_cache[pkg_import["package_name"]]["svn_tag"][pkg_import["svn_meta_tag_key"]][revision]["author"], author_metadata_cache)
    date = svn_metadata_cache[pkg_import["package_name"]]["svn_tag"][pkg_import["svn_meta_tag_key"]][revision]["date"]
    cmd.append("--author='{0}'".format(author))
    cmd.append("--date={0}".format(date))
    os.environ["GIT_COMMITTER_DATE"] = date
    check_output_with_retry(cmd, retries=1, dryrun=dryrun)
    if pkg_import["branch_import_tag"] not in tag_list:
        check_output_with_retry(("git", "tag", pkg_import["branch_import_tag"]), retries=1, dryrun=dryrun)
    if pkg_import["current_branch_import_tag"]:
        check_output_with_retry(("git", "tag", "-d", pkg_import["current_branch_import_tag"]), retries=1, dryrun=dryrun)
    logger.info("Committed {0} ({1}) onto {2} for {3}".format(pkg_import["package"], 
                                                              pkg_import["svn_tag"], branch, release_name))


def branch_builder(gitrepo, branch, tag_files, svn_metadata_cache, author_metadata_cache,
                   parentbranch=None, baserelease=None,
                   skipreleasetag=False, dryrun=False):
    ## @brief Main branch builder function
    #  @param gitrepo The git repository location
    #  @param branch The git branch to work on
    #  @param tag_files The plain tag content files to process
    #  @param svn_metadata_cache The standard metadata cache from SVN
    #  @param author_metadata_cache Cached author data
    #  @param parentbranch If creating a new branch, this is the BRANCH:COMMIT_ID of where to make the new branch from
    #  @param skipreleasetag If @c True then skip creating git tags for each processed release
    #  @param dryrun If @c True, do nothing except print commands that would have been executed
    
    # Prepare - chdir and then make sure we are on the correct branch
    os.chdir(gitrepo)    
    if not parentbranch:
        # @todo This should be a lot smarter and take a branch point from master...
        logger.info("Switching to branch {0}".format(branch))
        switch_to_branch(branch, orphan=True)
    else:
        parent, commit = parentbranch.split(":")
        check_output_with_retry(("git", "checkout", parent), retries=1, dryrun=dryrun) # needed?
        check_output_with_retry(("git", "checkout", commit), retries=1, dryrun=dryrun)
        check_output_with_retry(("git", "checkout", "-b", branch), retries=1, dryrun=dryrun)

    # Main loop starts here, with one pass for each tag file we are processing
    for tag_file in tag_files:
        with open(tag_file) as tag_file_fh:
            release_data = json.load(tag_file_fh)

        tag_list = get_current_git_tags(gitrepo)
        current_release_tags = get_current_release_tag_dict(tag_list, branch) # Markers for which packages have been processed
        logger.info("Processing release {0} ({1} current tags)".format(release_data["release"]["name"], len(current_release_tags)))
        release_tag = os.path.join("release", release_data["release"]["name"])
        if release_tag in tag_list and not skipreleasetag:
            logger.info("Release tag {0} already made - skipping".format(release_tag))
            continue
        
        # Find which packages need updated for this new tag content file
        import_list, packages_considered = find_packages_for_update(release_data, tag_list, branch, 
                                                                    svn_metadata_cache, current_release_tags)

        ## Sort the list of tags to be imported by SVN revision number for a
        #  more or less sensible package by package commit history
        sorted_import_revisions = import_list.keys()
        sorted_import_revisions.sort(cmp=lambda x,y: cmp(int(x), int(y)))

        ## Now loop over all the packages we have to import and update them
        pkg_processed = 0
        for revision in sorted_import_revisions:
            for pkg_import in import_list[revision]:
                pkg_processed += 1
                do_import_package(pkg_import, svn_metadata_cache, author_metadata_cache, release_name=release_data["release"]["name"], 
                                  branch=branch, dryrun=dryrun)
                logger.info("Processed {0}/{1} revisions".format(pkg_processed, len(import_list)))


        ## After all packages are updated, look for packages which present in the last
        #  release, but not this one, so they need to be removed
        new_current_release_tags = get_current_release_tag_dict(tag_list, branch) # Updated package list after upgrade
        packages_to_remove = []
        packages_to_revert = {}
        for package_name, old_package_state in current_release_tags[:]:
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
                for package, base_package_data in baserelease:
                    if base_package_data["package_name"] == package_name:
                        base_package_version = base_package_data
                        break
                if base_package_version:
                    if base_package_version["svn_tag"] == old_package_state["svn_tag"]:
                        logger.debug("Package {0} remains at base release version {1}".format(base_package_data["package"],
                                                                                              base_package_version["svn_tag"]))
                        packages_considered.append(package_name) # Flag we dealt this package
                    else:
                        logger.info("Package {0} was removed from cache - reverting to base "
                                    "release version {1}".format(base_package_data["package"],
                                                     base_package_version["svn_tag"]))
                        package_name = os.path.basename(package)
                        svn_meta_tag_key = os.path.join("tags", base_package_version["svn_tag"])
                        svn_revision = svn_metadata_cache[package_name]["svn"][svn_meta_tag_key].keys()[0]
                        git_import_tag = get_flattened_git_tag(package, base_package_version["svn_tag"], svn_revision)
                        packages_to_revert[package_name] = {"package": package,
                                                            "package_name": os.path.basename(package),
                                                            "git_import_tag": get_flattened_git_tag(package, base_package_version["svn_tag"], svn_revision),
                                                            "svn_tag": base_package_version["svn_tag"],
                                                            "branch_import_tag": get_flattened_git_tag(package, base_package_version["svn_tag"], svn_revision, branch),
                                                            "svn_meta_tag_key": svn_meta_tag_key,
                                                            "current_branch_import_tag": current_release_tags[package]["git_tag"]}
                else:
                    logger.info("Package {0} was removed from the cache and is not in the base release".format(package_name))
                    packages_to_remove.append(package_name)
            else:
                logger.info("Package {0} has been removed from the release".format(package_name))
                packages_to_remove.append(package_name)
        
        if baserelease:
            logger.info("{0} packages have been reverted to their base SVN state".format(len(packages_to_revert)))
            for package_name, revert_data in packages_to_revert.iteritems():
                do_import_package(revert_data, svn_metadata_cache, author_metadata_cache, release_name=release_data["release"]["name"], 
                                  branch=branch, dryrun=dryrun)
        
        logger.info("{0} packages have been removed from the release".format(len(packages_to_remove)))
        for package in packages_to_remove:
            logger.info("Removing {0} from {1}".format(package, branch))
            if not dryrun:
                package_path = os.path.join(svn_metadata_cache[removed_package]["path"], removed_package)
                recursive_delete(package_path)
            check_output_with_retry(("git", "add", "-A"), dryrun=dryrun)
            cmd = ["git", "commit", "--allow-empty", "-m", "{0} deleted from {1}".format(package_path, branch)]
            check_output_with_retry(cmd, dryrun=dryrun)
            check_output_with_retry(("git", "tag", "-d", current_release_tags[package]["git_tag"]), retries=1, dryrun=dryrun)
            pkg_processed += 1

        ## Now, finally, tag the release as done
        if release_data["release"]["type"] != "snapshot" and not skipreleasetag:
            if release_data["release"]["nightly"]:
                stub = "nightly"
            else:
                stub = "release"
            check_output_with_retry(("git", "tag", os.path.join(stub, release_data["release"]["name"])), retries=1, dryrun=dryrun)
            logger.info("Tagged release {0} ({1} packages processed)".format(release_data["release"]["name"], pkg_processed))
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
    parser.add_argument('--parentbranch', metavar="BRANCH:COMMIT",
                        help="If branch does not yet exist, use this BRANCH to make it from at COMMIT "
                        "(otherwise an orphaned branch is created)")
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
                        "exists - use this option to add packages to a 'secondary' branch from the main "
                        "release branch. Set true by default if the target branch is 'master'.")
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
    tag_files = [ os.path.abspath(fname) for fname in args.tagfiles ]
    
    if branch == "master":
        args.skipreleasetag = True
        
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
        logger.info("Found SVN metadata cache here: {0}".format(args.svnmetadata))
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
                   baserelease=base_tags, skipreleasetag=args.skipreleasetag, dryrun=args.dryrun)
    

if __name__ == '__main__':
    main()
