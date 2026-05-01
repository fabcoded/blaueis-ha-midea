# Device-specific knowledge base

Per-device notes and copy-pasteable glossary overrides for ACs that
under- or mis-report their capabilities on the serial protocol.

## The identity layer: capability fingerprints, not product labels

The Midea serial protocol has no model-ID field we can read. Two units
with the same product label can ship different firmware with different
cap shapes, and two units with different labels can share the same
cap shape. **What defines "a device" at this layer is its capability
fingerprint** — the exact byte sequence it returns to the B5 query
plus a small set of diagnostic behaviours.

Files here are organised by product-line label for discoverability
(users find their AC via the name on the box), but the **fingerprint
in the doc is what the override actually targets**. A product-line doc
may grow multiple fingerprint sections if we characterise more than one
firmware variant under the same label.

## How this is used

Find your product below → open the doc → run `ac_probe.py` against your
AC → compare your probe output against the fingerprint in the doc. If
and only if the fingerprint matches, copy the override YAML into
*Settings → Devices & Services → Blaueis Midea AC → Configure →
Advanced — Glossary overrides*.

## How this is *not* used

These files are reference documentation, not a runtime mechanism. The
integration never auto-loads any override here. Cap fingerprints within
a single product line can disagree across firmware revisions, and a
silent auto-applied misdecode on the wrong unit is worse than a
visible no-op that makes the user think. **You paste, you own it.**

## Documented product lines

| Product line | Fingerprints characterised | Observed on |
|---|---|---|
| [Midea XtremeSaveBlue](xtremesaveblue.md) | cap `0x16=0`, SN8 empty, 8-bit B1 keyspace | one XtremeSaveBlue-labelled unit, 2026-04 |

## Adding a device

One markdown file per product line. Key sections (use the XtremeSaveBlue
file as a template):

1. **Matching by fingerprint** — the exact B5 cap map bytes to compare
   against, plus diagnostic dead-ends and behavioural signatures. This
   is the identity of the entry.
2. **Observed on** — which physical unit(s) labelled how, when probed.
   Explicit about what we *haven't* tested — readers shouldn't assume
   the label alone implies a match.
3. **Working override** — inline YAML, copy-pasteable, with a short
   "what this does" explainer.
4. **Sanity-check values** so a user can tell immediately whether the
   paste worked, and what a wrong-paste looks like.
5. **Change log** with dates and what was actually measured.

If a product line gains a second distinct fingerprint (new firmware
revision, different sub-model), add it as a second section inside the
same file with its own fingerprint + override. Don't collapse two
fingerprints under one override "because the label is the same" —
that's exactly the silent-misdecode failure mode this knowledge base is
structured to prevent.
