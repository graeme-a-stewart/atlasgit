#! /usr/bin/env python
#
# # SVN utility functions used by atlasgit scripts
#
# Copyright (c) Graeme Andrew Stewart <graeme.a.stewart@gmail.com>
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.


def scan_svn_tags_and_get_metadata(svnroot, svn_packages, svn_metadata_cache, author_metadata_cache, all_package_tags=False):
    # # @brief Get SVN metadata for each of the package tags we're interested in
    #  @param svnroot URL of SVN repository
    #  @param svn_packages Dictionary of packages and tags to process
    #  @param svn_metadata_cache SVN metadata cache
    #  @param author_metadata_cache author metadata cache with name and email for commits
    #  @param all_package_tags Boolean flag triggering import of all package tags in SVN

    # First we establish the list of tags which we need to deal with.
    for package, package_tags in svn_packages.iteritems():
        logger.info("Preparing package {0} (base tags: {1})".format(package, package_tags))
        if all_package_tags:
            oldest_tag = svn_packages[package][0]
            tags = get_all_package_tags(svnroot, package)
            try:
                package_tags.extend(tags[tags.index(oldest_tag) + 1:])
            except ValueError:
                logger.error("Oldest release tag ({0}) for package {1} not found in SVN!".format(oldest_tag, package))
                sys.exit(1)
        # We need to now sort the package tags and remove any duplicates
        ordered_tags = list(set(package_tags))
        ordered_tags.sort(cmp=tag_cmp)
        svn_packages[package] = ordered_tags

    # Now iterate over the required tags and ensure we have the necessary metadata
    for package, package_tags in svn_packages.iteritems():
        package_name = os.path.basename(package)
        package_path = os.path.dirname(package)
        for tag in package_tags:
            # Do we have metadata?
            if package_name not in svn_metadata_cache:
                svn_metadata_cache[package_name] = {"path": package_path, "svn": {}}
            try:
                if tag == "trunk":
                    # We always need to get the metadata for trunk tags as we need to
                    # know the current revision
                    svn_metadata = svn_get_path_metadata(svnroot, package, tag)
                    if tag not in svn_metadata_cache[package_name]["svn"]:
                        svn_metadata_cache[package_name]["svn"][tag] = {svn_metadata["revision"]: svn_metadata}
                    elif svn_metadata["revision"] not in svn_metadata_cache[package_name]["svn"][tag]:
                        svn_metadata_cache[package_name]["svn"][tag][svn_metadata["revision"]] = svn_metadata
                elif tag not in svn_metadata_cache[package_name]["svn"]:
                    svn_metadata = svn_get_path_metadata(svnroot, package, tag)
                    svn_metadata_cache[package_name]["svn"][tag] = {svn_metadata["revision"]: svn_metadata}
                else:
                    svn_metadata = svn_metadata_cache[package_name]["svn"][tag].values()[0]
                if svn_metadata["author"] not in author_metadata_cache:
                    try:
                        author_metadata_cache[svn_metadata["author"]] = author_info_lookup(svn_metadata["author"])
                    except RuntimeError, e:
                        logger.info("Failed to get author information for {0}: {1}".format(package, e))
                        author_metadata_cache[svn_metadata["author"]] = {"name": svn_metadata["author"],
                                                                         "email": "{0}@cern.ch".format(svn_metadata["author"])}
            except RuntimeError:
                logger.warning("Failed to get SVN metadata for {0}".format(os.path.join(package, tag)))


def svn_get_path_metadata(svnroot, package, package_path, revision=None):
    # # @brief Get SVN metadata and return as a simple dictionary keyed on date, author and commit revision
    logger.info("Querying SVN metadata for {0}".format(os.path.join(package, package_path)))
    cmd = ["svn", "info", os.path.join(svnroot, package, package_path), "--xml"]
    svn_info = check_output_with_retry(cmd)
    tree = eltree.fromstring(svn_info)
    return {
            "date": tree.find(".//date").text.rsplit(".", 1)[0],  # Strip off sub-second part
            "author": tree.find(".//author").text,
            "revision": tree.find(".//commit").attrib['revision'],
            }

