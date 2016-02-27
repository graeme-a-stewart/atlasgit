#! /bin/sh
#
# Dumb helper script that writes that tag diff file from the NICOS tags
# for a base release and all of it's caches.
# Needs AFS access.
#
# Usage: get_prod_tags.sh 20.1.0
#
base=$1
nicos=/afs/cern.ch/atlas/software/dist/nightlies/nicos_work/tags

~/bin/atlastags.py $nicos/$base/x86_64-slc6-gcc4?-opt/tags* $nicos/$base.[0-9]/x86_64-slc6-gcc4?-opt/tags* $nicos/$base.[0-9][0-9]/x86_64-slc6-gcc4?-opt/tags* --tagEvolutionFile=$base.tagdiff
