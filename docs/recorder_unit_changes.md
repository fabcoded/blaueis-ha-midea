# Recorder: handling the "unit of X cannot be converted" warning

When a glossary edit adds or changes `ha.unit_of_measurement` for a
field that already has long-term-statistics history, HA logs:

```
WARNING (Recorder) The unit of sensor.<entity_id> (<new_unit>)
cannot be converted to the unit of previously compiled statistics
(<old_unit_or_None>). Generation of long term statistics will be
suppressed unless the unit changes back to None or a compatible unit.
Go to https://my.home-assistant.io/redirect/developer_statistics
to fix this.
```

Long-term-stats compilation for the entity is **paused** until you
resolve the issue from **Developer Tools → Statistics** (NOT the
Repairs panel — see "Where to find the Fix" below). Short-term state
history (the last 10 days of raw values) keeps recording — only the
rolled-up hourly/5-minute aggregates pause.

This is benign in itself, but if you don't act on it the entity
disappears from the Energy dashboard, the History/Statistics graphs,
and all `statistics` template helpers that reference long-term data.

## Why it happens

HA's recorder maintains two separate things per stats-eligible entity:

| What | Stored in | Set by |
|---|---|---|
| **Metadata** — `unit_of_measurement`, `state_class`, `has_mean`, `has_sum` | `statistics_meta` table (one row per entity) | First time the entity ever produced stats |
| **Numeric history** — hourly + 5-minute aggregates (min, max, mean, sum) | `statistics` + `statistics_short_term` tables | Continuously appended by the recorder |

The metadata's `unit_of_measurement` is **frozen at first write**.
Subsequent runs of the integration that report a different unit
trigger the warning.

The recorder then checks whether the old↔new units have a registered
**unit converter** (`homeassistant.util.unit_conversion`):

- **Convertible** (e.g. `W ↔ kW`, `°C ↔ °F`, `Wh ↔ kWh`): values are
  converted on the fly. No warning, no issue.
- **Not convertible** (e.g. `None ↔ h`, `None ↔ V`, `% ↔ kWh`):
  compilation pauses, `units_changed` issue raised in the issue
  registry. This is the case we hit by adding
  `unit_of_measurement` to a glossary entry that previously had none.

`source/components/sensor/recorder.py:710-738` is the dispatch.

## Where to find the Fix

**Developer Tools → Statistics tab**, NOT the Repairs panel.

The recorder creates an issue-registry entry with **`is_fixable=False`**
(`recorder.py:783`), which means the Repairs panel surfaces it as an
*informational notification* with **no FIX button**. The actual
remediation lives at:

```
Settings sidebar → 🔧 Developer Tools → Statistics tab
http://<ha-host>:8123/developer-tools/statistics
```

In that table, entities with active `units_changed` issues display a
**⚠️ yellow warning triangle** in the leftmost column. Click the row
→ dialog opens with the Fix buttons.

The warning's `Go to https://my.home-assistant.io/redirect/developer_statistics`
URL points here.

## What the "Fix" dialog offers

The Repairs entry surfaces a wizard with **two or three** buttons,
each mapped to a recorder WebSocket command
(`recorder/websocket_api.py`):

| Button (typical label) | WS command | Effect on numeric history |
|---|---|---|
| **Update statistics metadata** | `recorder/update_statistics_metadata` | Relabels the metadata's `unit_of_measurement` to the new unit. **Numeric history is untouched** — old rows keep their values bit-for-bit, just under the new label. |
| **Delete statistics** | `recorder/clear_statistics` | Drops the entity's rows from `statistics_meta`, `statistics`, and `statistics_short_term`. **Long-term history is wiped**; future stats start fresh under the new metadata. |
| **Convert statistics** *(only when a converter exists)* | `recorder/change_statistics_unit` | Walks every row and applies the unit converter (e.g. multiplies W rows by 0.001 to become kW). **Numerically lossless.** |

For our typical case — old unit `None`, new unit `h` / `V` / `kWh` —
no converter exists, so only the first two buttons appear.

## Decision tree for a glossary unit-add

When you see the warning after promoting a field from no-unit to a
real unit (which is what every entry in
[`disabled_fields.md`](../../../blaueis-libmidea/docs/disabled_fields.md)
re-enable will eventually do, and what
`compressor_cumul_hours` / `outdoor_dc_bus_voltage` /
`outdoor_supply_voltage` did during the 2026-05-01 commit
`86058d7` / `b2599b3`):

1. **Were the historic numeric values already in the new unit, only
   mislabeled?** This is the case whenever the integration's emitted
   scalar didn't change — only `glossary.yaml`'s `ha.unit_of_measurement`
   declaration did. **→ Click "Update statistics metadata"**. Lossless,
   safe, preserves the entire history series.

2. **Did the integration also start scaling the value differently?**
   (e.g. used to emit raw decivolts as `3800`, now emits `380.0` V.)
   The historic numeric series is no longer continuous with the new
   one. **→ Click "Delete statistics"**. The history is misleading;
   discarding is the right call.

3. **Are old and new units convertible** (e.g. `Wh → kWh`)? **→ Click
   "Convert statistics"**. HA does the math.

The risk of clicking the wrong button is **asymmetric**:

- Wrong "Update metadata" → history rows now mislabeled with a unit
  they don't actually represent. Graphs lie until the data ages out.
- Wrong "Delete statistics" → real data discarded; you can't get it
  back without a recorder backup.

When unsure, **prefer "Delete statistics"**. Losing history hurts;
poisoned history that looks valid hurts more.

## Sanity check before clicking

If you want to verify the scalar matches the new unit before clicking
Update, query the recorder DB directly:

```bash
ssh -i /tmp/claude-ha-ssh root@192.168.210.25 \
  "sqlite3 /homeassistant/home-assistant_v2.db \
   \"SELECT ts, mean, max FROM statistics_short_term \
     WHERE metadata_id = (SELECT id FROM statistics_meta \
                          WHERE statistic_id = 'sensor.<entity_id>') \
     ORDER BY ts DESC LIMIT 10;\""
```

(Note: HA stores `start_ts` and `mean` as floats; values match the
integration's emitted scalar at the time the row was compiled.)

If the values look like the new unit (`1234` for hours,
`380` for volts), Update is safe. If they look like a different
unit or scale, Delete.

## Avoiding the warning entirely on first deploy

For NEW fields being classified for the first time (no historic
stats yet), there's no warning — `statistics_meta` is empty so the
first compile writes the new unit cleanly. Risk only applies to
fields that already had long-term stats compiled under the OLD
classification.

## See also

- `glossary_overrides.md` — user-facing per-instance override flow
  (`ha.unit_of_measurement` in an override has the same metadata-vs-history
  consequences as a base-glossary edit).
- `disabled_fields.md` (in `blaueis-libmidea/docs/`) — fields disabled
  pending verification; future re-enables will trip this warning if
  short-term history was already keeping state on the old (None)
  classification.
- `homeassistant.components.sensor.recorder` — `_compile_statistics`
  is the dispatch site for the warning.
- `homeassistant.components.recorder.websocket_api` — `ws_clear_statistics`,
  `ws_update_statistics_metadata`, and the change-unit handler are the
  three commands the Fix wizard maps to.
