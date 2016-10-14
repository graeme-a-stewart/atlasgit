#! /usr/bin/env python
#
## Process release data to produce a plot showing when easy
#  numbered release was cut
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
    max = min = -1.0
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
        by_series[s]["x"].append(mini_dict["timestamp"])
        by_series[s]["y"].append(float(mini_dict["series"]))
        by_series[s]["name"].append(".".join(mini_dict["name"].split(".")[2:]))
        if max < 0.0 or mini_dict["timestamp"] > max:
            max = mini_dict["timestamp"] 
        if min < 0.0 or mini_dict["timestamp"] < min:
            min = mini_dict["timestamp"]

    if args.text:
        for r in summary:
            print r
            
    # Now arrange by release...
    for series, data in by_series.iteritems():
        print data
        plt.plot(data["x"], data["y"], 'ro')
        plt.text(data['x'][0]-2000000, data['y'][0]+0.1, series)
        for x, y, n in zip(data['x'], data['y'], data['name']):
            plt.text(x, y+0.1, "."+n)
    plt.xlim((min-860000, max+860000))
    plt.show()

if __name__ == '__main__':
    main()
