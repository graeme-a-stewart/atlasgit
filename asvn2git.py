#! /usr/bin/env python
#
# Prototype migration script from atlasoff to git,
# moving sets of package tags identified with releases
# to branches, and making tags for identified release
# builds
#

import argparse
import logging
import os
import os.path
import shutil
import subprocess
import sys
import tempfile

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

def get_all_package_tags(svnroot, package_path):
    '''Retrieve all tags for a package in svnroot'''
    cmd = ["svn", "ls", os.path.join(svnroot, package_path, "tags")]
    tag_output = subprocess.check_output(cmd)
    tag_list = [ s.rstrip("/") for s in tag_output.split() ]
    return tag_list
    
def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, branch="master"):
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
    msg = "Git commit of {0} tag {1} to branch {2}".format(package, tag, branch)
    cmd = ["git", "commit", "-m", msg, "--allow-empty"]
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
        logger.debug("Found leaf package: {0}".format(svn_path))
        return [svn_path]
    for entry in dir_output:
        if entry.endswith("/") and not entry.rstrip("/") in pathveto:
            my_package_list.extend(svn_find_packages(svnroot, os.path.join(svn_path, entry)))
    return my_package_list

def main():
    parser = argparse.ArgumentParser(description='SVN to git migrator, ATLAS style')
    parser.add_argument('svnroot', metavar='SVNDIR',
                        help="location of svn repository root")
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="location of git repository")
    parser.add_argument('--svnpaths', metavar='PATH', nargs='+', default=[],
                        help="list of paths in the SVN tree to process (default, process only explicit packages (if given), otherwise process everything)")
    parser.add_argument('--svnpathveto', metavar='PATH', nargs='+', default=[],
                        help="list of paths in the SVN tree to veto for processing (can refer to a leaf or an intermediate directory name)")
    parser.add_argument('--svnpackages', metavar='PACKAGE', nargs='+', default=[],
                        help="list of package paths in the SVN tree to process")
    parser.add_argument('--svnpackagesfile', metavar='FILE', 
                        help="file containing list of package paths in the SVN tree to process")
    parser.add_argument('--trimtags', metavar='N', type=int, default=0, 
                        help="limit number of tags to import into git (by default import everything)")    
    parser.add_argument('--svncachefile', metavar='FILE',
                        help="file containing cache of SVN information (optional) TODO")
    parser.add_argument('--svnsavecachefile', metavar='FILE',
                        help="file to save cache of SVN information to (saves a lot of SVN interaction time) [TODO]")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    if args.svnpackages == [] and args.svnpaths == [] and args.svnpackagesfile == None:
        args.svnpaths = ["."]

    # Set svnroot and git repo
    svnroot = args.svnroot
    gitrepo = args.gitrepo
    logger.debug("Set SVN root to {0} and git repo to {1}".format(svnroot, gitrepo))

    # Decide which svn packages we will import
    svn_packages = args.svnpackages
    if args.svnpackagesfile:
        logger.info("Reading packages to import from {0}".format(args.svnpackagesfile))
        with open(args.svnpackagesfile) as pkg_file:
            for package in pkg_file:
                package = package.strip()
                if package.startswith("#") or package == "":
                    continue
                svn_packages.append(package)
    for path_element in args.svnpaths:
        svn_packages.extend(svn_find_packages(svnroot, path_element, args.svnpathveto))
    logger.debug("Packages to import: {0}".format(svn_packages))
    with open(os.path.basename(gitrepo) + ".packages", "w") as pkg_dump:
        for package in svn_packages:
            print >>pkg_dump, package
    
    # Setup the git repository
    init_git(gitrepo)

    # Import packages
    for package in svn_packages:
        logger.info("Importing package {0}".format(package))
        tags = get_all_package_tags(svnroot, package)
        # Special strip....
        if args.trimtags:
            tags = tags[-args.trimtags:]
        for tag in tags:
            svn_co_tag_and_commit(svnroot, gitrepo, package, os.path.join("tags", tag))
        svn_co_tag_and_commit(svnroot, gitrepo, package, "trunk")

if __name__ == '__main__':
    main()

