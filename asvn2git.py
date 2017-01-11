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
#           "msg" : "'CMakeLists.txt'",
#           "revision": 735942,
#           "author": "alibrari"
#         }
#       },
#       "trunk": {
#         "735943": {
#           "date": "2016-04-08T16:35:05",
#           "msg" : "'CMakeLists.txt'",
#           "revision": 735943,
#           "author": "alibrari"
#         }
#       }
#     },
#     ...
#   }
#
# author_metadata_cache is a dictionary keyed by SVN committer (==SSO username), with a value
#  as a dictionary containing "email" and "name" keys. e.g.,
# {
#   "graemes": {"email": "graeme.andrew.stewart@cern.ch", "name": "Graeme A Stewart"},
#   "wlampl":  {"email": "Walter.Lampl@cern.ch", "name": "Walter Lampl"},
#   ...
# }

import argparse
import json
import logging
import os.path
import time

from glogger import logger
from atutils import check_output_with_retry, get_current_git_tags, switch_to_branch
from atutils import get_flattened_git_tag, initialise_metadata, backup_metadata
from svnutils import scan_svn_tags_and_get_metadata, svn_co_tag_and_commit
from svnutils import load_exceptions_file


def svn_cache_revision_dict_init(svn_metadata_cache):
    ## @brief Build a dictionary keyed by SVN revision and indicating which tags changed there
    #  @param svn_metadata_cache SVN metadata cache
    #  @return Cache revision dictionary with value list of packages and tags
    svn_cache_revision_dict = {}
    for package_name in svn_metadata_cache:
        for tag in svn_metadata_cache[package_name]["svn"]:
            for revision in svn_metadata_cache[package_name]["svn"][tag]:
                element = {"package": os.path.join(svn_metadata_cache[package_name]["path"], package_name), 
                           "tag": tag, "revision": revision}
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


def get_tags(tag_files, svn_path_accept):
    ## @brief Parse packages and package tags from release diff files
    #  @param tag_files List of release tag files to query
    #  @param svn_path_accept List of paths to filter on
    #  @return dictionary keyed by package (including path) and value as sorted list of tags
    svn_package_tags = {}
    for tag_file in tag_files:
        with open(tag_file) as tag_fh:
            tag_dict = json.load(tag_fh)
            logger.info("Getting tag lists from {0}".format(tag_dict["release"]["name"]))
            for package, package_info in tag_dict["tags"].iteritems():
                if len(svn_path_accept) > 0:
                    accept = False
                    for path in svn_path_accept:
                        if package.startswith(path):
                            accept = True
                            break
                    if not accept:
                        continue
                svn_tag = package_info["svn_tag"]
                if svn_tag != "trunk":
                    svn_tag = os.path.join("tags", svn_tag)
                if package in svn_package_tags:
                    svn_package_tags[package].add(svn_tag)
                else:
                    svn_package_tags[package] = set((svn_tag,))
    # Now convert back to list and sort tags...
    for package in svn_package_tags:
        svn_package_tags[package] = list(svn_package_tags[package])
        svn_package_tags[package].sort()
    return svn_package_tags

        
