# Device-specific knowledge base

Per-device notes and copy-pasteable glossary overrides for ACs that under-
or mis-report their capabilities on the serial protocol.

**How this is used:** find your device below, compare the capability
fingerprint against your own `ac_probe.py` output, then copy the
override YAML into *Settings → Devices & Services → Blaueis Midea AC →
Configure → Advanced — Glossary overrides*.

**How this is *not* used:** these files are reference documentation, not
a runtime mechanism. The integration never auto-loads any override here.
Device firmware revisions within the same product line can disagree on
cap semantics, and a silent auto-applied misdecode is worse than a
visible no-op. You paste, you own it.

## Documented devices

| Product line | Models | Status |
|---|---|---|
| [Midea XtremeSaveBlue](xtremesaveblue.md) | Q11 | ✅ characterised, live-validated |

## Adding a device

One markdown file per product line. Use the XtremeSaveBlue file as a
template — key sections are:

1. **Known models** — status per model (characterised / tentative /
   reported-working-by-user / etc.).
2. **Identification** — by physical label **and** by capability
   fingerprint (B5 cap map + diagnostic dead-end queries). Identification
   by protocol fingerprint is the reliable axis — there is no model-ID
   field in the serial protocol we can read.
3. **Device-specific quirks** that show up in decode or control paths.
4. **Working override YAML** inline as a code block.
5. **Sanity-check values** so users can tell immediately if the paste
   worked.
6. **Change log** with dates and what was measured.

When adding a new product line, also update the table above.
