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

`branchbuilder.py` - Reconstruct from tag diffs the state of an offline release
on a git branch

`trunktagdiff.py` - Generates a simple tagdiff file for trunk versions of SVN
packages; used to update master branch to latest trunk versions 

---

Auxiliary files:

`tjson2txt.py` - simple script to convert JSON timing file (from asvn2git.py) into
a text file that can be imported and plotted into a spreadsheet

`casefilter.sh` - git filter-branch script that resets the case of repository files
which at some point in their SVN history changed case, causing problems on
case insensitive file systems. N.B. It is observed that managing the SVN to git
migration using the git 2.7 client seems to avoid these problems.

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
releases and write a few JSON _tagdiff_ files, encapsulating the way that a 
base release and its caches evolved.

By far the easiest way to do this is just to give a base release:

`cmttags.py 20.7.0`

This takes the base content of release 20.7.0, then finds and parses all the 20.7.0.Y caches
and produces and internal _diff_ that describes the package tag evolution. The default
tagdiff file in this case is `20.7.0.tagdiff`.

Usually one wants to produce tagdiff files for a whole release series (i.e., all 20.7.X(.Y)
numbered releases), e.g.,

`for X in $(seq 0 7); do cmttags.py 20.7.$X; done`

### Import SVN tags into git

Using the `asvn2git.py` script take the tagdiff files prepared above and import them into 
a fresh git repository.

Positional arguments are SVNREPO and GITREPO and `--tagdiff` files must also be given. e.g.,

`asvn2git.py file:///data/graemes/atlasoff/ao-mirror Tier0 --tagdiff 20.7.* --targetbranch package`

In the last case the option `--targetbranch` is used, with the special value `package` to
import each SVN package onto a separate git branch.

Tests of the import procedure can be made using the option `--svnpath PATH` that
restricts the import to packages that start with `PATH`.   

`asvn2git.py` will query SVN for revision numbers are make sure that it 
imports from SVN in SVN commit order. Thus the import history is fairly sane.

In order to facilitate the next step (release branch creation) the script creates a git
tag for every package imported. These are:

`import/Package-XX-YY-ZZ` for package tags

`import/Package-rNNNNNN` for package trunk at SVN revision `NNNNNN`

It is better that tagdiff files are processed in roughly historical order,
which assures a better import history.

It is possible to re-run `asvn2git.py` with new or updated tagdiff files. The bookkeeping
git tags will ensure that no duplicate imports are made.

### Construct git branches for numbered releases

Once the main git import has been made, each release branch that is required 
can be reconstructed with `branchbuilder.py`. Git repo and branch name are positional, 
and `--tagdiff` files are needed. e.g., 

`branchbuilder.py Tier0 20.7 --tagdiff 20.7.*`

As SVN package versions are processed, git tags are created to record each package
import. In addition a release tag, `release/A.B.X.Y`, is created once a release
is complete, unless the branch being constructed is `master`.

Re-running over the import is perfectly fine, as the git bookkeeping tags are used
to prevent duplicated imports.

### Updating

As indicated, the whole process, from tagdiff file creation through importing from SVN
and creating branches, can be re-run multiple times, updating releases as they are made.
Bookkeeping git tags allow skipping work already done.

The `trunktagdiff.py` script will create a special tagdiff file with the `trunk` path
in SVN, which allows for updating the `master` branch to reflect SVN trunk changes. 
(Internally, trunk tags do bookkeeping with a revision number, so this is also
quite safe to rerun.) 


### Upload to gitlab/github

1. Create an empty repository in the social coding site of your choice.

1. Add the repository to your imported repository, e.g., as one of:

```git remote add origin https://gitlab.cern.ch/graemes/aogt.git```

```git remote add origin https://:@gitlab.cern.ch:8443/graemes/aogt.git```

```git remote add origin https://github.com/graeme-a-stewart/atlasofflinesw.git```

1. Push your import to the new upstream origin:

```git push --all origin```

Note, if packages were imported on _per-package_ branches it may not be a good idea to
import all of these small branches. gitlab repositories get rather unweildy when
there are many, many branches (indeed, currently there is a bug in gitlab and the
web interface is broken when there are more than around 1000 branches).

1. Push up tags that you care about

```git push origin MY_TAG```

or 

```git push --tags origin```

Note that in the last case (`--tags`) make sure you _delete_ all tags in `import/`, 
as these are not needed post-import and they substantially degrade performance.


