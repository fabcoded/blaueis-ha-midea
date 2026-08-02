#!/usr/bin/env bash
#
# Gate: the vendored lib/ tree must match its libmidea source.
#
# sync_from_libmidea.py exit codes:
#   0  in sync
#   1  drift  -> block the commit
#   2  no sibling blaueis-libmidea checkout -> not a drift signal
#
# Exit 2 means the check could not run, not that it failed. Contributors
# clone this integration on its own (the README puts it under
# <HA config>/custom_components/), so the sibling checkout only exists in
# the development workspace. Treat it the same way the ruff gate treats a
# missing ruff: warn, skip, let CI carry the enforcement.

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
LIBMIDEA="$(dirname "$REPO_ROOT")/blaueis-libmidea"

# The comparison is working-tree against working-tree, but pre-commit stashes
# unstaged changes here before running hooks — so our side reflects the index
# while the libmidea side still reflects its working tree. When libmidea has
# uncommitted changes in the mirrored subtrees, those two are not comparable
# and the check reports drift that does not exist.
#
# That combination is the normal mid-change state: edit libmidea, sync, test,
# commit both. Skip rather than block, and let the check do its job once the
# libmidea side is committed.
if [ -d "$LIBMIDEA/.git" ] && ! git -C "$LIBMIDEA" diff HEAD --quiet -- \
        packages/blaueis-core/src/blaueis/core \
        packages/blaueis-client/src/blaueis/client 2>/dev/null; then
    echo "" >&2
    echo "pre-commit: WARNING — blaueis-libmidea has uncommitted changes in the" >&2
    echo "mirrored subtrees; vendored-drift gate skipped (the comparison is not" >&2
    echo "meaningful until those land). Commit libmidea first to re-arm it." >&2
    exit 0
fi

python3 "$REPO_ROOT/tools/sync_from_libmidea.py" --check
rc=$?

case "$rc" in
    0)
        exit 0
        ;;
    2)
        echo "" >&2
        echo "pre-commit: WARNING — no sibling blaueis-libmidea checkout;" >&2
        echo "vendored-drift gate skipped. This is expected outside the" >&2
        echo "development workspace." >&2
        exit 0
        ;;
    *)
        echo "" >&2
        echo "pre-commit: vendored lib/ has drifted from libmidea." >&2
        echo "Run 'python3 tools/sync_from_libmidea.py' (no flag) to fix," >&2
        echo "then re-stage and re-commit." >&2
        exit 1
        ;;
esac
