#! /usr/bin/env python
#
# Get lists of package tags from CMake built releases and generate tagdiff 
# files from them
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
import os.path 
import sys
import time

from glogger import logger
from atutils import find_best_arch

def find_cmake_releases(install_path, release, nightly=None):
    ## @brief Find the base path and project sub-path for a CMake release
    #  @param install_path Base release area for CMake installed releases
    #  @param release Athena release series + release flavour number (e.g., 21.0)
    #  @param nightly Nightly series to search (otherwise look for installed release)
    #  @return Tuple with full base release path, all matching releases and project sub-path
    base_path = os.path.join(install_path, release)
    if not os.path.isdir(base_path):
        logger.error("Directory {0} is missing - cannot find CMake package data".format(base_path))
        sys.exit(1)
    logger.info("Using base path for release {0} of {1}".format(release, base_path))
    
    sample_project = find_cmake_sample_project(base_path)
    if not sample_project:
        logger.error("Could not find any sample project from {0} - cannot find CMake package data".format(base_path))
        sys.exit(1)
    logger.debug("Found build project {0} to build architecture with".format(sample_project))

    if nightly:
        releases = [ nightly ]
        if not os.path.isdir(os.path.join(os.path.join(base_path, sample_project, nightly))):
            logger.error("Could not find release {0} - "
                         "cannot find CMake package data".format(os.path.join(base_path, sample_project, nightly)))
            sys.exit(1)
    else:
        releases = [ d for d in os.listdir(os.path.join(base_path, sample_project)) 
                    if os.path.isdir(os.path.join(base_path, sample_project, d)) and d.startswith(release) ]    
        if len(releases) == 0:
            logger.error("Could not find any releases in {0} - "
                         "cannot find CMake package data".format(os.path.join(base_path, sample_project)))
            sys.exit(1)
    logger.debug("Found releases: {0}".format(releases))
    
    if os.path.isdir(os.path.join(base_path, sample_project, releases[0], "InstallArea")):
        best_arch = find_best_arch(os.path.join(base_path, sample_project, releases[0], "InstallArea"))
        project_path = os.path.join("InstallArea", best_arch)
    else:
        best_arch = find_best_arch(os.path.join(base_path, sample_project, releases[0]))
        project_path = best_arch
    logger.debug("Using build architecture {0}".format(best_arch))
    
    return base_path, releases, project_path


def find_cmake_sample_project(base_path, release=None):
    ## @brief Test a few possible projects to find one which definitely exists for
    #  this release
    #  @param base_path Base release area for this CMake release series
    #  @param release Specific Athena release number (is missing, generic test is done)
    #  @return Sample project name
    sample_project = None
    for project in ("AtlasCore", "AtlasEvent", "AtlasOffline", "AtlasProduction", "AthSimulationBase", "AthAnalysisBase"):
        if os.path.isdir(os.path.join(base_path, project)):
            if not release:
                sample_project = project
                break
            if os.path.isdir(os.path.join(base_path, project, release)):
                sample_project = project
                break
    return sample_project


def get_cmake_release_data(base_path, base_release, release, project_path, nightly=None):
    logger.debug("Parsing release data for {0} - {1} - {2} - {3} - {4}".format(base_path, base_release, release, project_path, nightly))
    if nightly:
        release_number_elements = base_release.split(".")
    else:
        release_number_elements = release.split(".")
    series = release_number_elements[0]
    flavour = release_number_elements[1]
    major = release_number_elements[2]
    if len(release_number_elements) == 3:
        release_type = "base"
        minor = None
        subminor = None
    elif len(release_number_elements) == 4:
        release_type = "cache"
        minor = release_number_elements[3]
        subminor = None
        
    sample_project = find_cmake_sample_project(base_path, release)
    timestamp = os.stat(os.path.join(base_path, sample_project, release)).st_mtime

    release_desc = {"name": release,
                    "series": series,
                    "flavour": flavour,
                    "major": major,
                    "minor": minor,
                    "subminor": subminor,
                    "type": release_type,
                    "timestamp": timestamp,
                    "nightly": False,
                    "author": "ATLAS Librarian <alibrari@cern.ch>"
                    }
    if nightly:
        release_desc["nightly"] = True
        release_desc["name"] = base_release + "-" + time.strftime("%Y-%m-%d", time.localtime(timestamp)) + "-" + nightly 
    logger.debug(release_desc)
    return release_desc
    

