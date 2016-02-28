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

`get_prod_tags.sh` - simple helper script to wrap atlastags.py and make simple
tagdiff file for a base release and all caches

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

There are two basic strategies for importing packages onto the git master:

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
* `--onlyreleasetags` take _only_ tags that were part of a release (otherwise all tags
  from the oldest tag in a release onwards are imported)
  
By default the current `trunk` is always imported, but this can be suppressed with 
the `--skiptrunk` option.

#### Preparing tagdiff files from known releases

WRITE ME

### Do the import

WRITE ME

### Construct git branches for numbered releases

TODO

