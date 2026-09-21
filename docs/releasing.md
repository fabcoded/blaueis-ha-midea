# Releasing

1. Bump `manifest.json` `version`, fold the changelog, and push a `v*` tag
   (e.g. `v0.1.0rc1`, then `v0.1.0`).
2. CI drafts a GitHub release for that tag
   (`.github/workflows/release.yml`), with notes prefilled from the matching
   `CHANGELOG.md` section when one exists, and runs hassfest plus the HACS
   validation action (`.github/workflows/validate.yml`).
3. A human publishes the draft once both checks are green (see
   "Known-red checks" below for the two that are not yet). HACS serves
   versions from GitHub **releases**, not from tags alone — a pushed tag
   with no published release stays invisible to HACS. The workflow marks
   the draft as a **pre-release** when the tag carries `a`, `b` or `rc`
   after the numeric part (`v0.1.0rc1`, `v0.2.0a1`, `v0.2.0-b2`), so
   publishing an rc does not make HACS offer it as the latest stable
   version. Plain `vX.Y.Z` tags are drafted as normal releases. The step
   fails when `CHANGELOG.md` has no non-empty section for the tag's
   version, so fold `[Unreleased]` into a versioned heading before tagging.
4. Never reuse a version: to redo one, yank it, move it back to draft, then
   re-tag as a patch.

## rc cycle order

Before the final tag, an rc cycle proves the pipeline end to end, in this
order: **blaueis-libmidea** rc published → the maintainer's gateway updated
to it over SSH → **blaueis-ha-midea** rc published → HACS install of the rc
from the custom repository, then the proofs of the rc rehearsal. The final
release repeats the same order (libmidea → gateway → ha-midea), with
**blaueis-hvacshark**'s annotated tag last.

## Known-red checks

Two HACS-action checks fail until the maintainer resolves them, so "both
checks green" cannot hold yet:

- **license** — `LICENSE` is still CC0-1.0, which SPDX marks as not
  OSI-approved. The fix is the relicense, not a workflow `ignore:`.
- **brands** — the repository has no `brand/icon.png` and the integration
  domain is not registered in the Home Assistant brands repository.

## Before the first release

- `brand/icon.png` — the maintainer supplies the artwork; nothing here
  invents one.
- GitHub repository settings: a description, topics, and Issues enabled
  (the HACS action checks all three).
