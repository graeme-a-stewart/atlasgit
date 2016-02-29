ATLAS git importer
==================

Files
-----

Modules to import ATLAS SVN to git.

Main files:

`asvn2git.py` - Imports a set of SVN tags into a git repository, placing them on the 
master branch

`atlastags.py` - Parses NICOS tag files to understand the SVN tag content
of a release; does diffs between a base release and various caches

`branchbuilder.py` - Reconstruct from tag diffs the state of an offline release
on a git branch

---

Auxiliary files:

`tjson2txt.py` - simple script to convert JSON timing file (from asvn2git.py) into
a text file that can be imported and plotted into a spreadsheet


HOWTO
-----

If you want to convert from the ATLAS Offline SVN repository into a git repo, then
here's roughly the proceedure to follow. Note that the entire strategy here is based 
on the idea of importing packages _at their package tag_ history points in SVN. If
you want to do a more conventional import of a single SVN package, with each SVN
commit reproduced as a git commit, then the built-in `git svn` module should do this
for you.

*Important Note* It's very important to run these scripts using version 1.7
(or later) of the subversion client. This client is much more efficient and
keeps a `.svn` only at the root of any checkout, which is far easier to import 
from. (If you don't do this, pieces of SVN metadata will be imported into git!)

On SLC6 use the scl module to activate the 1.7 SVN client:

`/usr/bin/scl enable subversion17 /bin/bash`

These scripts also use python2.7 features, whereas the SLC6 native python is 2.6.
Fix with:

`setupATLAS`
`lsetup python`

### Decide what to import to master

There are two basic strategies for importing packages onto the git master using `asvn2git.py`:

1. Import a certain section of the SVN repository
  * This is supported directly in `asvn2git.py`:
  * `--svnpackage` list of package paths in the SVN tree to process (e.g., `--svnpackage Tools/PyJobTransforms`)
  * `--svnpath` list of paths in SVN that will be scanned for leaf packages, 
  every leaf package found will be imported (e.g., `--svnpath Tracking`)
  * `--svnpathveto` list of paths in the SVN tree to veto for processing if the given string
  matches any part of the package path, these leaves will be omitted 
  (e.g. `--svnpath PhysicsAnalysis --svnpathveto HiggsPhys D3PDMaker/HeavyIonD3PDMaker`)

1. Import tags from a NICOS list of the tags built into a particular release
  * `--tagsfromtagdiff` list of files containing tagdiffs (as produced by `atlastags.py`)
  
In general, the first strategy is good when you want to just slice out a piece of the 
current SVN repository. The second works far better for a general import of the offline
SVN repository to git.

There are also a few options that control how extensive the import to git will be:

* `--trimtags N` take only the last `N` tags of a package (only useful for first strategy)
* `--tagtimelimit YYYY-MM-DD` take only tags younger than the specified date, plus the last tag made 
  before the date limit (so the 'current' tag on the given date is also admitted; again, this 
  is only useful for the first strategy)
* `--onlyreleasetags` take _only_ tags that were part of a release, otherwise all tags
  from the oldest tag in a release onwards are imported (only used with the second
  strategy)
  
By default the current `trunk` is always imported, but this can be suppressed with 
the `--skiptrunk` option.

#### Preparing tagdiff files from known releases

To employ the second strategy use the `atlastags.py` script to parse NICOS tag files and
write a few JSON _tagdiff_ files, encapsulating the way that a base release and it's caches
evolved.

By far the easiest way to do this is to give a base release:

`atlastags.py 20.1.0 --tagdifffile 20.1.0.tagdiff`

This takes the base content of release 20.1.0, then finds and parses all the 20.1.0.Y caches
and produces and internal _diff_ that describes the package tag evolution.

Usually one wants to produce tagdiff files for a whole release series (i.e., all 20.1.X(.Y)
numbered releases).

### Do the import

Using the import options described above imports are pretty easy.

In the case that you want to import based on a set of tagdiff files it's very important
to give *all* the tagdiff files for the release branches you will want to build, e.g.,

`asvn2git.py --tagsfromtagdiff 20.*.tagdiff --importtimingfile r20.json file:///data/graemes/atlasoff/ao-mirror r20`

(Just note to use the option `--onlyreleasetags` to leave out tags that were not put 
into any release.)

Note that `asvn2git.py` will query SVN for revision numbers are make sure that it 
imports from SVN in SVN commit order. Thus the master branch history is fairly sane.


### Construct git branches for numbered releases

Once the main git master branch has been made, each release branch that is required 
can be reconstructed with `branchbuilder.py`.

`branchbuilder.py --svnmetadata r20.svn.metadata r20 20.1 20.1.*.tagdiff`

Note that the `svnmetadata` option is used to branch from master at the correct 
point in the master import history, i.e., when the last tag that forms a branch
was committed to the master.

From the branch creation point, each numbered release is constructed and committed,
with a git tag containing the release name being created, e.g., `release/20.1.5.12`.

Note that in the example above a branch was made for the entire 20.1 series. It's
also possible to make a branch for only, e.g., 20.1.5 and caches.