def svn_co_tag_and_commit(svnroot, gitrepo, package, tag, svn_metadata=None, author_metadata_cache=None, branch=None,
                          filter_exceptions=[], filter_reject=[]):
    # # @brief Make a temporary space, check out from svn, clean-up, copy and then git commit and tag
    #  @param svnroot Base path to SVN repository
    #  @param gitrepo Path to git repository to import to
    #  @param package Path to package root (in git and svn)
    #  @param tag Package tag to import (i.e., path after base package path)
    #  @param svn_metadata SVN metadata cache
    #  @param author_metadata_cache Author name/email cache
    #  @param branch Git branch to switch to before import
    #  @param filter_exceptions Paths to force import to git
    #  @param filter_reject Paths to force reject from the import
    msg = "Processing {0} tag {1}".format(package, tag)
    if tag == "trunk":
        msg += " (r{0})".format(svn_metadata["revision"])
    logger.info(msg)

    if branch:
        logger.info("Switching to branch {0}".format(branch))
        switch_to_branch(args.targetbranch)

    tempdir = tempfile.mkdtemp()
    full_svn_path = os.path.join(tempdir, package)
    cmd = ["svn", "checkout", "-r", str(svn_metadata["revision"]), os.path.join(svnroot, package, tag), os.path.join(tempdir, package)]
    check_output_with_retry(cmd)

    # Clean out directory of things we don't want to import
    svn_cleanup(full_svn_path, svn_co_root=tempdir,
                filter_exceptions=filter_exceptions, filter_reject=filter_reject)

    # Copy to git
    full_git_path = os.path.join(gitrepo, package)
    package_root, package_name = os.path.split(full_git_path)
    try:
        if os.path.isdir(full_git_path):
            shutil.rmtree(full_git_path, ignore_errors=True)
        os.makedirs(package_root)
    except OSError:
        pass
    shutil.move(full_svn_path, package_root)

    # get ChangeLog diff
    cl_diff = changelog_diff(package)

    # Commit
    check_output_with_retry(("git", "add", "-A", package))
    if logger.level <= logging.DEBUG:
        logger.debug(check_output_with_retry(("git", "status")))
    cmd = ["git", "commit", "--allow-empty", "-m", "{0} - r{1}".format(os.path.join(package, tag), svn_metadata['revision'])]
    if svn_metadata:
        cmd.extend(("--author='{0}'".format(author_string(svn_metadata["author"], author_metadata_cache)),
                    "--date={0}".format(svn_metadata["date"])))
    if cl_diff:
        cmd.extend(("-m", "Diff in ChangeLog:\n" + '\n'.join(cl_diff)))
    check_output_with_retry(cmd)
    cmd = ["git", "tag", "-a", get_flattened_git_tag(package, tag, svn_metadata["revision"]), "-m", ""]
    check_output_with_retry(cmd)

    # Clean up
    shutil.rmtree(tempdir)

def svn_cleanup(svn_path, svn_co_root="", filter_exceptions=[], filter_reject=[]):
    # # @brief Cleanout files we do not want to import into git
    shutil.rmtree(os.path.join(svn_path, ".svn"))

    # File size veto
    for root, dirs, files in os.walk(svn_path):
        for name in files:
            filename = os.path.join(root, name)
            svn_filename = filename[len(svn_co_root) + 1:]
            filter_exception_match = False
            for filter in filter_exceptions:
                if fnmatch.fnmatch(svn_filename, filter):
                    logger.info("{0} imported from matching exception {1}".format(svn_filename, filter))
                    filter_exception_match = True
                    break
            if filter_exception_match:
                continue
            try:
                if os.stat(filename).st_size > 100 * 1024:
                    if "." in name and name.rsplit(".", 1)[1] in ("cxx", "py", "h", "java", "cc", "c", "icc", "cpp",
                                                                  "hpp", "hh", "f", "F"):
                        logger.info("Source file {0} is too large, but importing anyway".format(filename))
                    elif name in ("ChangeLog"):
                        logger.info("Repo file {0} is too large, but importing anyway".format(filename))
                    else:
                        logger.warning("File {0} is too large - not importing".format(filename))
                        os.remove(filename)
                if name.startswith("."):
                    logger.warning("File {0} starts with a '.' - not importing".format(filename))
                    os.remove(filename)

                # Rejection always overrides the above
                for filter in filter_reject:
                    if fnmatch.fnmatch(svn_filename, filter):
                        logger.info("{0} not imported due to {1} filter".format(svn_filename, filter))
                        os.remove(filename)

            except OSError, e:
                logger.warning("Got OSError treating {0}: {1}".format(filename, e))
