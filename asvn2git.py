#! /usr/bin/env python
#
# Prototype migration script from atlasoff to git,
# moving sets of package tags identified with releases
# to branches, and making tags for identified release
# builds
#

import argparse
import json
import logging
import os
import os.path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as eltree

# Setup basic logging
logger = logging.getLogger('as2g')
hdlr = logging.StreamHandler(sys.stdout)
frmt = logging.Formatter("%(name)s.%(funcName)s %(levelname)s %(message)s")
hdlr.setFormatter(frmt)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)


def check_output_with_retry(cmd, retries=3, wait=10):
    '''Multiple attempt wrapper for subprocess.check_call (especially remote SVN commands can bork)'''
    success = failure = False
    tries = 0
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
    return output
    

def set_svn_packages_from_args(svnroot, args):
    '''Return a list of svn packages to import, based on args settings'''
    svn_packages = args.svnpackage
    if args.svnpackagefile and os.path.exists(args.svnpackagefile):
        logger.info("Reading packages to import from {0}".format(args.svnpackagefile))
        with open(args.svnpackagefile) as pkg_file:
            for package in pkg_file:
                package = package.strip()
                if package.startswith("#") or package == "":
                    continue
                svn_packages.append(package)
    for path_element in args.svnpath:
        svn_packages.extend(svn_find_packages(svnroot, path_element, args.svnpathveto))
    # De-duplicate and clean unwanted prefix/suffix pieces of the path
    svn_packages = [ pkg.rstrip("/").lstrip("./") for pkg in set(svn_packages) ]
    logger.debug("Packages to import: {0}".format(svn_packages))
    return svn_packages


def backup_package_list(svn_packages, start_cwd, svnpackagefile, start_timestamp_string):
    '''Backup package lists to a file'''
    os.chdir(start_cwd)
    if os.path.exists(svnpackagefile):
        os.rename(svnpackagefile, svnpackagefile+".bak."+start_timestamp_string)
    with open(svnpackagefile, "w") as pkg_dump:
        for package in svn_packages:
            print >>pkg_dump, package


def initialise_svn_metadata(svncachefile):
    '''Load existing cache file, if it exists, or return empty cache'''
    if os.path.exists(svncachefile):
        logger.info("Reloading SVN cache from {0}".format(svncachefile))
        with file(svncachefile) as md_load:
            svn_metadata_cache = json.load(md_load)
    else:
        svn_metadata_cache = {}
    return svn_metadata_cache


def scan_svn_tags_and_get_metadata(svnroot, svn_packages, svn_metadata_cache, trimtags=None, oldest_time=None):
    '''Scan package tags from SVN and populate metadata cache if necessary'''
    for package in svn_packages:
        logger.info("Preparing package {0}".format(package))
        tags = get_all_package_tags(svnroot, package)
        last_veto_tag = None
        
        if trimtags:
            # Restrict tag list size
            tags = tags[-trimtags:]

        for tag in tags:
            # Do we have metadata?
            if package not in svn_metadata_cache:
                svn_metadata_cache[package] = {}
            if tag not in svn_metadata_cache[package]:
                svn_metadata = svn_get_path_metadata(svnroot, package, tag)
                if oldest_time:
                    svn_time = time.strptime(svn_metadata["date"], '%Y-%m-%dT%H:%M:%S')
                    if svn_time < oldest_time:
                        logger.debug("Vetoed {0} ({1} is too old)".format(tag, svn_metadata["date"]))
                        # We save the latest trunk tag before the time veto, so that we have the trunk
                        # tag on the time boundary
                        # N.B. This relies on the time ordering of tags from "svn ls"!
                        if is_trunk_tag(tag):
                            last_veto_tag = tag
                        continue
                if last_veto_tag:
                    svn_metadata_cache[package][last_veto_tag] = svn_get_path_metadata(svnroot, package, last_veto_tag)
                    last_veto_tag = None
                svn_metadata_cache[package][tag] = svn_get_path_metadata(svnroot, package, tag)


def get_all_package_tags(svnroot, package_path, include_trunk=True):
    '''Retrieve all tags for a package in svnroot'''
    cmd = ["svn", "ls", os.path.join(svnroot, package_path, "tags")]
    tag_output = check_output_with_retry(cmd)
    tag_list = [ os.path.join("tags", s.rstrip("/")) for s in tag_output.split() ]
    if include_trunk:
        tag_list.append("trunk")
    return tag_list


def svn_cache_revision_dict_init(svn_metadata_cache):
    svn_cache_revision_dict = {}
    for package in svn_metadata_cache:
        for tag in svn_metadata_cache[package]:
            if svn_metadata_cache[package][tag]["revision"] in svn_cache_revision_dict:
                # It is possible for a single SVN commit to straddle packages
                svn_cache_revision_dict[svn_metadata_cache[package][tag]["revision"]].append({"package": package, "tag": tag})
            else:
                svn_cache_revision_dict[svn_metadata_cache[package][tag]["revision"]] = [{"package": package, "tag": tag}]
    return svn_cache_revision_dict


