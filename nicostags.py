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

import argparse
import datetime
import json
import logging
import os
import os.path
import re
import sys
import time

from glogger import logger
from atutils import find_best_arch, release_compare


def get_release_name(release_file_path):
    ## @brief a NICOS tag file to get tags and projects for this build.
    #  @param release_file_path Path to file with NICOS tags for the release of interest
    #  @return Tuple of release name, plus boolen if the release is a nightly 
    #  (thus @c False for a numbered release)
    with open(release_file_path) as release_file:
        for line in release_file:
            if line.startswith("#release"):
                # This is a numbered release_file_path
                release_match = re.match(r"#release\s([\d\.]+)", line)
                if release_match:
                    return release_match.group(1), False
            elif line.startswith("#tags for"):
                # This is a nightly
                release_match = re.match(r"#tags for\s([\d\.]+)", line)
                if release_match:
                    return release_match.group(1), True
        logger.error("Failed to parse release_file_path name from tag file {0}".format(release_file_path))
        raise RuntimeError("Failed to find release name")


def parse_release_data(release_file_path, name_prefix=None):
    ## @brief Parse release data from the NICOS tag file
    #  @param release_file_path Path to file with NICOS tags for the release of interest
    #  @return Dictionary of values for the different release properties
    timestamp = os.stat(release_file_path).st_mtime
    release_name, nightly_flag = get_release_name(release_file_path)
    if name_prefix:
        full_name = name_prefix + "-" + release_name
    else:
        full_name = release_name
    release_elements = release_name.split(".")
    if len(release_elements) < 3:
        raise RuntimeError("Weird release: {0}".format(release_name))
    if len(release_elements) == 3:
        rel_type = "base"
        minor = None
        subminor = None
        cache_number = 0
    elif len(release_elements) == 4:
        rel_type = "cache"
        minor = release_elements[3]
        subminor = None
    major = release_elements[0]
    minor = release_elements[1]
    patch = release_elements[2]
    release_desc = {"name": full_name,
                    "series": release_elements[0],
                    "flavour": release_elements[1],
                    "major": release_elements[2],
                    "minor": minor,
                    "subminor": subminor,
                    "type": rel_type,
                    "timestamp": timestamp,
                    "nightly": nightly_flag,
                    "author": "ATLAS Librarian <alibrari@cern.ch>"
                    }
    if nightly_flag:
        release_desc["name"] += "-{0}".format(time.strftime("%Y-%m-%d", time.localtime(timestamp)))
    logger.debug(release_desc)
    return release_desc


def parse_tag_file(release_file_path, analysis_filter=False):
    ## @brief Open a NICOS tag file and extract the package tags
    #  @param release_file_path Path to file with NICOS tags for the release of interest
    #  @param analysis_filter Apply a filter to take only packages that are in the analysis
    #         release, but are missing from Athena releases
    #  @return Dictionary keyed by package, with each value a dictionary with @c tag and @project
    #  information for the package
    analysis_packages = ["AsgExternal/Asg_Test",
                         #"PhysicsAnalysis/AnalysisCommon/AssociationUtils",    # Have to remove this for now because of the name clash with PhysicsAnalysis/AssociationBuilder/AssociationUtils
                         "PhysicsAnalysis/AnalysisCommon/CPAnalysisExamples",
                         "PhysicsAnalysis/AnalysisCommon/PMGTools",
                         "PhysicsAnalysis/D3PDTools/EventLoop",
                         "PhysicsAnalysis/D3PDTools/EventLoopAlgs",
                         "PhysicsAnalysis/D3PDTools/EventLoopGrid",
                         "PhysicsAnalysis/D3PDTools/MultiDraw",
                         "PhysicsAnalysis/D3PDTools/SampleHandler",
                         "PhysicsAnalysis/ElectronPhotonID/PhotonEfficiencyCorrection",
                         "PhysicsAnalysis/ElectronPhotonID/PhotonVertexSelection",
                         "PhysicsAnalysis/HiggsPhys/Run2/HZZ/Tools/ZMassConstraint",
                         "PhysicsAnalysis/Interfaces/AsgAnalysisInterfaces",
                         "PhysicsAnalysis/JetPhys/SemileptonicCorr",
                         "PhysicsAnalysis/SUSYPhys/SUSYTools",
                         "PhysicsAnalysis/TauID/DiTauMassTools",
                         "PhysicsAnalysis/TauID/TauCorrUncert",
                         "PhysicsAnalysis/TopPhys/QuickAna",
                         "PhysicsAnalysis/TrackingID/InDetTrackSystematicsTools",
                         "Reconstruction/Jet/JetAnalysisTools/JetTileCorrection",
                         "Reconstruction/Jet/JetJvtEfficiency",
                         "Reconstruction/Jet/JetReclustering",
                         "Trigger/TrigAnalysis/TrigMuonEfficiency",
                         "Trigger/TrigAnalysis/TrigTauAnalysis/TrigTauMatching",
                         ]
    release_package_dict = {}
    with open(release_file_path) as tag_file:
        for line in tag_file:
            line = line.strip()
            logger.debug(line)
            if len(line) == 0 or line.startswith("#"):
                continue
            try:
                (package, tag, project) = line.split(" ")
            except ValueError:
                continue
            # Gaudi packages live in a separate project, so don't add them
            if project == "GAUDI":
                continue
            # "Release" and "RunTime" packages live inside the Release path, but in fact
            # we ignore them for git . Except for TriggerRelease, which is a real package!
            if package != "Trigger/TriggerRelease" and (package.endswith("Release") or package.endswith("RunTime")):
                logger.debug("Vetoing package auto-generated package {0}".format(package))
                continue
            if package in ["AtlasEvent", "AtlasAnalysis", "AtlasCore", "AtlasTrigger", "AtlasProduction",
                           "AtlasOffline", "DetCommon", "AtlasReconstruction", "AtlasConditions",
                           "AtlasExternals", "AtlasSimulation", "AtlasHLT"]:
                logger.debug("Vetoing fake 'project' package {0}".format(package))
                continue
            # Fake packages made by tag collector
            if "/" not in package and "22-00-00" in tag:
                continue
            logger.debug("Found package {0}, tag {1} in project {2}".format(package, tag, project))
            if analysis_filter and package not in analysis_packages:
                continue
            release_package_dict[package] = {"svn_tag": tag, 
                                             "project": project, "package_name": os.path.basename(package)}
    return release_package_dict



