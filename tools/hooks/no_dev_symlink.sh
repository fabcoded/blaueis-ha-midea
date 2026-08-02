#!/usr/bin/env bash
#
# Gate: the vendored lib/ subtrees must be real files, not dev symlinks.
#
# tools/dev_link_libmidea.py swaps lib/blaueis/{core,client} for symlinks
# into a sibling libmidea checkout so edits there are picked up live. That
# state must never be committed — the vendored copy is what ships to users.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
LIB="$REPO_ROOT/custom_components/blaueis_midea/lib/blaueis"

for sub in core client; do
    if [ -L "$LIB/$sub" ]; then
        echo "pre-commit: $LIB/$sub is a symlink (dev-link active)." >&2
        echo "Run 'python3 tools/dev_link_libmidea.py --unlink' to restore" >&2
        echo "flat-file copies before committing." >&2
        exit 1
    fi
done

exit 0