def backup_svn_metadata(svn_metadata_cache, start_cwd, svncachefile, start_timestamp_string):
    '''Persistify SVN metadata cache (as JSON)'''
    os.chdir(start_cwd)
    if os.path.exists(svncachefile):
        os.rename(svncachefile, svncachefile+".bak."+start_timestamp_string)
    with file(svncachefile, "w") as md_dump:
        json.dump(svn_metadata_cache, md_dump, indent=2)


def init_git(gitrepo):
    '''Initialise git repo, if needed'''
    if not os.path.exists(gitrepo):
        os.makedirs(gitrepo)
    os.chdir(gitrepo)
    if os.path.exists(os.path.join(gitrepo, ".git")):
        logger.info("Found existing git repo, {0}".format(gitrepo))
        check_output_with_retry(("git", "reset", "--hard"))
    else:
        logger.info("Initialising git repo: {0}".format(gitrepo))
        check_output_with_retry(("git", "init"))


def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, svn_metadata = None, branch="master"):
    '''Make a temporary space, check out from svn, clean-up, copy and then git commit and tag'''
    logger.info("processing {0} tag {1} to branch {2}".format(package, tag, branch))
    tempdir = tempfile.mkdtemp()
    full_svn_path = os.path.join(tempdir, package)
    cmd = ["svn", "co", os.path.join(svnroot, package, tag), os.path.join(tempdir, package)]
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
    logger.info("Moving {0} to {1}".format(full_svn_path, package_root))
    shutil.move(full_svn_path, package_root)
    
    # Commit
    os.chdir(gitrepo)
    cmd = ["git", "add", package]
    check_output_with_retry(cmd)
    if logger.level <= logging.DEBUG:
        cmd = ["git", "status"]
        logger.debug(check_output_with_retry(cmd))
    cmd = ["git", "commit", "--allow-empty", "-m", "{0} tag {1}".format(package, tag)]
    if svn_metadata:
        cmd.extend(("--author='{0} <{0}@cern.ch>".format(svn_metadata["author"]), 
                    "--date={0}".format(svn_metadata["date"]),
                    "-m", "SVN r{0}".format(svn_metadata['revision'])))
    check_output_with_retry(cmd)
    cmd = ["git", "tag", "-a", os.path.join(package, tag), "-m", ""]
    check_output_with_retry(cmd)
    
    # Clean up
    shutil.rmtree(tempdir)
    
def svn_cleanup(svn_path):
    '''Cleanout files we do not want to import into git'''
    shutil.rmtree(os.path.join(svn_path, ".svn"))
    
    # File size veto
    for root, dirs, files in os.walk(svn_path):
        for name in files:
            filename = os.path.join(root, name)
            try:
                if os.stat(filename).st_size > 100*1024:
                    if "." in name and name.rsplit(".", 1)[1] in ("cxx", "py", "h", "java", "cc", "c"):
                        logger.info("Source file {0} is too large, but importing anyway".format(filename))
                    elif name in ("ChangeLog"):
                        logger.info("Repo file {0} is too large, but importing anyway".format(filename))
                    else:
                        logger.warning("File {0} is too large - not importing".format(filename))
                        os.remove(filename)
                if filename.startswith("."):
                    logger.warning("File {0} starts with a '.' - not importing")
                    os.remove(filename)
            except OSError, e:
                logger.warning("Got OSError treating {0}: {1}".format(filename, e))

    
def svn_find_packages(svnroot, svn_path, pathveto = []):
    '''Recursively list SVN directories, looking for leaf packages, defined by having
    a branches/tags/trunk structure'''
    my_package_list = []
    logger.debug("Searching {0}".format(svn_path))
    cmd = ["svn", "ls", os.path.join(svnroot, svn_path)]
    dir_output = check_output_with_retry(cmd).split("\n")
    if ("trunk/" in dir_output and "tags/" in dir_output): # N.B. some packages lack "branches", though this is a bit non-standard (FastPhysTagMon)
        # We are a leaf!
        logger.info("Found leaf package: {0}".format(svn_path))
        return [svn_path]
    for entry in dir_output:
        if entry.endswith("/") and not entry.rstrip("/") in pathveto and not " " in entry:
            my_package_list.extend(svn_find_packages(svnroot, os.path.join(svn_path, entry)))
    return my_package_list


