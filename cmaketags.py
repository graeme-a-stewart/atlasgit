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
from atutils import find_best_arch, diff_release_tags

def find_cmake_release(install_path, release, nightly=None):
    ## @brief Find the base path and project sub-path for a CMake release
    #  @param install_path Base release area for CMake installed releases
    #  @param release Athena release number
    #  @param nightly Nightly series to search (otherwise look for installed release)
    #  @return Tuple with full base release path and project sub-path
    if nightly:
        base_path = os.path.join(install_path, nightly)
    else:
        release_number_elements = release.split(".")
        base_path = os.path.join(install_path, "{0}.{1}".format(release_number_elements[0], release_number_elements[1]))
    if not os.path.isdir(base_path):
        logger.error("Directory {0} is missing - cannot find CMake package data".format(base_path))
        sys.exit(1)
    logger.info("Using base path for release {0} of {1}".format(release, base_path))
        
    sample_project = find_cmake_sample_project(base_path, release)
    if not sample_project:
        logger.error("Could not find any sample project from {0} - cannot find CMake package data".format(base_path))
        sys.exit(1)
    logger.debug("Found build project {0} to build architecture with".format(sample_project))
    
    if os.path.isdir(os.path.join(base_path, sample_project, release, "InstallArea")):
        use_install_area = True
        best_arch = find_best_arch(os.path.join(base_path, sample_project, release, "InstallArea"))
        project_path = os.path.join("InstallArea", best_arch)
    else:
        use_install_area = False
        best_arch = find_best_arch(os.path.join(base_path, sample_project, release))
        project_path = best_arch
    logger.debug("Using build architecture {0}".format(best_arch))
    
    return base_path, project_path


def find_cmake_sample_project(base_path, release):
    ## @brief Test a few possible projects to find one which definitely exists for
    #  this release
    #  @param base_path Base release area this CMake release series
    #  @param release Athena release number
    #  @return Sample project name
    sample_project = None
    for project in ("AtlasCore", "AtlasEvent", "AtlasOffline", "AtlasProduction", "AthSimulationBase", "AthAnalysisBase"):
        if os.path.isdir(os.path.join(base_path, project, release)):
            sample_project = project
            break
    return sample_project


def get_cmake_release_data(base_path, release, project_path, nightly=None):
    if nightly:
        release_number_elements = nightly.split(".")
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
                    "major": series,
                    "minor": flavour,
                    "patch": major,
                    "cache": minor,
                    "subminor": subminor,
                    "type": release_type,
                    "timestamp": timestamp,
                    "nightly": False,
                    "author": "ATLAS Librarian <alibrari@cern.ch>"
                    }
    if nightly:
        release_desc["nightly"] = True
        release_desc["name"] = "{0}_{1}-{2}".format(nightly, release, time.strftime("%Y-%m-%dT%H%M", time.localtime(timestamp)))
    logger.debug(release_desc)
    return release_desc
    

def find_cmake_tags(base_path, release, project_path):
    ## @brief Find the tags that went into a CMake release foound
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
    parser.add_argument('release', metavar='RELEASE', nargs="+",
                        help="Releases to build tagdiff files from, e.g., 21.0.1")
    parser.add_argument('--tagdiff',
                        help="output file for tag evolution between releases (defaults to A.B.X.tagdiff only for single "
                        "base release use case - otherwise must be specified using this option)")
    parser.add_argument('--installpath',
                        help="path to CMake release installation location (defaults to cvfms path "
                        "/cvmfs/atlas.cern.ch/repo/sw/software for releases, "
                        "/afs/cern.ch/atlas/software/builds/nightlies for nightlies)")
    parser.add_argument('--nightly', help="Generate tag diff for nightly build series (e.g., 21.0.X) "
                        "instead of a deployed release (in this case 'release' should be, e.g., rel_4)")    
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
    
    tags_by_release = {}
    ordered_releases = []

    for release in args.release:
        base_path, project_path = find_cmake_release(args.installpath, release, nightly=args.nightly)
        release_description = get_cmake_release_data(base_path, release, project_path, nightly=args.nightly)
        logger.debug("Release {0} parsed as {1}/PROJECT/{2}".format(base_path, release, project_path))
        release_tags = find_cmake_tags(base_path, release, project_path)
        tags_by_release[release_description["name"]] = {"release": release_description,
                                                        "tags": release_tags}
        ordered_releases.append(release_description["name"])
    
    if tags_by_release[ordered_releases[0]]["release"]["type"] == "base":
        if args.tagdiff == None:
            tdfile = tags_by_release[ordered_releases[0]]["release"]["name"] + ".tagdiff"
        else:
            tdfile = args.tagdiff 
    else:
        logger.error("First release must be a base release")
        sys.exit(1)
        
    with open(tdfile, "w") as td_output:
        last_base_release = ordered_releases[0]
        last_cache_release = None

        diff = diff_release_tags(None, tags_by_release[last_base_release])
        release_diff_list = [{"release": last_base_release,
                              "meta": tags_by_release[last_base_release]["release"],
                              "diff": diff}]
        
        for release in ordered_releases[1:]:
            if tags_by_release[release]["release"]["type"] == "base":
                diff = diff_release_tags(tags_by_release[last_base_release], tags_by_release[release], allow_removal=True)
                last_base_release = release
                last_cache_release = None
            else:
                diff = diff_release_tags(tags_by_release[last_base_release], tags_by_release[release], allow_removal=False)
                last_cache_release = release
            release_diff_list.append({"release": release,
                                      "meta": tags_by_release[release]["release"],
                                      "diff": diff})
        json.dump(release_diff_list, td_output, indent=2)

if __name__ == '__main__':
    main()
    