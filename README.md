ATLAS git importer
==================

Files
-----

Modules to import ATLAS SVN to git.

Main files:

`asvn2git.py` - Imports a set of SVN tags into a git repository, placing them on an 
import branch

`atlastags.py` - Parses NICOS tag files to understand the SVN tag content
of a release; does diffs between a base release and various caches

`trunktagdiff.py` - Generates a simple tagdiff file for trunk versions of SVN
packages; used to update master branch to latest trunk versions 

`branchbuilder.py` - Reconstruct from tag diffs the state of an offline release
on a git branch

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

### Decide what to import to master

1. Import tags from a NICOS list of the tags built into a particular release
  * `--tagsfromtagdiff` list of files containing tagdiffs (as produced by `atlastags.py`)  
  
By default the current `trunk` is always imported, but this can be suppressed with 
the `--skiptrunk` option. Only SVN tags that appeared in releases are imported, unless
the `--intermediatetags` option is used, which process all tags from the oldest found
in a release..

#### Preparing tagdiff files from known releases

To employ the second strategy use the `atlastags.py` script to parse NICOS tag files and
write a few JSON _tagdiff_ files, encapsulating the way that a base release and it's caches
evolved.

By far the easiest way to do this is to give a base release:

`atlastags.py 20.1.0`

This takes the base content of release 20.1.0, then finds and parses all the 20.1.0.Y caches
and produces and internal _diff_ that describes the package tag evolution. The default
tagdiff file in this case is `20.1.0.tagdiff`.

Usually one wants to produce tagdiff files for a whole release series (i.e., all 20.1.X(.Y)
numbered releases).

### Do the import

Using the import options described above imports are pretty easy.

In the case that you want to import based on a set of tagdiff files it's very important
to give *all* the tagdiff files for the release branches you will want to build, e.g.,

`asvn2git.py --tagsfromtagdiff 20.*.tagdiff --importtimingfile r20.json file:///data/graemes/atlasoff/ao-mirror r20`

Note that `asvn2git.py` will query SVN for revision numbers are make sure that it 
imports from SVN in SVN commit order. Thus the import history is fairly sane.

In order to facilitate the next step (release branch creation) the script creates a git
tag for every package imported. These are:

`import/tag/Package-XX-YY-ZZ` for tags

`import/trunk/Package` for the trunk

N.B. The creation of this huge number of tags impacts on git performance, so it's best
to not export these tags to gitlab/github (or delete from the the original import
repository).

### Construct git branches for numbered releases

Once the main git import branch has been made, each release branch that is required 
can be reconstructed with `branchbuilder.py`.

`branchbuilder.py --svnmetadata r20.svn.metadata r20 20.1 20.1.*.tagdiff`

Note that the `svnmetadata` option is used to ensure that branches are built
with packages in SVN commit order (by default `GITREPO.svn.metadata` will be used).

From the branch creation point, each package is imported and committed; an import tag
for that branch is made for bookkeeping . Once a release is processed a git 
tag containing the release name being created, e.g., `release/20.1.5.12`. 
The commit is timestamped with the date that NICOS created its tag list file for
that release.  

Note that in the example above a branch was made for the entire 20.1 series. It's
also possible to make a branch for only 20.1.5 and caches (for example).

The script has protection against trying to import a package tag for which no
corresponding git import tag exists, but this should not happen if the tagdiff
files used to create the master branch and the release branch are the same.

### Upload to gitlab/github

1. Create an empty repository in the social coding site of your choice.

1. Add the repository to your imported repository, e.g., as:

```git remote add origin https://gitlab.cern.ch/graemes/aogt.git```
```git remote add origin https://:@gitlab.cern.ch:8443/graemes/aogt.git```
```git remote add origin https://github.com/graeme-a-stewart/atlasofflinesw.git```

1. Push your import to the new upstream origin:

```git push --all origin```

1. Push up tags that you care about

```git push origin MY_TAG```

or 

```git push --tags origin```

Note that in the last case (`--tags`) make sure you _delete_ all tags in `import/`, 
as these are not needed post-import and they substantially degrade performance.


