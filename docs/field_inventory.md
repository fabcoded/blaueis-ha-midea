# Field inventory — "what's actually populated on this AC?"

A diagnostic that sends every known read-query to the gateway, decodes
the responses **without cap-gating**, and reports which of the 211+
glossary fields are carrying real data on your specific firmware.

Two entry points — same output, same core logic:

1. **HA Configure menu:** *AC device → Configure → "Run new inventory scan on submit"* → tick + save → scan runs → result appears in the textarea below on your next visit to Configure.
2. **HA service:** `blaueis_midea.run_field_inventory` → scriptable from automations.

(A CLI variant lives in libmidea at `python -m blaueis.tools.field_inventory` for protocol work without HA in the loop.)

## Why this exists

Running `ac_probe.py` dumps raw frame bytes. Useful for protocol work,
not useful for "on my specific AC, is the humidity sensor actually
reporting values?" The inventory tool answers that — plus, for fields
that are populated but hidden by default HA cap-gating, it emits
**copy-paste-ready glossary-override YAML snippets** to unlock them in
the HA Configure dialog.

## The field classifications

| Bucket | Meaning |
|---|---|
| `populated` | Decoded a real non-zero value. The field is live. |
| `zero` | Decoded value is 0 / False / empty. Either a legitimately idle counter, or a field this firmware doesn't populate. Repeat the scan in a different state to tell them apart. |
| `ff_flood` | The whole response frame was `0xFF` bytes. The firmware accepts the query but doesn't populate anything — classic "protocol placeholder" pattern. |
| `none` | Decoder returned `None` — we couldn't extract a value from the frame at all. |
| `not_seen` | No response frame carrying this field arrived during the scan. |

A field that's `populated` in one scan and `zero` in another is
telling you about state-dependency. That's the main use case for
running it repeatedly.

## Running a scan from Configure

1. *Settings → Devices & Services → Blaueis Midea AC → Configure*
2. Scroll to **"Run new inventory scan on submit"**, tick the box.
3. Hit Submit. The form closes immediately; the scan runs in the
   background (~15 s).
4. Re-open Configure. The **"Latest field inventory report"** textarea
   now shows the full markdown — select + copy to save or share.

That's it. No URLs, no bell-icon notification, no files in `/config/`.

## HA service

```yaml
service: blaueis_midea.run_field_inventory
data:
  label: "cooling-20C-from-22"   # required — short state tag for the header
  suggest_overrides: true         # optional, default true
  reset_prior: false              # optional — skip the diff section on this run
```

The service returns immediately; the scan runs as a background task.
When it completes, the coordinator's cache (and therefore the
Configure textarea) updates with the new report.

### Compare-against-previous is automatic

Each completed scan is persisted to HA's `helpers.storage.Store`
(under `/config/.storage/blaueis_midea.<entry_id>.snapshot`). The
*next* scan finds that prior snapshot, computes a field-by-field diff,
and appends a **Changed fields** section to the new markdown report.
No parameter needed — compare is the default.

Use `reset_prior: true` when the baseline is invalid (e.g. after a
firmware change) and you want a clean start without a diff section.

Typical workflow for state-dependency discovery:

```yaml
sequence:
  - service: climate.turn_off
    target: { entity_id: climate.atelier_midea }
  - delay: "00:00:30"
  - service: blaueis_midea.run_field_inventory
    data: { label: "off", reset_prior: true }  # baseline
  - service: climate.set_hvac_mode
    target: { entity_id: climate.atelier_midea }
    data: { hvac_mode: cool }
  - delay: "00:02:00"
  - service: blaueis_midea.run_field_inventory
    data: { label: "cooling" }                 # auto-diffs vs "off"
```

The second scan's markdown carries the diff section.

## Suggested override snippets

For each field classified `populated` that HA would hide by default
(cap-gated to `never` on this firmware), the report emits a YAML
snippet ready to paste into *Configure → Advanced — Glossary
overrides (YAML)*. Example from a probed XtremeSaveBlue (cap 0x16=0) unit:

