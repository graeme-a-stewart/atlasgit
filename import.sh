#! /bin/sh
#
# Top to bottom import of ATLAS SVN to git

gitrepo=${1:-athena-import}

(
# Get package tags
for r in 20.8 21.0; do
    cmaketags.py $r
done
for r in 19.2 20.1 20.7 20.8 20.11 20.20; do
    nicostags.py $r
done
rm tagdir/20.1.56  # What was that?

# Oddly, NICOS does not know about all of the P1HLT caches for 2016
for r in $(seq 1 26); do
cmttags.py --overwrite /afs/cern.ch/atlas/software/releases/20.11.0/AtlasP1HLT/20.11.0.${r}/AtlasP1HLTRelease/cmt/requirements
done
for r in $(seq 1 10); do
cmttags.py /afs/cern.ch/atlas/software/releases/20.11.1/AtlasP1HLT/20.11.1.${r}/AtlasP1HLTRelease/cmt/requirements
done
for r in $(seq 1 6); do
cmttags.py /afs/cern.ch/atlas/software/releases/20.11.2/AtlasP1HLT/20.11.2.${r}/AtlasP1HLTRelease/cmt/requirements
done

# Now we select a few nightlies that are used for the last stages
# of building the master branch with r22 tags and some tags
# from AnalysisBase and AthAnalysisBase
for r22 in tags_2017_01_01_H3 tags_2017_01_10_H22 tags_2017_01_20_H3 tags_2017_01_27_H3 tags_2017_02_02_H3 tags_2017_02_06_H3 tags_2017_02_15_H3 tags_2017_02_21_H3 tags_2017_02_22_H3; do 
	nicostags.py /afs/cern.ch/atlas/software/dist/nightlies/nicos_work/tags/22.0.X/x86_64-slc6-gcc49-opt/$r22
done

for aab in tags_2017_01_01_H21 tags_2017_01_10_H21 tags_2017_01_19_H21 tags_2017_01_26_H21 tags_2017_02_01_H21 tags_2017_02_05_H21 tags_2017_02_14_H21 tags_2017_02_20_H21 tags_2017_02_21_H21; do
nicostags.py --prefix AthAnalysisBase --analysispkgfilter /afs/cern.ch/atlas/software/dist/nightlies/nicos_work/tags/AthAnalysisBase-2.6.X/x86_64-slc6-gcc49-opt/$aab 
done

for ab in tags_2017_01_01_H3 tags_2017_01_11_H3 tags_2017_01_20_H3 tags_2017_01_27_H3 tags_2017_02_02_H3 tags_2017_02_06_H3 tags_2017_02_15_H3 tags_2017_02_21_H3 tags_2017_02_22_H3; do
nicostags.py --prefix AnalysisBase --analysispkgfilter /afs/cern.ch/atlas/software/dist/nightlies/nicos_work/tags/AnalysisBase-2.6.X/x86_64-slc6-gcc49-opt/$ab 
done

# We then merge the analysis releases into the main dev release to make
# a super dev release
mergereleases.py tagdir/22.0.0-2017-01-01 tagdir/AthAnalysisBase-2.6.0-2017-01-01 tagdir/AnalysisBase-2.6.0-2017-01-01
mergereleases.py tagdir/22.0.0-2017-01-10 tagdir/AthAnalysisBase-2.6.0-2017-01-10 tagdir/AnalysisBase-2.6.0-2017-01-11
mergereleases.py tagdir/22.0.0-2017-01-20 tagdir/AthAnalysisBase-2.6.0-2017-01-19 tagdir/AnalysisBase-2.6.0-2017-01-20
mergereleases.py tagdir/22.0.0-2017-01-27 tagdir/AthAnalysisBase-2.6.1-2017-01-26 tagdir/AnalysisBase-2.6.1-2017-01-27
mergereleases.py tagdir/22.0.0-2017-02-02 tagdir/AthAnalysisBase-2.6.1-2017-02-01 tagdir/AnalysisBase-2.6.1-2017-02-02
mergereleases.py tagdir/22.0.0-2017-02-06 tagdir/AthAnalysisBase-2.6.1-2017-02-05 tagdir/AnalysisBase-2.6.1-2017-02-06
mergereleases.py tagdir/22.0.0-2017-02-15 tagdir/AthAnalysisBase-2.6.2-2017-02-14 tagdir/AnalysisBase-2.6.2-2017-02-15
mergereleases.py tagdir/22.0.0-2017-02-21 tagdir/AthAnalysisBase-2.6.2-2017-02-20 tagdir/AnalysisBase-2.6.2-2017-02-21
mergereleases.py tagdir/22.0.0-2017-02-22 tagdir/AthAnalysisBase-2.6.2-2017-02-21 tagdir/AnalysisBase-2.6.2-2017-02-22
) |& tee o.${gitrepo}.tags


