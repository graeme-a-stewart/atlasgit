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
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as eltree

# Setup basic logging
logger = logging.getLogger('as2g')
hdlr = logging.StreamHandler(sys.stdout)
frmt = logging.Formatter("%(name)s.%(funcName)s %(levelname)s %(message)s")
hdlr.setFormatter(frmt)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)

class svnpackagetag(object):
    def __init__(self, package_path, tag):
        self._package_path = os.path.basename(package_path)
        self._package_tag = tag
        
    @property
    def package_path(self):
        return self._package_path

    @property
    def tag(self):
        return self._package_tag

def init_git(gitrepo):
    if not os.path.exists(gitrepo):
        os.makedirs(gitrepo)
    if os.path.exists(os.path.join(gitrepo, ".git")):
        logger.info("Found existing git repo, {0}".format(gitrepo))
    else:
        os.chdir(gitrepo)
        logger.info("Initialising git repo: {0}".format(gitrepo))
        subprocess.check_call(["git", "init"])

def get_all_package_tags(svnroot, package_path, include_trunk=True):
    '''Retrieve all tags for a package in svnroot'''
    cmd = ["svn", "ls", os.path.join(svnroot, package_path, "tags")]
    tag_output = subprocess.check_output(cmd)
    tag_list = [ os.path.join("tags", s.rstrip("/")) for s in tag_output.split() ]
    if include_trunk:
        tag_list.append("trunk")
    return tag_list
    
def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, svn_metadata = None, branch="master"):
    '''Make a temporary space, check out, copy and then git commit'''
    
    # Pre-check if we have this tag already
    os.chdir(gitrepo)
    cmd = ["git", "tag", "-l", tag]
    git_tag_check = subprocess.check_output(cmd)
    if len(git_tag_check) > 0:
        logger.info("Tag {0} exists already - skipping".format(tag))
        return
    
    package = package.rstrip("/") # Trailing / causes shutil.move to add an extra subdir
    logger.info("processing {0} tag {1} to branch {2}".format(package, tag, branch))
    tempdir = tempfile.mkdtemp()
    full_svn_path = os.path.join(tempdir, package)
    cmd = ["svn", "co", os.path.join(svnroot, package, tag), os.path.join(tempdir, package)]
    subprocess.check_call(cmd)

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
    cmd = ["git", "add", "-A"]
    subprocess.check_call(cmd)
    if logger.level <= logging.DEBUG:
        cmd = ["git", "status"]
        subprocess.check_call(cmd)
    cmd = ["git", "commit", "--allow-empty", "-m", "{0} tag {1}".format(package, tag)]
    if svn_metadata:
        cmd.extend(("--author='{0} <{0}@cern.ch>".format(svn_metadata["author"]), 
                    "--date={0}".format(svn_metadata["date"]),
                    "-m", "SVN r{0}".format(svn_metadata['revision'])))
    subprocess.check_call(cmd)
    if tag != "trunk":
        cmd = ["git", "tag", "-a", tag, "-m", ""]
        subprocess.check_call(cmd)
    
    # Clean up
    shutil.rmtree(tempdir)
    
def svn_cleanup(svn_path):
    '''Cleanout files we do not want to import into git'''
    shutil.rmtree(os.path.join(svn_path, ".svn"))
    
    # File size veto
    for root, dirs, files in os.walk(svn_path):
        for name in files:
            filename = os.path.join(root, name)
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

    
def svn_find_packages(svnroot, svn_path, pathveto = []):
    '''Recursively list SVN directories, looking for leaf packages, defined by having
    a branches/tags/trunk structure'''
    my_package_list = []
    logger.debug("Searching {0}".format(svn_path))
    cmd = ["svn", "ls", os.path.join(svnroot, svn_path)]
    dir_output = subprocess.check_output(cmd).split()
    if ("trunk/" in dir_output and "tags/" in dir_output): # N.B. some packages lack "branches", though this is a bit non-standard (FastPhysTagMon)
        # We are a leaf!
        logger.info("Found leaf package: {0}".format(svn_path))
        return [svn_path]
    for entry in dir_output:
        if entry.endswith("/") and not entry.rstrip("/") in pathveto:
            my_package_list.extend(svn_find_packages(svnroot, os.path.join(svn_path, entry)))
    return my_package_list


def svn_get_path_metadata(svnroot, package, package_path, revision=None):
    '''Get SVN metadata and return as a simple dictionary keyed on date, author and commit revision'''
    logger.debug("Querying SVN metadeta for {0}".format(os.path.join(package, package_path)))
    cmd = ["svn", "info", os.path.join(svnroot, package, package_path), "--xml"]
    svn_info = subprocess.check_output(cmd)
    tree = eltree.fromstring(svn_info)
    return {
            "date": tree.find(".//date").text,
            "author": tree.find(".//author").text,
            "revision": int(tree.find(".//commit").attrib['revision']),
            }


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
    parser.add_argument('--svncachefile', metavar='FILE',
                        help="file containing cache of SVN information - default 'gitrepo.svn.metadata'")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    # Massage default values
    if not args.svncachefile:
        args.svncachefile = os.path.basename(args.gitrepo) + ".svn.metadata"
    if not args.svnpackagefile:
        args.svnpackagefile = os.path.basename(args.gitrepo) + ".packages"

    # Set svnroot and git repo
    svnroot = args.svnroot
    gitrepo = args.gitrepo
    start_cwd = os.getcwd()
    logger.debug("Set SVN root to {0} and git repo to {1}".format(svnroot, gitrepo))

    # Decide which svn packages we will import
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
    logger.debug("Packages to import: {0}".format(svn_packages))
    os.chdir(start_cwd)
    with open(os.path.basename(gitrepo) + ".packages", "w") as pkg_dump:
        for package in svn_packages:
            print >>pkg_dump, package
    
    # Setup the git repository
    init_git(gitrepo)

    svn_metadata_cache = {}
    svn_cache_revision_dict = {}

    # Prepare package import
    for package in svn_packages:
        logger.info("Preparing package {0}".format(package))
        tags = get_all_package_tags(svnroot, package)
        # Special strip....
        if args.trimtags:
            tags = tags[-args.trimtags:]
        for tag in tags:
            # Do we have metadata?
            if package not in svn_metadata_cache:
                svn_metadata_cache[package] = {}
            if tag not in svn_metadata_cache[package]:
                svn_metadata_cache[package][tag] = svn_get_path_metadata(svnroot, package, tag)
            if svn_metadata_cache[package][tag]["revision"] in svn_cache_revision_dict:
                logger.error("Found 2 package tags on same SVN revision!")
                sys.exit(1)
            svn_cache_revision_dict[svn_metadata_cache[package][tag]["revision"]] = {"package": package, "tag": tag}
            
    # Now presistify metadata cache
    os.chdir(start_cwd)
    if os.path.exists(args.svncachefile):
        os.rename(args.svncachefile, args.svncachefile + ".bak")
    with file(args.svncachefile, "w") as md_dump:
        json.dump(svn_metadata_cache, md_dump, indent=2)

    # Now process and git commit...
    ordered_revisions = svn_cache_revision_dict.keys()
    ordered_revisions.sort()
    print ordered_revisions
    for rev in ordered_revisions:
        svn_co_tag_and_commit(svnroot, gitrepo, svn_cache_revision_dict[rev]["package"], 
                              svn_cache_revision_dict[rev]["tag"], 
                              svn_metadata_cache[svn_cache_revision_dict[rev]["package"]][svn_cache_revision_dict[rev]["tag"]])

if __name__ == '__main__':
    main()

