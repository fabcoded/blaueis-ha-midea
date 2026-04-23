# Midea XtremeSaveBlue

Per-device findings and a known-working glossary override for the
**XtremeSaveBlue** air-conditioner line.

## Known models

| Model | Status | Notes |
|---|---|---|
| Q11 | ✅ characterised, live-validated 2026-04-23 | Power telemetry under-reported as "no power calc"; data is present and linear-encoded. |

If you own a different XtremeSaveBlue model, the override below may or may
not apply — compare your probe output against the fingerprint below first.

---

## Identification

### By product label

Printed on the outdoor-unit spec plate and the remote: **"Midea
XtremeSaveBlue"** followed by a model code (Q11, Q14, Q1B, …). Label
match is necessary but not sufficient — the protocol-level fingerprint
below is the real test.

### By capability fingerprint

Run [`ac_probe.py`](../../../blaueis-libmidea/packages/blaueis-tools)
against your AC. The Q11 returns this B5 capability map:

```
tag=0xB5  b5 08 12 02 01 01  14 02 01 01  15 02 01 01
              16 02 01 00  1a 02 01 01  10 02 01 01  25 …
# 8 caps advertised: 0x10 0x12 0x14 0x15 0x16 0x1a 0x25 + one tail cap.
# The load-bearing byte: cap 0x16 = 0x00  ("no power calc")
```

Plus these dead-end queries that confirm the match:

- `msg_type 0x07` device-ID query → all-`0xFF` response (firmware accepts
  the query but doesn't populate a serial / model ID)
- B1 SN8 serial query → empty
- B1 property-key high byte → ignored (8-bit keyspace)

### By device-specific quirks that surprise you elsewhere

If you're debugging and see any of these, you're almost certainly on an
XtremeSaveBlue Q11:

- `compressor_idle` bit is **inverted** (`1` = idle, `0` = running). The
  OEM mobile app mislabels this as "compressor current".
- Louver swing-angle sensors return constants, not live positions.
- Buzzer is globally gated by the display-LED latch
  (`rsp_0xC0 body[14] bits[6:4]`). Silent-louver adjustment requires
  toggle-off → `cmd_0xB0` writes → toggle-on.
- `rsp_0xA1` heartbeat carries cumulative kWh at `body[1..4]` in linear
  encoding (not BCD, contrary to several published protocol notes).

---

## Working glossary override for Home Assistant

Paste into *Settings → Devices & Services → Blaueis Midea AC →
Configure → Advanced — Glossary overrides (YAML)* and submit:

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
    power_realtime_kw:
      capability:
        values:
          none_0:
            feature_available: always
            encoding: power_linear_3
      ha:
        device_class: power
        state_class: measurement
        unit_of_measurement: kW
        suggested_display_precision: 3
        off_behavior: available
```

### What this does

- Treats cap `0x16 = 0` as if it reported "power available, linear
  encoding" — the glossary's `power_cal_non_bcd` branch — so the
  decoder extracts `power_total_kwh` from C1-Group-4 `body[4..7]` and
  `power_realtime_kw` from `body[16..18]` as 4-byte and 3-byte
  big-endian integers divided by 100 and 10 000 respectively.
- Adds Home Assistant metadata (`device_class: energy`, `kWh`,
  `total_increasing`) so the sensors land in the Energy Dashboard, and
  `off_behavior: available` so cumulative readings don't go
  `unknown` every time the AC cycles off.

### Why only two fields and not all four

The protocol carries two more kWh counters — `power_total_run_kwh`
(`body[8..11]`) and `power_current_run_kwh` (`body[12..15]`) — but the
Q11 firmware never populates them. Observed: 48 h of live capture with
2.6 h of compressor runtime; both stayed at `0.0 kWh` throughout.

If you want them anyway (harmless, they'll just read `0`), add the same
four-line `capability` and `ha` blocks under each field name.

### Sanity-check after you paste

Two new sensors should appear within ~10 s:

| Field | Expected ballpark |
|---|---|
| `sensor.atelier_midea_power_total_kwh` | Cumulative lifetime usage. A Q11 that's been running for a year is usually 600–1500 kWh. Monotonic — never resets. |
| `sensor.atelier_midea_power_realtime_kw` | `0` when compressor stops. `0.1–0.5 kW` at partial load, `0.8–1.5 kW` at full compressor duty. Tracks `compressor_frequency` sensor. |

If you see `realtime_power_kw` stuck at a large constant (e.g. 6 553 kW)
the decoder picked BCD when it should have picked linear — your cap
`0x16` value is probably not `0`, and this override is wrong for your
firmware.

---

## Related references

- Protocol-level quirks YAML (for CLI workflows with `ac_monitor.py
  --quirks …` and `build_command.py --quirks …`):
  `blaueis-libmidea/packages/blaueis-core/src/blaueis/core/data/device_quirks/xtremesaveblue_q11_power.yaml`
- Linear-encoding formulas: see `encodings:` → `power_linear_4` and
  `power_linear_3` in the glossary.
- How the override mechanism works:
  [glossary_overrides.md](../glossary_overrides.md).
- Why quirks files are not auto-loaded: they're a **knowledge base**,
  not a runtime mechanism. Device variants within a line can have
  incompatible firmware quirks — a visible decode failure on the right
  seam (user-pasted override) beats a silent misdecode on the wrong one
  (auto-loaded quirk).

## Change log

- **2026-04-23** — Initial doc. Q11 characterisation based on Session 15
  probe (2026-04-10, `ac_probe.py`) and 48 h live observation post-deploy.
  Content replaces the orphaned workspace-root `q11_power_override.yaml`.