def svn_get_path_metadata(svnroot, package, package_path, revision=None):
    '''Get SVN metadata and return as a simple dictionary keyed on date, author and commit revision'''
    logger.debug("Querying SVN metadeta for {0}".format(os.path.join(package, package_path)))
    cmd = ["svn", "info", os.path.join(svnroot, package, package_path), "--xml"]
    svn_info = check_output_with_retry(cmd)
    tree = eltree.fromstring(svn_info)
    return {
            "date": tree.find(".//date").text.rsplit(".",1)[0], # Strip off sub-second part
            "author": tree.find(".//author").text,
            "revision": int(tree.find(".//commit").attrib['revision']),
            }


def get_current_git_tags(gitrepo):
    os.chdir(gitrepo)
    cmd = ["git", "tag", "-l"]
    return check_output_with_retry(cmd).split("\n")

def is_trunk_tag(tag):
    return re.match(r'[a-zA-Z]+-\d{2}-\d{2}-\d{2}$', tag)


def main():
    parser = argparse.ArgumentParser(description='SVN to git migrator, ATLAS style')
    parser.add_argument('svnroot', metavar='SVNDIR',
                        help="location of svn repository root")
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="location of git repository")
    parser.add_argument('--svnpath', metavar='PATH', nargs='+', default=[],
                        help="list of paths in the SVN tree to process (use '.' to process entire SVN repo)")
    parser.add_argument('--svnpathveto', metavar='PATH', nargs='+', default=[],
                        help="list of paths in the SVN tree to veto for processing (can refer to a leaf or an intermediate directory name)")
    parser.add_argument('--svnpackage', metavar='PACKAGE', nargs='+', default=[],
                        help="list of package paths in the SVN tree to process")
    parser.add_argument('--svnpackagefile', metavar='FILE', 
                        help="file containing list of package paths in the SVN tree to process - default 'gitrepo.packages'")
    parser.add_argument('--trimtags', metavar='N', type=int, default=0, 
                        help="limit number of tags to import into git (by default import everything)")
    parser.add_argument('--tagtimelimit', metavar='YYYY-MM-DD', default=None, 
                        help="limit tag import to tags newer than time limit")
    parser.add_argument('--skiptagscan', action="store_true", default=False,
                        help="skip scanning SVN for current tags (only tags from SVN cache file are processed)")    
    parser.add_argument('--svncachefile', metavar='FILE',
                        help="file containing cache of SVN information - default 'gitrepo.svn.metadata'")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    # Parse and handle initial arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    # Massage default values
    if not args.svncachefile:
        args.svncachefile = os.path.basename(args.gitrepo) + ".svn.metadata"
    if not args.svnpackagefile:
        args.svnpackagefile = os.path.basename(args.gitrepo) + ".packages"

    # Set svnroot and git repo, get some starting values
    svnroot = args.svnroot
    gitrepo = os.path.abspath(args.gitrepo)
    start_cwd = os.getcwd()
    start_timestamp_string = time.strftime("%Y%m%dT%H%M.%S")
    logger.debug("Set SVN root to {0} and git repo to {1}".format(svnroot, gitrepo))

    if args.tagtimelimit:
        args.tagtimelimit = time.strptime(args.tagtimelimit, "%Y-%m-%d")
        

    ### Main actions start here
    ## SVN interactions and reloading state    
    # Decide which svn packages we will import
    svn_packages = set_svn_packages_from_args(svnroot, args)
    
    # Save package list for the future 
    backup_package_list(svn_packages, start_cwd, args.svnpackagefile, start_timestamp_string)
    
    # Initialise SVN metadata cache
    svn_metadata_cache = initialise_svn_metadata(args.svncachefile)

    # Prepare package import
    if not args.skiptagscan:
        scan_svn_tags_and_get_metadata(svnroot, svn_packages, svn_metadata_cache, args.trimtags, args.tagtimelimit)

    # Now presistify metadata cache
    backup_svn_metadata(svn_metadata_cache, start_cwd, args.svncachefile, start_timestamp_string)
    
    # Setup dictionary for keying by SVN revision number
    svn_cache_revision_dict = svn_cache_revision_dict_init(svn_metadata_cache)
            

    ## git actions
    # Setup the git repository
    init_git(gitrepo)

    # Pull current list of tags here, to fast skip work already done
    current_git_tags = get_current_git_tags(gitrepo)

    # Process each SVN tag in order
    ordered_revisions = svn_cache_revision_dict.keys()
    ordered_revisions.sort()
    for rev in ordered_revisions:
        for pkg_tag in svn_cache_revision_dict[rev]:
            if os.path.join(pkg_tag["package"], pkg_tag["tag"]) in current_git_tags:
                logger.info("Tag {0} exists already - skipping".format(os.path.join(pkg_tag["package"], pkg_tag["tag"])))
                continue
            svn_co_tag_and_commit(svnroot, gitrepo, pkg_tag["package"], pkg_tag["tag"], 
                                  svn_metadata_cache[pkg_tag["package"]][pkg_tag["tag"]])

if __name__ == '__main__':
    main()

