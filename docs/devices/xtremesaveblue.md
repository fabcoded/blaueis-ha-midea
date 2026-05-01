# Midea XtremeSaveBlue

One product-line entry. The load-bearing identity at the protocol layer
is the **capability fingerprint** below, not the product name on the
box — two units with the same product label but different firmware can
report different cap shapes, and vice versa.

## Matching — by capability fingerprint

Run [`ac_probe.py`](../../../blaueis-libmidea/packages/blaueis-tools)
against your AC and compare. The override in this doc applies to any AC
that returns **this exact B5 cap map**:

```
tag=0xB5  b5 08 12 02 01 01  14 02 01 01  15 02 01 01
              16 02 01 00  1a 02 01 01  10 02 01 01  25 …
# 8 caps advertised: 0x10 0x12 0x14 0x15 0x16 0x1a 0x25 + one tail cap.
# The load-bearing byte: cap 0x16 = 0x00  ("no power calc")
```

Plus these diagnostic dead-ends (all must hold):

- `msg_type 0x07` device-ID query → all-`0xFF` response (firmware accepts
  the query but doesn't populate a serial / model ID)
- B1 SN8 serial query → empty
- B1 property-key high byte → ignored (8-bit keyspace)

And these behavioural signatures that surface in day-to-day decode:

- `compressor_idle` bit is **inverted** (`1` = idle, `0` = running) —
  OEM mobile app mislabels it as "compressor current"
- Louver swing-angle sensors return constants, not live positions
- Buzzer is globally gated by the display-LED latch
  (`rsp_0xC0 body[14] bits[6:4]`); silent-louver adjustment requires
  toggle-off → `cmd_0xB0` writes → toggle-on
- `rsp_0xA1` heartbeat carries cumulative kWh at `body[1..4]` in linear
  encoding (not BCD, contrary to some published protocol notes)

If your probe matches on the cap map **and** cap `0x16` really is `0`,
the override below applies. If any byte of the cap map differs, this
doc may still approximate-fit, but paste at your own risk — a different
cap shape is a different device at the protocol layer even if the label
matches.

### Observed on

We've confirmed this fingerprint on one physical XtremeSaveBlue-labelled
unit. Other XtremeSaveBlue units (different firmware revisions, different
regional SKUs) may match this fingerprint, partially overlap, or differ
entirely — we don't have evidence either way. If you probe one, please
open an issue with your cap map.

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

Treats cap `0x16 = 0` as if it reported "power available, linear
encoding" — the glossary's `power_cal_non_bcd` branch — so the decoder
extracts `power_total_kwh` from C1-Group-4 `body[4..7]` and
`power_realtime_kw` from `body[16..18]` as 4-byte and 3-byte big-endian
integers divided by 100 and 10 000 respectively. Adds Home Assistant
metadata (`device_class`, `state_class`, `unit_of_measurement`) so the
sensors land in the Energy Dashboard, and `off_behavior: available` so
cumulative readings don't go `unknown` every time the AC cycles off.

### Why only two fields and not all four

The protocol carries two more kWh counters — `power_total_run_kwh`
(`body[8..11]`) and `power_current_run_kwh` (`body[12..15]`) — but on
this fingerprint they stay at `0.0 kWh` regardless of runtime. Observed:
48 h of live capture with 2.6 h of compressor runtime; both flatlined
the whole time. If you want them anyway, add the same `capability` and
`ha` blocks under each field name — they'll just read `0`.

### Sanity-check after you paste

Two new sensors should appear within ~10 s:

| Field | Expected ballpark |
|---|---|
| `sensor.atelier_midea_power_total_kwh` | Cumulative lifetime usage, monotonic. A unit that's been running for a year is usually 600–1500 kWh. Never resets. |
| `sensor.atelier_midea_power_realtime_kw` | `0` when compressor stops. `0.1–0.5 kW` at partial load, `0.8–1.5 kW` at full duty. Tracks `compressor_frequency` sensor. |

If you see `realtime_power_kw` stuck at a large constant (e.g. 6 553 kW)
the decoder picked BCD when it should have picked linear — your cap
`0x16` is probably not `0`, and this override is wrong for your
firmware. Re-probe and compare against the fingerprint above.

---

## Related references

- Protocol-level quirks for CLI workflows (`ac_monitor.py --quirks …`,
  `build_command.py --quirks …`):
  `blaueis-libmidea/packages/blaueis-core/src/blaueis/core/data/device_quirks/xtremesaveblue_q11_power.yaml`
- Linear-encoding formulas: see `encodings:` → `power_linear_4` and
  `power_linear_3` in the glossary.
- How the override mechanism works:
  [glossary_overrides.md](../glossary_overrides.md).
- Why these overrides are not auto-loaded: they're a **knowledge base**,
  not a runtime mechanism. Cap fingerprints within a single product
  label can disagree across firmware revisions — a visible no-op on the
  right seam (user-pasted override) beats a silent misdecode on the
  wrong one (auto-loaded file).

## Change log

- **2026-04-23** — Initial doc. Fingerprint characterisation from
  Session 15 probe (2026-04-10) + 48 h live observation post-deploy.
  Verified cap `0x16 = 0` on one physical XtremeSaveBlue-labelled unit;
  other firmware revisions / regional SKUs in the same product line not
  yet probed.
