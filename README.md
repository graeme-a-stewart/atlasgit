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

`nicostags.py` - Parses NICOS tag archive files to obtain the SVN tag content
of releases to import into git

`asvn2git.py` - Imports a set of SVN tags into a git repository, placing them on  
special import branches

`branchbuilder.py` - Reconstruct from release tag content files the state 
of an offline release on a git branch

`svnpull.py` - Script to pull arbitrary SVN package versions and import them
into an already checked out git repository (use `svnpull.py --help` for more
details)

---

Auxiliary scripts:

`tjson2txt.py` - simple script to convert JSON timing file (from asvn2git.py) into
a text file that can be imported and plotted into a spreadsheet

`casefilter.sh` - git filter-branch script that resets the case of repository files
which at some point in their SVN history changed case, causing problems on
case insensitive file systems (it's not proposed to use this, but it's kept for
archival interest)

`licensecheck.py` - script that can be used to check for suspicious license or
copyright statements in imported code (Apache license text is ignored)

`orderreleases.py` - takes a set of release tag files and orders them 
chronologically (useful for constructing the master branch)

`pkgdiff.py` - compare two different package tag files

`releasedate.py` - plots release dates using matplotlib

`glogger.py`, `atutils.py`, `svnutils.py`- module files for shared functions

---

Other files:

`aogt.author.metadata` - JSON file with all ATLAS SVN authors identified 
(particularly including those who have left ATLAS and are no longer in
CERN's phonebook)

`uncrustify-import.cfg` - Uncrustify configuration file used to reformat
C++ sources in a standard way on import from SVN

`atlasoffline-exceptions.txt` - List of glob matches for files that will
either not be added to git from SVN or be forced to be added to git

`atlaslicense-exceptions.txt` - List of glob matches for files that will
not have any license added to them during a standard ATLAS import
(when using the `--licensefile` option of `asvn2git.py`)

`atlasuncrustify-exceptions.txt` - List of glob matches for files that will
not have uncrustify added to them during a standard ATLAS import
(when using the `--uncrustify` option of `asvn2git.py`) *NB* It was decided
not to pass code through uncrustify during the bulk ATLAS import due
to some errors made when rewriting the code.

`import.sh` - Script containing the final sequence of commands used to
perform the SVN to git migration of the atlasoff repository (very useful to
see the use of more advanced options as well)


HOWTO
-----

If you want to convert from the ATLAS Offline SVN repository into a git repo, then
here's roughly the procedure to follow. Note that the entire strategy here is based 
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

`setupATLAS; lsetup git`

### Preparing tagdiff files from known releases

Use the `nicostags.py` and/or `cmaketags.py` script the SVN tag content of interesting
releases and write a JSON files containing the (SVN) tag content of the releases of
interest.

By far the easiest way to do this is just to give a base release:

`cmaketags.py 21.0` or `nicostags.py 20.7`

This takes the base content of release series 21.0 (or 20.7), then finds and parses all the 
base releases and caches and produces a file with the package tag evolution. The default
tag content files are placed in the `tagdir` directory.

Note that CMake and CMT releases can, of course, be combined in any import to git.

To get the tag content of a CMake nightly that is no longer available the
`nicostags.py` script can be used.

### Import SVN tags into git

Using the `asvn2git.py` script take the tag content files prepared above and import them into 
a fresh git repository.

The first two positional arguments are SVNREPO and GITREPO and all remaining ones are tag content
files (as generated above).

 `asvn2git.py file:///data/graemes/atlasoff/ao-mirror aogt tagdir/{19,20,21}.?.?`

The default import is performed using a separate branch for each package. This is a clean import
strategy, however it creates many branches, which makes for an unwieldy repository
It is possible to use a single branch for all imported 
tags using the `--targetbranch` option, but this is no longer well tested ;-)

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
but this is not that important). The `orderreleases.py` script can be used
to help with this, or filtering to only base releases.

It is possible to re-run `asvn2git.py` with new or updated tag content files. The bookkeeping
git tags will ensure that no duplicate imports are made. If `asvn2git.py` is 
re-run on the same set of tag content files it will
_update_ the trunks of each imported package to the latest revision if the `--processtrunk` option
is given (by default it is not - only tagged packages are imported).

#### Optional source file manipulations

`--licensefile` - License file that will be added to C++ and python code on import
(use the `--licenseexceptions` file to exclude source files from having a license added -
see the default `atlaslicense-exceptions.txt` for some examples of what and why).

