# Releasing

1. Bump `manifest.json` `version`, fold the changelog, and push a `v*` tag
   (e.g. `v0.1.0rc1`, then `v0.1.0`).
2. CI drafts a GitHub release for that tag
   (`.github/workflows/release.yml`), with notes prefilled from the matching
   `CHANGELOG.md` section when one exists, and runs hassfest plus the HACS
   validation action (`.github/workflows/validate.yml`).
3. A human publishes the draft once both checks are green. HACS serves
   versions from GitHub **releases**, not from tags alone — a pushed tag
   with no published release stays invisible to HACS.
4. Never reuse a version: to redo one, yank it, move it back to draft, then
   re-tag as a patch.

## rc cycle order

Before the final tag, an rc cycle proves the pipeline end to end, in this
order: **blaueis-libmidea** rc published → the maintainer's gateway updated
to it over SSH → **blaueis-ha-midea** rc published → HACS install of the rc
from the custom repository, then the proofs of the rc rehearsal. The final
release repeats the same order (libmidea → gateway → ha-midea), with
**blaueis-hvacshark**'s annotated tag last.
