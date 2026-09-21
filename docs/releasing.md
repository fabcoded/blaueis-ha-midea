# Releasing

1. Bump `manifest.json` `version`, fold the changelog, and push a `v*` tag
   (e.g. `v0.1.0rc1`, then `v0.1.0`).
2. CI drafts a GitHub release for that tag
   (`.github/workflows/release.yml`), with notes prefilled from the matching
   `CHANGELOG.md` section when one exists, and runs hassfest plus the HACS
   validation action (`.github/workflows/validate.yml`).
3. A human publishes the draft once the Validate run is green (see
   "What the Validate workflow checks" below). HACS serves
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

## What the Validate workflow checks

`validate.yml` runs hassfest and the HACS action on every push and weekly.
Everything it needs is in the tree or in the repository settings:

- **hassfest** — `manifest.json` keys in the order `domain`, `name`, then
  alphabetical; the other manifest fields as HA requires.
- **HACS repository checks** — a repository description and topics
  (repository settings, set with `gh repo edit`), issues enabled, and
  `hacs.json`.
- **HACS brands** — `custom_components/blaueis_midea/brand/icon.png` and
  `icon@2x.png` (a placeholder today, see "Before the first release"), or a
  listing in the `home-assistant/brands` repository.
- **HACS license** — an OSI-approved `LICENSE` (MIT since the relicense).

A red run blocks merges to `main` until it is fixed (workspace rule).

## Before the first release

- `custom_components/blaueis_midea/brand/icon.png` and `icon@2x.png` are a
  placeholder (glacier-blue square, white "B"). Replace them with the
  maintainer's artwork under the same file names. The HACS brands check also
  accepts a listing in the `home-assistant/brands` repository later.
- GitHub repository settings: a description, topics, and Issues enabled
  (the HACS action checks all three).
