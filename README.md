ATLAS git importer
==================

Overview
--------

This package contains some modules and scripts that can be used to import 
the ATLAS offline SVN repository into git.


### Files

Main scripts:

`cmaketags.py` - Parses a CMake release to obtain the SVN tag content
for importing into git. 

`cmttags.py` - Parses NICOS tag files to understand the SVN tag content
of CMT built releases to import into git

`asvn2git.py` - Imports a set of SVN tags into a git repository, placing them on  
import branch(es)

`branchbuilder.py` - Reconstruct from release tag content files the state 
of an offline release on a git branch

---

Auxiliary files:

`tjson2txt.py` - simple script to convert JSON timing file (from asvn2git.py) into
a text file that can be imported and plotted into a spreadsheet

`casefilter.sh` - git filter-branch script that resets the case of repository files
which at some point in their SVN history changed case, causing problems on
case insensitive file systems.

`glogger.py`, `atutils.py` - module files for shared functions


HOWTO
-----

If you want to convert from the ATLAS Offline SVN repository into a git repo, then
here's roughly the proceedure to follow. Note that the entire strategy here is based 
on the idea of importing packages _at their package tag_ history points in SVN. If
you want to do a more conventional import of a single SVN package, with each SVN
commit reproduced as a git commit, then the built-in `git svn` module should do this
for you.

*Important Note* It's very important to run these scripts using version 1.7
(or later) of the subversion client and python 2.7. The SVN client is much more efficient and
keeps a `.svn` only at the root of any checkout, which is far easier to import 
from. The python version is needed for a few features used in these scripts.

On SLC6 use the scl module to activate the 1.7 SVN client and python 2.7:

`/usr/bin/scl enable subversion17 python27 -- /bin/bash`

Using an up to date git client will certainly _do no harm_ and specifically helps
when files have undergone case changes in their history. An up to date git client
is available via

`atlasSetup; lsetup git`

### Preparing tagdiff files from known releases

Use the `cmttags.py` and/or `cmaketags.py` script the SVN tag content of interesting
releases and write a JSON files containing the (SVN) tag content of the releases of
interest.

By far the easiest way to do this is just to give a base release:

`cmaketags.py 21.0` or `cmttags.py 20.7`

This takes the base content of release series 21.0 (or 20.7), then finds and parses all the 
base releases and caches and produces a file with the package tag evolution. The default
tag content files are placed in the `tagdir` directory.

Note that CMake and CMT releases can, of course, be combined in any import to git.

### Import SVN tags into git

Using the `asvn2git.py` script take the tag content files prepared above and import them into 
a fresh git repository.

The first two positional arguments are SVNREPO and GITREPO and all remaining ones are tag content
files (as generated above).

 `asvn2git.py file:///data/graemes/atlasoff/ao-mirror aogt tagdir/20.7.*`

The default import is performed using a separate branch for each package. This is a clean import
strategy, however it creates many branches, which gitlab does not like, so it is possible to use
 a single branch for all imported tags using the `--targetbranch` option (generally, however,
 there is no need to upload the import branches to gitlab).

Tests of the import procedure can be made using the option `--svnpath PATH` that
restricts the import to packages that start with `PATH`.   

`asvn2git.py` will query SVN for revision numbers are make sure that it 
imports from SVN in SVN commit order. Thus the import history is fairly sane.

In order to facilitate the next step (release branch creation) the script creates a git
tag for every package imported. These are:

`import/Package-XX-YY-ZZ` for package tags

`import/Package-rNNNNNN` for package trunk at SVN revision `NNNNNN`

It is better that tag content files are processed in roughly historical order,
which gives a more reasonable import history (although branch tags may appear muddled,
but this is not that important).

It is possible to re-run `asvn2git.py` with new or updated tag content files. The bookkeeping
git tags will ensure that no duplicate imports are made. If `asvn2git.py` is 
re-run on the same set of tag content files it will
_update_ the trunks of each imported package to the latest revision.

### Construct git branches for numbered releases

Once the main git import has been done, each release branch that is required 
can be reconstructed with `branchbuilder.py`. Git repo and branch name are positional, 
and `--tagdiff` files are needed. e.g., 

`branchbuilder.py aogt 20.7 tagdir/20.7.*`

As SVN package versions are processed, git tags are created to record each package
import. In addition a release tag, `release/A.B.X[.Y]`, is created once a release
is complete, unless the branch being constructed is `master`.

Re-running over the import is perfectly fine, as the git bookkeeping tags are used
to prevent duplicated imports.

TODO: Descibe how to create and store a patch branch off a base release.

### Updating

As indicated, the whole process, from tag content file creation through importing from SVN
and creating branches, can be re-run multiple times, updating releases as they are made.
Bookkeeping git tags allow skipping work already done.

TODO: Allow `branchbuilder.py` to update to latest trunk revisions on the master branch.

#### Tagdiff files for CMake nightlies

In the `cmaketags.py` script simply give the name of the nightly branch to parse
and the different releases to scan, e.g.,

`cmaketags.py rel_1 rel_2 rel_3 rel_4 --nightly 21.0.X`

The default tagdiff file is composed of the nightly branch name, the first
release and a timestamp, e.g., `21.0.X-VAL_rel_1-2016-06-26T2242.tagdiff`.

TODO: Fix this, it's broken...

### Upload to gitlab/github

1. Create an empty repository in the social coding site of your choice.

1. Add the repository to your imported repository, e.g., as one of:

```git remote add origin https://gitlab.cern.ch/graemes/aogt.git```

```git remote add origin https://:@gitlab.cern.ch:8443/graemes/aogt.git```

```git remote add origin https://github.com/graeme-a-stewart/aogt.git```

1. Push your release branches to the new upstream origin:

```git push -u origin MY_BRANCH```

Note, if packages were imported on _per-package_ branches it may not be a good idea to
import all branches. gitlab repositories get rather unweildy when
there are many, many branches (indeed, currently there is a bug in gitlab and the
web interface is broken when there are more than around 1000 branches).

1. Push up tags that you care about

```git push origin MY_TAG```

or 

```git push --tags origin```

Note that in the last case (`--tags`) make sure you _delete_ all tags in `import/`, 
as these are not needed post-import and they substantially degrade performance.
