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

## Process release data to produce a plot showing when easy
#  numbered release was cut

import argparse
import datetime
import json

import matplotlib.pyplot as plt
import numpy as np

from glogger import logger

def main():
    parser = argparse.ArgumentParser(description='Plotter for release dates')
    parser.add_argument('tagfiles', nargs="+", metavar='TAGFILE',
                        help="List of release tag content files to add to the plot")
    parser.add_argument('--text', action='store_true', help="Output text summary of release dates")
    parser.add_argument('--debug', '--verbose', "-v", action="store_true",
                        help="Switch logging into DEBUG mode")

    # Parse and handle arguments
    args = parser.parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    summary = []
    by_series = {}
    for release in args.tagfiles:
        with open(release) as release_fh:
            release_data = json.load(release_fh)
        mini_dict = {"series": "{0}.{1}".format(release_data["release"]["series"], release_data["release"]["flavour"]), 
                     "name": release_data["release"]["name"], "timestamp": release_data["release"]["timestamp"], 
                     "date": datetime.date.fromtimestamp(release_data["release"]["timestamp"])}
        summary.append(mini_dict)
        s = mini_dict["series"]
        if s not in by_series:
            by_series[s] = {"x": [], "y": [], "name": []}
        by_series[s]["x"].append(datetime.date.fromtimestamp(mini_dict["timestamp"]))
        by_series[s]["y"].append(float(mini_dict["series"]))
        by_series[s]["name"].append(".".join(mini_dict["name"].split(".")[2:]))

    if args.text:
        for r in summary:
            print r
            
    # Now arrange by release...
    for series, data in by_series.iteritems():
        print data
        plt.plot(data["x"], data["y"], "ro")
        plt.text(data["x"][0]-datetime.timedelta(21), data["y"][0]+0.1, series)
        for x, y, n in zip(data["x"], data["y"], data["name"]):
            plt.text(x, y+0.1, "."+n)
    plt.xlabel("Date")
    plt.ylabel("Release Series")
    plt.title("Base Release Build Dates")
    plt.show()

if __name__ == '__main__':
    main()
