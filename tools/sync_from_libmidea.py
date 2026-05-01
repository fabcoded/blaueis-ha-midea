"""sync_from_libmidea.py — mirror blaueis-libmidea source into the
vendored lib/ tree.

Single direction: libmidea → ha-midea. Never the other way. The
vendored copy is a build artefact, not source. Direct edits to
`custom_components/blaueis_midea/lib/blaueis/{core,client}/` are
overwritten on every run.

Usage:
    python3 tools/sync_from_libmidea.py            # sync, exit 0
    python3 tools/sync_from_libmidea.py --check    # diff-only, exit 1 on drift

Sources mirrored (relative to the libmidea sibling checkout):
    packages/blaueis-core/src/blaueis/core/   →  lib/blaueis/core/
    packages/blaueis-client/src/blaueis/client/ →  lib/blaueis/client/

`__pycache__/` directories are excluded from the mirror.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = REPO_ROOT.parent
LIBMIDEA = WORKSPACE / "blaueis-libmidea"

VENDOR_TARGETS: list[tuple[Path, Path]] = [
    (
        LIBMIDEA / "packages" / "blaueis-core" / "src" / "blaueis" / "core",
        REPO_ROOT
        / "custom_components"
        / "blaueis_midea"
        / "lib"
        / "blaueis"
        / "core",
    ),
    (
        LIBMIDEA / "packages" / "blaueis-client" / "src" / "blaueis" / "client",
        REPO_ROOT
        / "custom_components"
        / "blaueis_midea"
        / "lib"
        / "blaueis"
        / "client",
    ),
]


def _walk(root: Path) -> set[Path]:
    """All files under `root`, relative to root, excluding __pycache__."""
    out: set[Path] = set()
    for p in root.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        if p.is_file():
            out.add(p.relative_to(root))
    return out


def diff(src: Path, dst: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Return (only_in_src, only_in_dst, content_differs) — all rel to src/dst."""
    if not src.is_dir():
        raise SystemExit(f"libmidea source not found: {src}")
    if not dst.exists():
        return sorted(_walk(src)), [], []
    src_files = _walk(src)
    dst_files = _walk(dst) if dst.is_dir() else set()
    only_src = sorted(src_files - dst_files)
    only_dst = sorted(dst_files - src_files)
    differs: list[Path] = []
    for f in sorted(src_files & dst_files):
        if not filecmp.cmp(src / f, dst / f, shallow=False):
            differs.append(f)
    return only_src, only_dst, differs


def sync_one(src: Path, dst: Path) -> tuple[int, int, int]:
    """Return (added, removed, updated)."""
    only_src, only_dst, differs = diff(src, dst)
    dst.mkdir(parents=True, exist_ok=True)
    for f in only_src:
        (dst / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / f, dst / f)
    for f in differs:
        shutil.copy2(src / f, dst / f)
    for f in only_dst:
        (dst / f).unlink()
    # Best-effort empty-dir cleanup
    for d in sorted(dst.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return len(only_src), len(only_dst), len(differs)


def is_symlink_path(p: Path) -> bool:
    return p.is_symlink() or any(parent.is_symlink() for parent in p.parents)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift, exit 1 if any; do not modify files",
    )
    args = parser.parse_args()

    if not LIBMIDEA.is_dir():
        print(
            f"error: blaueis-libmidea not found at {LIBMIDEA}\n"
            "       (expected as a sibling checkout of blaueis-ha-midea)",
            file=sys.stderr,
        )
        return 2

    drift_found = False
    summary: list[str] = []
    for src, dst in VENDOR_TARGETS:
        rel = dst.relative_to(REPO_ROOT)
        if dst.is_symlink() or any(p.is_symlink() for p in dst.parents if p != REPO_ROOT):
            print(f"  {rel}: symlinked (dev-link active) — skip", file=sys.stderr)
            continue
        only_src, only_dst, differs = diff(src, dst)
        n_drift = len(only_src) + len(only_dst) + len(differs)
        if n_drift:
            drift_found = True
            summary.append(
                f"  {rel}: +{len(only_src)} −{len(only_dst)} ~{len(differs)}"
            )
            if args.check:
                for f in only_src:
                    print(f"    + {rel}/{f}")
                for f in only_dst:
                    print(f"    − {rel}/{f}")
                for f in differs:
                    print(f"    ~ {rel}/{f}")
        else:
            summary.append(f"  {rel}: in sync")

    if args.check:
        print("\n".join(summary))
        if drift_found:
            print("\nDRIFT detected. Run `python3 tools/sync_from_libmidea.py` to fix.", file=sys.stderr)
            return 1
        print("\nclean")
        return 0

    if not drift_found:
        print("\n".join(summary))
        print("\nclean (no changes)")
        return 0

    for src, dst in VENDOR_TARGETS:
        if dst.is_symlink():
            continue
        rel = dst.relative_to(REPO_ROOT)
        added, removed, updated = sync_one(src, dst)
        print(f"  {rel}: +{added} −{removed} ~{updated}")
    print("\nsynced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
