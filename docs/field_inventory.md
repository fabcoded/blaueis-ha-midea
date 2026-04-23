# Field inventory — "what's actually populated on this AC?"

A diagnostic that sends every known read-query to the gateway, decodes
the responses **without cap-gating**, and reports which of the 211+
glossary fields are carrying real data on your specific firmware.

Three entry points — same output, same core logic, pick whichever
fits your workflow:

1. **HA button:** *AC device → "Run field inventory scan"* → tap → browser download.
2. **HA service:** `blaueis_midea.run_field_inventory` → scriptable from automations.
3. **CLI:** `python -m blaueis.tools.field_inventory …` → for pros + AI without HA in the loop.

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

## HA button

The AC device has a **"Run field inventory scan"** button. Tap it → a
background task kicks off. About 10 seconds later, a persistent
notification appears with two download links:

- markdown report (human-readable)
- JSON sidecar (machine-readable, used by `compare_to_blob_id`)

Links are single-use (**unlinked after first download**) and expire
after **15 minutes**. Click once, save locally if you want to keep it.

## HA service

```yaml
service: blaueis_midea.run_field_inventory
data:
  label: "cooling-20C-from-22"          # required — short state tag for the filename + header
  compare_to_blob_id: "abc123…"          # optional — uuid of a prior snapshot for diff-mode
  suggest_overrides: true                # optional, default true
```

The service returns **immediately**. Actual scan + file preparation
happens in a background task. When it's done, a persistent notification
fires with the download links.

`compare_to_blob_id` takes the uuid from a prior scan's notification
(it's in the URL: `/api/blaueis_midea/inventory/<uuid>/md`). Pass it in
and a third markdown file lands alongside — the field-by-field diff
between the two runs.

Typical workflow for state-dependency discovery:

```yaml
# In your automation — hypothetical "scan each state" script:
sequence:
  # 1. AC off
  - service: climate.turn_off
    target: { entity_id: climate.atelier_midea }
  - delay: "00:00:30"   # let it settle
  - service: blaueis_midea.run_field_inventory
    data: { label: "off" }
  # 2. AC cooling
  - service: climate.set_hvac_mode
    target: { entity_id: climate.atelier_midea }
    data: { hvac_mode: cool }
  - delay: "00:02:00"   # let the compressor spin up
  - service: blaueis_midea.run_field_inventory
    data:
      label: "cooling"
      compare_to_blob_id: "<uuid-from-the-off-scan>"
```

The uuid is surfaced in the first scan's notification.

## CLI

For professionals + AI that want to run without HA in the loop:

```sh
python -m blaueis.tools.field_inventory \
  --host 192.168.210.30 \
  --psk YG23aC3EWkdmabs2Pc5eWL7vR77fUtY2mzyiwJqglVsB \
  --label "cooling-20C-from-22"
```

Writes two files to the current directory:
`2026-04-23_20-45-00_cooling-20C-from-22_inventory.md` and `.json`.

Compare two prior runs:

```sh
python -m blaueis.tools.field_inventory \
  --host 192.168.210.30 --psk … \
  --label "idle" \
  --compare ./2026-04-23_off_inventory.json
```

Produces a third `…_compare.md` file alongside.

Flags:

| Flag | Default | Purpose |
|---|---|---|
| `--wait` | 1.5 s | Per-query response-wait window |
| `--output-dir` | cwd | Where the files land |
| `--no-suggest-overrides` | off | Skip the YAML-synthesis section |
| `--no-encrypt` | off | Disable AES-GCM (dev gateways only) |
| `--compare PATH` | — | Diff against a prior JSON sidecar |

## Suggested override snippets

For each field classified `populated` that HA would hide by default
(cap-gated to `never` on this firmware), the report emits a YAML
snippet ready to paste into *Configure → Advanced — Glossary
overrides (YAML)*. Example from the Q11:

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
is flagged **_(guessed)_**. Check the JSON sidecar's `variants` array
for the alternatives; pick the one whose value matches reality as
measured by an external meter.

## How it works

Short version:

1. Core logic lives in `blaueis.core.inventory` (pure functions —
   `ShadowDecoder`, `classify()`, `synthesize_override_snippet()`,
   report writers). No I/O, no HA dep.
2. The CLI opens its own WS to the gateway, feeds frames into a
   standalone `ShadowDecoder`.
3. The HA integration taps the existing `Device` WS via a frame-observer
   hook (added in blaueis-client as part of this feature), injects
   extra queries the normal poll loop doesn't send, and lets the same
   core library build the output.
4. HA serves the output as ephemeral tempfiles via a single-use
   `HomeAssistantView`. No files ever land in `/config/`.

Design philosophy and decisions are documented in the commit history +
inline docstrings. The core module's docstring is a good entry point.

## Troubleshooting

**"Inventory blob not found or expired" (404)**
: The tempfile has been unlinked. Either it was already downloaded
  once (links are single-use), or 15 minutes have passed since the
  scan. Run the scan again.

**"Inventory file already downloaded" (410)**
: You're clicking the same link a second time. Save the file after
  the first download if you want to share it.

**No `Suggested overrides` section in the report**
: Either no field qualifies (everything `populated` is already
  `feature_available: always`), or `suggest_overrides=false` was
  passed. The section is omitted entirely, not rendered empty.

**Picked encoding is wrong (value obviously unrealistic)**
: The `_(guessed)_` flag acknowledges this. Check the JSON sidecar's
  `variants` array for alternate decodes. If the `range:` on the field
  in `glossary.yaml` would exclude the wrong variant, a PR to add the
  bounds would make the picker deterministic.

**Scan takes longer than 10 s**
: The collection window is fixed in `_SCAN_COLLECTION_SECONDS`
  (`field_inventory.py`). Responses after the window drop on the
  floor. If you're consistently losing responses, raise the constant
  — frame spacing (150 ms minimum) limits how fast we can send, so
  tight scans will always need a generous window.
