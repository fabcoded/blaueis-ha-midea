"""dev_link_libmidea.py — replace the vendored lib/ tree with relative
symlinks pointing at the libmidea sibling source. Local-only — never
commit while symlinked (the pre-commit hook refuses).

Restore via `--unlink` (or run `tools/sync_from_libmidea.py`).

Usage:
    python3 tools/dev_link_libmidea.py            # link
    python3 tools/dev_link_libmidea.py --unlink   # restore flat copies
    python3 tools/dev_link_libmidea.py --status   # report current state
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = REPO_ROOT.parent
LIBMIDEA = WORKSPACE / "blaueis-libmidea"

VENDOR_TARGETS: list[tuple[Path, Path]] = [
    (
        LIBMIDEA / "packages" / "blaueis-core" / "src" / "blaueis" / "core",
        REPO_ROOT / "custom_components" / "blaueis_midea" / "lib" / "blaueis" / "core",
    ),
    (
        LIBMIDEA / "packages" / "blaueis-client" / "src" / "blaueis" / "client",
        REPO_ROOT / "custom_components" / "blaueis_midea" / "lib" / "blaueis" / "client",
    ),
]


def status() -> int:
    for src, dst in VENDOR_TARGETS:
        rel = dst.relative_to(REPO_ROOT)
        if dst.is_symlink():
            target = os.readlink(dst)
            print(f"  {rel}: symlink → {target}")
        elif dst.is_dir():
            print(f"  {rel}: flat-file copy")
        else:
            print(f"  {rel}: missing")
    return 0


def link() -> int:
    if not LIBMIDEA.is_dir():
        print(f"error: blaueis-libmidea not found at {LIBMIDEA}", file=sys.stderr)
        return 2
    for src, dst in VENDOR_TARGETS:
        rel = dst.relative_to(REPO_ROOT)
        if not src.is_dir():
            print(f"error: source missing: {src}", file=sys.stderr)
            return 2
        if dst.is_symlink():
            print(f"  {rel}: already a symlink, skip")
            continue
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        rel_target = os.path.relpath(src, dst.parent)
        os.symlink(rel_target, dst, target_is_directory=True)
        print(f"  {rel} → {rel_target}")
    print("\nlinked. Do NOT commit while symlinked — run --unlink first.")
    return 0


def unlink() -> int:
    """Replace symlinks with flat-file copies via the sync script."""
    for _, dst in VENDOR_TARGETS:
        rel = dst.relative_to(REPO_ROOT)
        if dst.is_symlink():
            dst.unlink()
            print(f"  {rel}: symlink removed")
    # Now run the sync to repopulate as flat files
    sync_path = REPO_ROOT / "tools" / "sync_from_libmidea.py"
    print()
    rc = os.system(f'python3 "{sync_path}"')
    return rc >> 8 if rc else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--unlink", action="store_true")
    g.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        return status()
    if args.unlink:
        return unlink()
    return link()


if __name__ == "__main__":
    sys.exit(main())
