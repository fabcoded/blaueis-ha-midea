#!/usr/bin/env bash
# Install this repo's git hooks. Run once after cloning. Idempotent.
#
# The gates themselves are declared in .pre-commit-config.yaml and run via
# the pre-commit framework (https://pre-commit.com). Two hook types are
# installed:
#
#   pre-commit  — lint, formatting, and the vendored-mirror gates
#   commit-msg  — message-level checks
#
# Both are safe outside the development workspace: the vendored-mirror gates
# skip with a warning when there is no sibling blaueis-libmidea checkout.

set -euo pipefail

if ! command -v pre-commit >/dev/null 2>&1; then
    echo "error: pre-commit not found on PATH." >&2
    echo "Install it with 'pip install pre-commit' (or 'pipx install pre-commit')" >&2
    echo "and re-run this script." >&2
    exit 1
fi

pre-commit install --overwrite
pre-commit install --overwrite --hook-type commit-msg

echo "hooks installed (pre-commit, commit-msg)"
