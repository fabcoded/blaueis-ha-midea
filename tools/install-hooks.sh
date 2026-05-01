#!/usr/bin/env bash
# Install the repo-tracked pre-commit hook into .git/hooks/.
# Run once after cloning. Idempotent.

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
ln -sf ../../tools/pre-commit "$REPO_ROOT/.git/hooks/pre-commit"
chmod +x "$REPO_ROOT/tools/pre-commit"
echo "installed pre-commit → tools/pre-commit"