def main():
    parser = argparse.ArgumentParser(description='SVN to git migrator, ATLAS style')
    parser.add_argument('svnroot', metavar='SVNDIR',
                        help="Location of svn repository root")
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="Location of git repository")
    parser.add_argument('tagfiles', nargs="+", metavar='TAGFILE',
                        help="List of release tag content files to process - all tags found in these files will "
                        "be imported (any already imported tags will be skipped)")
    parser.add_argument('--targetbranch', default="package",
                        help="Target git branch for import. Default is the special value 'package' in which "
                        "each package is imported onto its own branch")
    parser.add_argument('--svnpath', metavar='PATH', nargs='+', default=[],
                        help="Restrict actions to this list of paths in the SVN tree (use to "
                        "make small scale tests of the import workflow).")
    parser.add_argument('--intermediatetags', action="store_true",
                        help="Import all tags from oldest release tag found, instead of just release tags")
    parser.add_argument('--processtrunk', action="store_true",
                        help="Update trunk versions during the import (False by default, the trunk will be skipped).")
    parser.add_argument('--svncachefile', metavar='FILE',
                        help="File containing cache of SVN information - default '[gitrepo].svn.metadata'")
    parser.add_argument('--authorcachefile', metavar='FILE',
                        help="File containing cache of author name and email information - default '[gitrepo].author.metadata'")
    parser.add_argument('--importtimingfile', metavar="FILE",
                        help="File to dump SVN->git import timing information - default '[gitrepo]-timing.json'")
    parser.add_argument('--svnfilterexceptions', '--sfe', metavar="FILE",
                        help="File listing path globs to exempt from SVN import filter (lines with '+PATH') or "
                        "to always reject (lines with '-PATH'); default %(default)s. Use NONE to have no exceptions.",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlasoffline-exceptions.txt"))
    parser.add_argument('--licensefile', metavar="FILE", help="License file to add to source code files (default "
                        "is not to add a license file)")
    parser.add_argument('--licenseexceptions', metavar="FILE", help="File listing path globs to exempt from or  "
                        "always apply license file to (same format as --svnfilterexceptions)",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlaslicense-exceptions.txt"))
    parser.add_argument('--uncrustify', metavar="FILE", help="Uncrustify configuration file to use to process C++ "
                        "sources through before git import (by default uncrustify will not be used)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    # Massage default values
    if not args.svncachefile:
        args.svncachefile = os.path.basename(args.gitrepo) + ".svn.metadata"
    if not args.authorcachefile:
        args.authorcachefile = os.path.basename(args.gitrepo) + ".author.metadata"
    if not args.importtimingfile:
        args.importtimingfile = os.path.basename(args.gitrepo) + "-timing.json"

    # Set svnroot and git repo, get some starting values
    svnroot = args.svnroot
    gitrepo = os.path.abspath(args.gitrepo)
    start_cwd = os.getcwd()
    start_timestamp_string = time.strftime("%Y%m%dT%H%M.%S")
    logger.debug("Set SVN root to {0} and git repo to {1}".format(svnroot, gitrepo))
    
    # Load exception globs
    svn_path_accept, svn_path_reject = load_exceptions_file(args.svnfilterexceptions)

    # License file loading
    if args.licensefile:
        with open(args.licensefile) as lfh:
            license_text = [ line.rstrip() for line in lfh.readlines() ]
    else:
        license_text = None
    if args.licenseexceptions:
        license_path_accept, license_path_reject = load_exceptions_file(args.licenseexceptions)
    else:
        license_path_accept = license_path_reject = []


    ### Main actions start here
    # Setup the git repository
    init_git(gitrepo)
    # Pull current list of tags here, to fast skip any work already done
    if args.targetbranch != "package":
        switch_to_branch(args.targetbranch, orphan=True)
    current_git_tags = get_current_git_tags(gitrepo)
    os.chdir(start_cwd)
    
    ## SVN interactions and reloading state    
    # Decide which svn packages we will import
    # Note that if we're pulling the packages from a tag diff file, we also get tags
    # at this point, otherwise the tag list is empty.
    svn_packages = get_tags(args.tagfiles, args.svnpath)
    # Add "trunk" packages, if required
    if args.processtrunk:
        for package, tags in svn_packages.iteritems():
            if "trunk" not in tags:
                tags.append("trunk")

    # Initialise SVN and author metadata cache with any stored values
    svn_metadata_cache = initialise_metadata(args.svncachefile)
    author_metadata_cache = initialise_metadata(args.authorcachefile)

    # Prepare package import
    scan_svn_tags_and_get_metadata(svnroot, svn_packages, svn_metadata_cache, author_metadata_cache, args.intermediatetags)

    # Now presistify metadata cache
    backup_metadata(svn_metadata_cache, start_cwd, args.svncachefile, start_timestamp_string)
    backup_metadata(author_metadata_cache, start_cwd, args.authorcachefile, start_timestamp_string)
    
    # Setup dictionary for keying by SVN revision number
    svn_cache_revision_dict = svn_cache_revision_dict_init(svn_metadata_cache)

    ## git processing actions
    # Process each SVN tag in order
    ordered_revisions = svn_cache_revision_dict.keys()
    ordered_revisions.sort(cmp=lambda x,y: cmp(int(x), int(y)))
    logger.info("Will process {0} SVN revisions in total".format(len(ordered_revisions)))
    counter=0
    processed_tags=0
    timing = []
    os.chdir(gitrepo)
    
    for rev in ordered_revisions:
        counter+=1
        start=time.time()
        logger.info("SVN Revsion {0} ({1} of {2})".format(rev, counter, len(ordered_revisions)))
        for pkg_tag in svn_cache_revision_dict[rev]:
            if get_flattened_git_tag(pkg_tag["package"], pkg_tag["tag"], rev) in current_git_tags:
                logger.info("Tag {0} exists already - skipping".format(os.path.join(pkg_tag["package"], pkg_tag["tag"])))
                continue
            if args.targetbranch == "package":
                switch_to_branch(os.path.basename(pkg_tag["package"]), orphan=True)
            svn_co_tag_and_commit(svnroot, gitrepo, pkg_tag["package"], pkg_tag["tag"], 
                                  svn_metadata_cache[os.path.basename(pkg_tag["package"])]["svn"][pkg_tag["tag"]][rev],
                                  author_metadata_cache,
                                  svn_path_accept=svn_path_accept,
                                  svn_path_reject=svn_path_reject,
                                  license_text=license_text,
                                  license_path_accept=license_path_accept,
                                  license_path_reject=license_path_reject,
                                  uncrustify_config=args.uncrustify)
            processed_tags += 1
        elapsed = time.time()-start
        logger.info("{0} processed in {1}s ({2} packages really processed)".format(counter, elapsed, processed_tags))
        timing.append(elapsed)
        
    if args.importtimingfile:
        os.chdir(start_cwd)
        with open(args.importtimingfile, "w") as time_file:
            json.dump(timing, time_file)
            
    # Last task, clean all empty directories (git does not track these, but they are clutter)
    check_output_with_retry(("find", gitrepo, "-type", "d", "-empty", "-delete"))

if __name__ == '__main__':
    main()

