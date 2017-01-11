#! /bin/sh
#
# Top to bottom import of ATLAS SVN to git

# Get package tags
for r in 20.8 21.0; do
    cmaketags.py $r
done
for r in 19.2 20.1 20.7 20.8; do
    cmttags.py $r
done

# Import all tags
(time asvn2git.py file:///atlas/scratch0/graemes/ao-mirror aogt tagdir/* --licensefile ~/bin/apache2.txt --uncrustify ~/bin/uncrustify-import.cfg) |& tee o.agot.a2s

# Build master branch
(time branchbuilder.py aogt master $(ls -v tagdir/19.2.? tagdir/20.1.? tagdir/20.11.? tagdir/20.7.? tagdir/20.8.? tagdir/21.0.*) --skipreleasetag --onlyforward) |& tee o.aogt.master

# Build release branches
for r in 19.2 20.1 20.7 20.8 21.0; do
    (time branchbuilder.py aogt $r $(ls -v tagdir/$r.?) --parentbranch master:@$(pwd)/tagdir/$r.0 ) |& tee o.aogt.bb.$r
done
# HLT branch was made from 20.7, not dev
(time branchbuilder.py aogt 20.11 $(ls -v tagdir/20.11.?) --parentbranch 20.7:@$(pwd)/tagdir/20.11.0 ) |& tee o.aogt.bb.20.11


# Update for master:
# cmaketags.py --nightly rel_1 22.0.X
# asvn2git.py file:///atlas/scratch0/graemes/ao-mirror aogt tagdir/22.0.X-2017-01-08-rel_1 --licensefile ~/bin/apache2.txt --uncrustify ~/bin/uncrustify-import.cfg
# 
