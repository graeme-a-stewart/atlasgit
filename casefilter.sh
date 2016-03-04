#! /bin/sh
#
# Rewrite git history to manage files that changed case at some point in their
# SVN history, because this creates a git repository that cannot be used
# properly on case preserving+insensitive filesystems, such as the default
# mode for HFS+ filesystems on OS X
#
# This script filters all commit indexes and updates the 'bad' case name
# to the 'good' case one (i.e., usually what's in current master/HEAD).  
#
# Adapted from:
#  http://stackoverflow.com/questions/23841111/change-file-name-case-using-git-filter-branch
git filter-branch --index-filter '
git ls-files --stage | \
sed "s:Tools/RunTimeTester/share/FileComparator.py:Tools/RunTimeTester/share/fileComparator.py:" | \
sed "s:Tools/RunTimeTester/src/ShellCommand.py:Tools/Tools/RunTimeTester/src/shellcommand.py:" | \
sed "s:Trigger/TrigHypothesis/TrigJetHypo/src/TrigHLTJetHypoHelpers/CleanerFactory.cxx:Trigger/TrigHypothesis/TrigJetHypo/src/TrigHLTJetHypoHelpers/cleanerFactory.cxx:" | \  # Need to double check this one - not in master/HEAD
sed "s:Trigger/TrigT1/L1Topo/L1TopoAlgorithms/L1TopoAlgorithms/LAR.h:Trigger/TrigT1/L1Topo/L1TopoAlgorithms/L1TopoAlgorithms/LAr.h:" | \
sed "s:Trigger/TrigT1/L1Topo/L1TopoAlgorithms/Root/LAR.cxx:Trigger/TrigT1/L1Topo/L1TopoAlgorithms/Root/LAr.cxx:" | \
GIT_INDEX_FILE=$GIT_INDEX_FILE.new \
git update-index --index-info && \
mv "$GIT_INDEX_FILE.new" "$GIT_INDEX_FILE"
' HEAD
