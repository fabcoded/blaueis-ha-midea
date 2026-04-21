# Glossary overrides — developer / debugging feature

## What it is

A per-device YAML override that patches the integration's view of the
device glossary at runtime. Lets you change the integration's behaviour
**without modifying the AC firmware or the on-disk glossary** — useful
for testing how the integration responds to caps that aren't actually
advertised, simulating firmware changes, or exercising error paths.

The override is **strictly a developer / debugging tool.** Leave it
empty for normal operation.

## Where to find it

*Settings → Devices & Services → Blaueis Midea AC → Configure*.

The setting **"Advanced — Glossary overrides (YAML)"** sits at the
bottom of the form. Empty by default; the placeholder text points
back to this document.

## What goes in the field

A **partial glossary** — the same schema as `glossary.yaml`, but you
only include the keys you want to change. The integration deep-merges
your override into a per-device patched view of the glossary at startup.
The base glossary is never modified.

### Example: simulate the AC not advertising `screen_display`

```yaml
fields:
  control:
    screen_display:
      feature_available: never
```

What this does:

- `screen_display` is removed from `Device.available_fields`.
- The Display & Buzzer mode select goes `unavailable` (cap-gated).
- Incoming `rsp_0xC0` frames no longer populate the field — the override
  is sticky against ingress (see G11).
- `device.read("screen_display")` returns `None`.
- Auto-cleanup (G14) removes any stale field-driven entities for the
  field from the HA entity registry.

To revert: clear the field, save, the integration reloads with the
un-overridden glossary view.

### Example: simulate a different cap_id

```yaml
fields:
  control:
    screen_display:
      capability:
        cap_id: '0xFF'
        cap_id_16: '0x02FF'
```

The patched glossary indexes the cap under the new ID; the actual B5
the AC sends will not match, so the cap will be treated as
unadvertised. Equivalent to `feature_available: never` in effect, but
exercises the cap-mismatch path instead of the cap-pinned-never path.

## Validation

On save, the integration:

1. Parses the YAML. Parse errors → form rejected with **line and
   column** of the error.
2. Strips the protected `meta` block silently (with a warning surfaced
   in the post-save confirmation).
3. Deep-merges the override into the base glossary.
4. Validates the merged result against `glossary_schema.json`. Any
   schema violation introduced by the override → form rejected with
   the **JSON-pointer path** of the offending field (e.g.
   `Schema validation failed at fields.control.screen_display: …`).
5. Stores the YAML text in the config entry options. The integration
   reloads automatically; on startup the YAML is re-parsed (config-flow
   validation is the authoritative gate, but re-parse keeps the runtime
   honest if the file was tampered with).

Pre-existing schema violations in the on-disk glossary (e.g. fields
with audit metadata blocks the schema doesn't yet describe) are
**ignored** — the validator only flags errors your override
*introduces*.

## What's deliberately NOT supported

- **Modifying `meta`.** Stripped silently; meta carries the schema
  version, last-updated date, and other constants no user override
  should touch.
- **Decode-rule overrides.** Not blocked technically (any leaf can be
  patched), but if you find yourself tweaking decode rules in an
  override, edit `glossary.yaml` directly instead — that's the source
  of truth and changes there are version-controlled with the rest of
  the integration.
- **Per-platform overrides.** The override applies at the glossary
  layer; downstream entities derive from `available_fields`. There's
  no separate "hide this entity" knob — go through the cap.

## Inspecting the applied override

Three options:

1. **Confirmation step.** When you save a non-trivial override, the
   form transitions to a confirmation step listing the affected leaf
   paths and any warnings (e.g. meta-strip).
2. **Diagnostics.** *Settings → Devices & Services → Blaueis Midea AC
   → \[device\] → Download Diagnostics* includes a `glossary_override`
   block with the raw YAML, the affected paths, and a summary of
   `available_fields` after the override applied. Useful for bug
   reports and offline diffs.
3. **HA logs.** On every config-entry setup the integration logs the
   number of leaf paths affected and a preview of the first five.

## Behind the scenes

- **Per-device patched view.** Each `Device` instance builds its own
  patched glossary at construction time (via
  `blaueis.core.glossary_override.apply_override`). The global
  glossary stays a singleton, untouched. Two AC entries with
  different overrides see different views.
- **Decoder respects sticky `never`.** When the override pins a
  field's `feature_available` to `never`, B5 cap promotion will
  *not* escalate the field back to `always` on subsequent ingresses
  — the override survives every frame, not just the first.
- **Auto-cleanup.** Entities for fields no longer in
  `available_fields` are removed from the HA entity registry on every
  setup, so the registry never accumulates stale `unavailable`
  entries from override-toggle-toggle iterations.

## Future work (not in v1)

- **Inline merged-glossary view.** A read-only menu step in the
  Configure dialog showing the post-merge YAML scoped to the touched
  fields, with `← overridden (base: X)` markers. Coverage is currently
  via the diagnostics download instead.
- **Live reload service.** Today the integration reloads on save,
  which takes ~2 s. A dedicated `blaueis_midea.reload_glossary_overrides`
  service could shave that further if developer iteration speed
  becomes a constraint.