def find_cmake_tags(base_path, release, project_path):
    ## @brief Find the tags that went into a CMake release found
    #  at the path specified
    #  @param base_path Starting base path for the release number and flavour
    #  @param release The Athena release number
    #  @param project_path The path element inside each project where the
    #  project is installed
    release_packages = {}
    project_directories = [ dir for dir in os.listdir(base_path) if dir.startswith("Atlas") or dir == "DetCommon" ]
    for project in project_directories:
        packages_file = os.path.join(base_path, project, release, project_path, "packages.txt")
        if not os.path.exists(packages_file):
            logger.warning("Project packages file {0} doesn't exist - skipping this project".format(packages_file))
            continue
        project_packages = read_project_packages(packages_file, project)
        logger.debug("Found {0} packages for project {1}".format(len(project_packages), project))
        release_packages.update(project_packages)
    logger.info("Found {0} packages in release {1}".format(len(release_packages), release))
    return release_packages


def read_project_packages(packages_file, project = None):
    ## @brief Read CMake made packages file
    #  @param packages_file File containing project package tags
    #  @param project Project name
    packages_dict = {}
    with open(packages_file) as pfile:
        for line in pfile:
            line = line.strip()
            if line.startswith("#") or line == "":
                continue
            try:
                package, package_tag = line.split(" ")
                # These are odd fish, but keep them if they exist...
                if (package == project + "RunTime" or package == project + "Release") and "/" not in package:
                    package = os.path.join("Projects", package)
                packages_dict[package] = {"tag": package_tag, "project": project}
            except ValueError, e:
                logger.warning("Problem splitting line '{0}' into package and package tag".format(line))
    return packages_dict
                

def main():
    parser = argparse.ArgumentParser(description='ATLAS tag munger, calculating tag evolution across '
                                     'a releases series for CMake releases')
    parser.add_argument('release', metavar='RELEASE',
                        help="Release to build tagdiff files from, e.g., 21.0 or 21.0.6 or 21.0.X")
    parser.add_argument('--tagdir', default="tagdir",
                        help="output directory for tag files, each release will generate an entry here")
    parser.add_argument('--installpath',
                        help="path to CMake release installation location (defaults to cvfms path "
                        "/cvmfs/atlas.cern.ch/repo/sw/software for releases, "
                        "/afs/cern.ch/atlas/software/builds/nightlies for nightlies)")
    parser.add_argument('--nightly', help="Generate tag file for the named nightly build in the nightly "
                        "release series")
    parser.add_argument('--overwrite', action="store_true", default=False,
                        help="Overwrite any exisitng configuration files (otherwise, just skip over)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    if not args.installpath:
        if args.nightly:
            args.installpath = "/afs/cern.ch/atlas/software/builds/nightlies"
        else:
            args.installpath = "/cvmfs/atlas.cern.ch/repo/sw/software"
            
    if not os.path.exists(args.tagdir):
        try:
            os.makedirs(args.tagdir)
        except OSError, e:
            logger.error("Failed to make directory {0}: {1}".format(args.tagdir, e))
            sys.exit(1)
    
    base_path, releases, project_path = find_cmake_releases(args.installpath, args.release, nightly=args.nightly)
    for release in releases:
        release_description = get_cmake_release_data(base_path, args.release, release, project_path, nightly=args.nightly)
        logger.debug("Release {0} parsed as {1}/PROJECT/{2}".format(base_path, release, project_path))
        release_tags = find_cmake_tags(base_path, release, project_path)
        output_file = os.path.join(args.tagdir, release_description["name"])
        if args.overwrite or not os.path.exists(output_file):
            with open(os.path.join(args.tagdir, release_description["name"]), "w") as tag_output:
                my_release_data = {"release": release_description, "tags": release_tags}
                json.dump(my_release_data, tag_output, indent=2)
                logger.info("Wrote {0}".format(output_file))
        else:
            logger.info("Skipped writing to {0} - overwrite is false".format(output_file))

if __name__ == '__main__':
    main()
    