base_prod_releases=$(ls -v tagdir/* | perl -ne 'print if /\/\d+\.\d+\.\d+$/')
all_prod_releases=$(ls -v tagdir/* | perl -ne 'print if /\/\d+\.\d+\.\d+(\.\d+)?$/')
master_prod_releases=$(ls -v tagdir/19.2.* tagdir/20.1.* tagdir/20.7.* tagdir/21.0.* | perl -ne 'print if /\/\d+\.\d+\.\d+$/')
dev_releases=$(ls tagdir/22.0.0-2017-??-??)

# Copy definitive author list...
cp ~/bin/aogt.author.metadata ${gitrepo}.author.metadata

# Import all tags
(time asvn2git.py file:///atlas/scratch0/graemes/ao-mirror $gitrepo $all_prod_releases $dev_releases) |& tee o.${gitrepo}.a2s

# Build master branch
(time branchbuilder.py $gitrepo master $master_prod_releases $dev_releases --skipreleasetag --onlyforward) |& tee o.${gitrepo}.master

# Build release branches
for r in 19.2 20.1 20.7 20.8 21.0; do
	(time branchbuilder.py $gitrepo $r $(ls -v tagdir/$r.* | perl -ne 'print if /\/\d+\.\d+\.\d+$/') --parentbranch master:@$(pwd)/tagdir/$r.0 ) |& tee o.${gitrepo}.bb.$r
done
# HLT branch was made from 20.7, not dev
(time branchbuilder.py $gitrepo 20.11 $(ls -v tagdir/20.11.?) --parentbranch 20.7:@$(pwd)/tagdir/20.11.0 ) |& tee o.$gitrepo.bb.20.11
# Upgrade branch was made from 20.7, not dev
(time branchbuilder.py $gitrepo 20.20 $(ls -v tagdir/20.20.?) --parentbranch 20.7:@$(pwd)/tagdir/20.20.0 ) |& tee o.$gitrepo.bb.20.20

# Build cache branches
for series in 19.2 20.1 20.7 20.11 20.20; do
for base in $(ls -v tagdir/${series}.* | perl -ne 'print "$1\n" if /\/(\d+\.\d+\.\d+$)/'); do
cache=$(ls -v tagdir/${base}.* 2>/dev/null)
if [ -z "$cache" ]; then
	echo "Release $base has no caches"
else
	(time branchbuilder.py ${gitrepo} ${base} ${cache} --parentbranch ${series}:release/${base} --baserelease tagdir/${base}) |& tee o.$gitrepo.bb.${base} 
fi
done
done

# Update for master:
# cmaketags.py --nightly rel_1 22.0.X
# asvn2git.py file:///atlas/scratch0/graemes/ao-mirror aogt tagdir/22.0.X-2017-01-08-rel_1 --licensefile ~/bin/apache2.txt --uncrustify ~/bin/uncrustify-import.cfg
# 

# TODO - tag nightlies on master branch...