def find_best_tagfile(arch_path):
    ## @brief Find the newest tag file when various NICOS tag files are available
    #  for a particular release
    #  @param arch_path Directory path to NICOS tag files
    #  @return Chosen tag file
    tag_files = os.listdir(arch_path)
    tag_files.sort()
    if len(tag_files) == 0:
        raise RuntimeError("No tags files found in {0}".format(arch_path))
    logger.debug("Best tagfile for {0} is {1} (chosen from {2})".format(arch_path, tag_files[-1], len(tag_files)))
    return(tag_files[-1])


def get_tag_file(base_path):
    ## @brief Walk down the NICOS path, finding the "best" tag file to take
    #  which means the highest gcc version, the opt build and the youngest tag file)
    #  @param base_path Directory base with architecture subdirectories containing tag files
    best_arch = find_best_arch(base_path)
    best_tag_file = find_best_tagfile(os.path.join(base_path, best_arch))
    return (os.path.join(base_path, best_arch, best_tag_file))


def find_nicos_from_base(nicos_path, base_release):
    ## @brief Find base release and cache release tag files when only a base release number
    #  is given
    #  @param nicos_path Base path to NICOS tag file area
    #  @param base_release Base release number A.B or A.B.X (e.g., 21.0[.1])
    #  @return list of matching tag files, in release numbered order
    release_list = []
    dir_list = os.listdir(nicos_path)
    release_match = "{0}(\.(\d+))*$".format(os.path.basename(base_release).replace(".", r"\."))
    logger.debug("Matching releases against pattern '{0}'".format(release_match))
    for entry in dir_list:
        if re.match(release_match, entry):
            release_list.append(entry)
    logger.debug("Matching releases: {0}".format(release_list))
    # It's not actually necessary to sort the releases, but it does no harm
    release_list.sort(cmp=release_compare)
    logger.info("Found ordered list of production caches: {0}".format(release_list))

    tag_files = []
    for release in release_list:
        tag_files.append(get_tag_file(os.path.join(nicos_path, release)))

    return tag_files


def main():
    parser = argparse.ArgumentParser(description='ATLAS tag munger, calculating tag evolution across a releases series')
    parser.add_argument('release', metavar='RELEASE', nargs="+",
                        help="Files containing tag lists (NICOS format). If a release series/major is given (e.g., 20.1 or 20.1.5) "
                        "the script will search for the base release and all caches to build the tag files in "
                        "a simple way, without worrying about the details of the NICOS tag files and paths (N.B. "
                        "in the rare cases when there is more than one tag file for a release, the last one will "
                        "be used).")
    parser.add_argument('--tagdir', default="tagdir",
                        help="output directory for tag files, each release will generate an entry here (default \"tagdir\")")
    parser.add_argument('--prefix',
                        help="Prefix for the name of the release, when the NICOS information is insufficient")
    parser.add_argument('--nicospath', default="/afs/cern.ch/atlas/software/dist/nightlies/nicos_work/tags/",
                        help="path to NICOS tag files (defaults to usual CERN AFS location)")
    parser.add_argument('--analysispkgfilter', action="store_true",
                        help="Special post processing for the (Ath)AnalysisBase-2.6.X release series, which "
                        "filters tags to be only those which are missing from standard Athena releases")
    parser.add_argument('--overwrite', action="store_true", default=False,
                        help="Overwrite any exisitng configuration files (otherwise, just skip over)")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="switch logging into DEBUG mode")

    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Case when a single bese release is given - we have to expand this
    if len(args.release) == 1 and re.match(r"(\d+)\.(\d+)(\.(\d+))?$", args.release[0]):
        nicos_paths = find_nicos_from_base(args.nicospath, args.release[0])
    else:
        nicos_paths = []
        for path in args.release:
            if os.path.exists(path):
                nicos_paths.append(path)
            elif os.path.exists(os.path.join(args.nicospath, path)):
                nicos_paths.append(os.path.join(args.nicospath, path))
            else:
                logger.error("Path {0} doesn't exist (even after prepending NICOS path)".format(path))
                sys.exit(1)
    
    for release in nicos_paths:
        release_description = parse_release_data(release, args.prefix)
        release_tags = parse_tag_file(release, args.analysispkgfilter)
        logger.info("Processing tags for release {0}".format(release_description["name"]))
        output_file = os.path.join(args.tagdir, release_description["name"])
        if args.overwrite or not os.path.exists(output_file):
            with open(os.path.join(args.tagdir, release_description["name"]), "w") as tag_output:
                json.dump({"release": release_description, "tags": release_tags}, tag_output, indent=2)
        else:
            logger.debug("Skipped writing to {0} - overwrite is false".format(output_file))



if __name__ == '__main__':
    main()