`--uncrustify` - An [uncrustify](http://uncrustify.sourceforge.net/) configuration file
that will be used to reformat C++ sources before import. It is recommended to use the
default `uncrustify-import.txt` for consistency in the offline code base. *N.B.* it
was noticed that uncrustify can make mistakes when processing code, so unless you
can validate all of the changes this is probably too risky (it was decided not to
use it for the main `atlasoff` import).

### Construct a master branch

This step is optional, but a fairly complete historical import is performed if
a master branch, encapsulating the entire release history, is constructed first.

Here just run `branchbuilder.py` with all the releases of interest, but use these options:

`branchbuilder.py aogt master $(ls -v tagdir/{19,20,21}.?.?) --skipreleasetag --onlyforward`

* `--skipreleasetag` will not make tagged releases for this master branch (these should be made
on the release branches themselves - see next section)

* `--onlyforward` will prevent any tag from being downgraded on the master branch and will 
preprocess the list of releases to ensure that the master branch never skips backwards
to an earlier release in time (see https://its.cern.ch/jira/browse/ATLINFR-1306 for
a discussion why this is sensible) 

Use `ls -v` to make sure the releases are given to the script in _release_ order and not 
alphabetically. Note also that cache releases should not be imported into master (tune your
`ls` command to ensure this!).

See `import.sh` for an example of how to create a development superset of packages
from the offline `dev` releases, but with `(Ath)AnalysisBase` packages included.

### Construct git branches for base releases

Once the master branch has been constructed, each release branch can be made. There is
only one tricky option:

`branchbuilder.py aogt 20.1 $(ls -v tagdir/21.0.?) --parentbranch master:@$(pwd)/tagdir/21.0.0`

The `parentbranch` option instructs the script to branch from `master` using the commit time
corresponding to when the `21.0.0` release was made. Using this option means the
git repository contains a sensible ancestry between the release branches. (Because the script
will change working directory this has to be an absolute path, hence the `$(pwd)`.)

Obviously the parent branch can be anything known to the repository, e.g., one could branch
the HLT release from an appropriate commit on the Tier-0 branch. 

Internally, git tags are created so that the import repository knows which SVN tags are
current on the HEAD of each branch. (This allows the script to update when new releases
are processed.) As each of the base releases is processed a release tag is made, e.g.
`release/21.0.2`.

#### Construct patch release branches

If it is desired to recreate a series of patch releases use, e.g., this command

`branchbuilder.py aogt 20.11.0 $(ls -v tagdir/20.11.0.*) --parentbranch 20.11:release/20.11.0`

Note that this time we branch from an existing release tag, not from a release timestamp.

### Updating and nighty builds

As indicated, the whole process, from tag content file creation through importing from SVN
and creating branches, can be re-run multiple times, updating releases as they are made.
Bookkeeping git tags allow skipping work already done.

The tag content files for a nightly release are quite simple to get:

`cmaketags.py 21.0.X-VAL --nightly rel_5`

The name of the tag content file is a bit different, e.g., `21.0.X-VAL-2016-10-20-rel_5` 
but it is used just the same as before (i.e., `asvn2git.py` to git import any
missing SVN package tags, then `branchbuilder.py` to make the file changes
on the desired release branch).  

Note that when a nightly is imported the git release tag will look like

`nightly/21.0/2016-10-20T2213`

This encodes the branch on which the tag was made and the time when it was made. 
Nightly tags are always lightweight as it is not intended to keep them forever.


### Upload to gitlab/github

Finally, when a good import has been made, the repository should be exported. 

1. Create an empty repository in the social coding site of your choice (for 
ATLAS this should of course always be CERN GitLab!).

1. Add the upload repository to your local repository, e.g., like this:

```git remote add origin https://:@gitlab.cern.ch:8443/graemes/athena.git```

1. Push your _release_ branches to the new upstream origin:

```git push -u origin MY_BRANCH```

There is no need to push the special per-package import branches to the production
repository. In fact, doing so will will make the repository quite unweildy.

1. Push up tags that you care about

```git push origin MY_TAG```

Tags you care about usually means `git tag -l release/* nightly/*`.

1. Backup import repository:

If there is a desire to keep importing SVN tags over some time period then 
backing up the entire import repository to gitlab may be desirable as well.

## Copyright and License

See `license.txt`.