````markdown
### `power_total_kwh`

- **Live-decoded value:** `748.66 kWh` via `power_linear_4` encoding
- **Reason:** populated; cap `0x16=0x00` currently gates the field to `never`

```yaml
fields:
  sensor:
    power_total_kwh:
      capability:
        values:
          none_0:
            feature_available: always
            encoding: power_linear_4
      ha:
        device_class: energy
        state_class: total_increasing
        unit_of_measurement: kWh
        suggested_display_precision: 2
        off_behavior: available
```
````

Every emitted snippet is deep-merged against the base glossary and
validated against `glossary_schema.json` before being written to the
report. Snippets that fail validation are dropped + logged, never
shown to the user.

When a cap-dependent field has multiple encoding variants that all
produce plausible values (BCD vs linear, for instance) and the
glossary has no `range:` bounds to discriminate, the picked encoding
is flagged **_(guessed)_**. Check the JSON sidecar fields for the
alternatives; pick the one whose value matches reality as measured by
an external meter.

## How it works

Short version:

1. Core logic lives in `blaueis.core.inventory` (pure functions —
   `ShadowDecoder`, `classify()`, `synthesize_override_snippet()`,
   report writers). No I/O, no HA dep.
2. The HA integration attaches a `ShadowDecoder` to the existing
   `Device` WebSocket via the `register_frame_observer` hook, injects
   extra queries the normal poll loop doesn't send, and lets the core
   library build the markdown + JSON sidecar.
3. The scan result (markdown + JSON sidecar) is persisted to HA Store
   — one slot per config entry, overwritten on every scan, survives
   HA restarts.
4. The Configure textarea reads the cached markdown off the
   coordinator. The coordinator re-hydrates from Store on
   `async_setup_entry`.

### Memory + runtime cost

- **Observer is attached only during a scan** (~10 s window). At rest,
  the ingress path costs one `if self._frame_observers:` check per
  frame on an empty list — effectively free.
- **RAM held at rest:** one snapshot_json dict (~30 KB) + one rendered
  markdown string (~20 KB) + a few scalars. No ring, no FIFO. Each
  scan rebinds the coordinator attrs; the previous values are
  garbage-collected.
- **Disk at rest:** one JSON blob per config entry at
  `/config/.storage/blaueis_midea.<entry_id>.snapshot`. Overwritten on
  each scan. ~50 KB.

## Troubleshooting

**The textarea says "No field inventory scan has been run yet" but I just ran one**
: Re-open the Configure form. The textarea is populated from the
  coordinator at form-render time — a scan completing mid-form-display
  won't push an update. Close + reopen.

**Scan takes longer than 10 s**
: The collection window is fixed in `_SCAN_COLLECTION_SECONDS`
  (`field_inventory.py`). Responses after the window drop on the
  floor. If you're consistently losing responses, raise the constant
  — frame spacing (200 ms minimum) limits how fast we can send, so
  tight scans will always need a generous window.

**No `Suggested overrides` section in the report**
: Either no field qualifies (everything `populated` is already
  `feature_available: always`), or `suggest_overrides: false` was
  passed. The section is omitted entirely, not rendered empty.

**Picked encoding is wrong (value obviously unrealistic)**
: The `_(guessed)_` flag acknowledges this. Check the JSON sidecar's
  `variants` array for alternate decodes. If the `range:` on the field
  in `glossary.yaml` would exclude the wrong variant, a PR to add the
  bounds would make the picker deterministic.

**I want the scan history across restarts — is that possible?**
: Intentionally not. HA Store keeps exactly one prior scan per config
  entry; re-running a scan replaces it. If you want a durable history,
  copy the markdown out of Configure into your own notes. Runtime
  storage for inventory history is out of scope — this feature is a
  "what's live right now, vs the last time I looked" diagnostic, not a
  time-series store.
