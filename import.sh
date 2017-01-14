#! /bin/sh
#
# Top to bottom import of ATLAS SVN to git

gitrepo=${1:-aogt}

# Get package tags
for r in 20.8 21.0; do
    cmaketags.py $r
done
for r in 19.2 20.1 20.7 20.8 20.11; do
    cmttags.py $r
done
rm tagdir/21.0.56  # What was that?

# Copy definitive author list...
cp ~/bin/$gitrepo.author.metadata .

# Import all tags
(time asvn2git.py file:///data/graemes/atlasoff/ao-mirror $gitrepo $(ls -v tagdir/* | perl -ne 'print if /\/\d+\.\d+\.\d+$/') --licensefile ~/bin/apache2.txt) |& tee o.agot.a2s

# Build master branch
(time branchbuilder.py $gitrepo master $(ls -v tagdir/* | perl -ne 'print if /\/\d+\.\d+\.\d+$/') --skipreleasetag --onlyforward) |& tee o.$gitrepo.master

# Build release branches
for r in 19.2 20.1 20.7 20.8 21.0; do
    (time branchbuilder.py $gitrepo $r $(ls -v tagdir/$r.* | perl -ne 'print if /\/\d+\.\d+\.\d+$/') --parentbranch master:@$(pwd)/tagdir/$r.0 ) |& tee o.$gitrepo.bb.$r
done
# HLT branch was made from 20.7, not dev
(time branchbuilder.py $gitrepo 20.11 $(ls -v tagdir/20.11.?) --parentbranch 20.7:@$(pwd)/tagdir/20.11.0 ) |& tee o.$gitrepo.bb.20.11


# Update for master:
# cmaketags.py --nightly rel_1 22.0.X
# asvn2git.py file:///atlas/scratch0/graemes/ao-mirror aogt tagdir/22.0.X-2017-01-08-rel_1 --licensefile ~/bin/apache2.txt --uncrustify ~/bin/uncrustify-import.cfg
# 
