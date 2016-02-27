#! /usr/bin/env python
#
# Trivially convert JSON timing list into text file for a spreadsheet
#

import json
import sys

with open(sys.argv[1]) as json_input:
    timings=json.load(json_input)

with open(sys.argv[2], "w") as text_output:
    for t in timings:
        print >>text_output, t
