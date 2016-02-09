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
    os.chdir(gitrepo)
    subprocess.check_call(["git", "init"])

def find_packages(svnroot, svnsubdirs):
    '''This will only work with a filesystem copy - not too useful'''
    package_paths = []
    for svnsubdir in svnsubdirs:
        for root, dirs, files in os.walk(os.path.join(svnroot, svnsubdir)):
            if "trunk" in dirs:
                package_paths.append(root.replace(svnroot + os.sep, ""))
    return package_paths

def get_svn_metadata(svnroot, package_path, tag):
    '''Get all SVN metadata for a tag commit, to reconstruct in a git commit'''
    pass 

def get_all_package_tags(svnroot, package_path):
    '''Retrieve all tags for a package in svnroot'''
    cmd = ["svn", "ls", os.path.join(svnroot, package_path, "tags")]
    tag_output = subprocess.check_output(cmd)
    tag_list = [ s.rstrip("/") for s in tag_output.split() ]
    return tag_list
    
def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, branch="master"):
    '''Make a temporary space, check out, copy and then git commit'''
    
    package.rstrip("/")
    print "processing {0} tag {1} to {2} branch {3}".format(package, tag, gitrepo, branch)
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
    print "Moving {0} to {1}".format(full_svn_path, package_root)
    shutil.move(full_svn_path, package_root)
    
    # Commit
    os.chdir(gitrepo)
    cmd = ["git", "add", "."]
    subprocess.check_call(cmd)
    msg = "Git commit of {0} tag {1} to branch {2}".format(package, tag, branch)
    cmd = ["git", "commit", "-m", msg, "--allow-empty"]
    subprocess.check_call(cmd)
    
    # Clean up
    shutil.rmtree(tempdir)
    
def svn_cleanup(svn_path):
    '''Cleanout files we do not want to import into git'''
    shutil.rmtree(os.path.join(svn_path, ".svn"))
    # File size veto - TODO
    
    
def svn_find_packages(svnroot, svn_path):
    '''Recursively list SVN directories, looking for leaf packages, defined by having
    a branches/tags/trunk structure'''
    my_package_list = []
    cmd = ["svn", "ls", os.path.join(svnroot, svn_path)]
    print cmd
    dir_output = subprocess.check_output(cmd).split()
    if ("trunk/" in dir_output and "tags/" in dir_output and "branches/" in dir_output):
        # We are a leaf!
        return [svn_path]
    for entry in dir_output:
        if entry.endswith('/'):
            my_package_list.extend(svn_find_packages(svnroot, os.path.join(svn_path, entry)))
    return my_package_list

def main():
    parser = argparse.ArgumentParser(description='SVN to git migrator')
    parser.add_argument('svnroot', metavar='SVNDIR',
                        help="location of svn repository root")
    parser.add_argument('gitrepo', metavar='GITDIR',
                        help="location of git repository")
    parser.add_argument('--svnsubdirs', metavar='DIR', nargs='+', default=[],
                        help="list of subdirectories in the SVN tree to process (default, process only explicit packages)")
    parser.add_argument('--svnpackages', metavar='PACKAGE', nargs='+', default=[],
                        help="list of package paths in the SVN tree to process")
    parser.add_argument('--trimtags', metavar='N', type=int, default=0, 
                        help="limit number of tags to import into git (by default import everything)")    
    parser.add_argument('--svncachefile', metavar='FILE',
                        help="file containing cache of SVN information (optional) TODO")
    parser.add_argument('--svnsavecachefile', metavar='FILE',
                        help="file to save cache of SVN information to (saves a lot of SVN interaction time) [TODO]")

    args = parser.parse_args()

    # Set svnroot and git repo
    svnroot = args.svnroot
    gitrepo = args.gitrepo 

    # Decide which svn packages we will import
    svn_packages = args.svnpackages
    for subdir in args.svnsubdirs:
        svn_packages.extend(svn_find_packages(svnroot, subdir))
    print svn_packages
    
    # First setup the git repository
    init_git(gitrepo)

    # Import packages
    for package in svn_packages:
        tags = get_all_package_tags(svnroot, package)
        # Special strip....
        if args.trimtags:
            tags = tags[-args.trimtags:]
        print tags
        for tag in tags:
            svn_co_tag_and_commit(svnroot, gitrepo, package, os.path.join("tags", tag))
        svn_co_tag_and_commit(svnroot, gitrepo, package, "trunk")

if __name__ == '__main__':
    main()

