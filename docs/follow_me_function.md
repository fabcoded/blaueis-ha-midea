# Follow Me Function

> The AC uses an HA temperature sensor instead of its built-in thermistor.
> Persistent across HA restarts. Guards and safety timeout protect against
> sensor failures and misconfigured readings.

---

## 1. What it does

Follow Me (Midea's "I Feel" function) overrides the AC's internal temperature
sensor with an external reading. The AC regulates to the setpoint using the
external temperature instead of the thermistor on the indoor unit.

The **Follow Me Function** is the HA integration layer that manages this:

- **Persistent** — survives HA restarts. Toggle state stored in config entry
  options, auto-started on boot when enabled.
- **Guarded** — configurable temperature bounds reject implausible readings.
- **Watchdog** — stale sensor detection disables Follow Me until the sensor
  recovers.

---

## 2. How it works — two-layer architecture

Follow Me requires two independent protocol mechanisms running simultaneously:

### Layer 1: Data Plane — shadow register (Device poll loop)

The Device class polls the AC every ~15 seconds via `cmd_0x41`. When the
Follow Me shadow register is armed, the poll frame is patched to carry the
sensor temperature:

```
Shadow armed:
  body[1]=0x81  body[4]=0x01 (optCommand=Follow Me)  body[5]=T*2+50
  → AC responds rsp_0xc0 with follow_me=true + indoor_temp

Shadow cleared:
  body[4]=0x03 (standard status query, no FM data)
  → AC responds rsp_0xc0, follow_me decays to false within ~60s
```

The shadow register is written by the Follow Me Manager (`set_follow_me_shadow`)
and cleared on stop or temp-disable (`clear_follow_me_shadow`). While engaged,
the manager writes it on every 30 s tick and also as soon as the source sensor
changes state, so a new reading goes out with the next poll (at most ~15 s).
The state-change path only refreshes the shadow; it never sends a 0x40 frame
and never decides temp-disable or recovery, which stay on the tick.

### Layer 2: Control Plane — 0x40 SET (Follow Me Manager)

The 0x40 SET frame carries the Follow Me enable/disable flag (`body[8] bit 7`).
This is event-driven, not periodic:

- **Hello** (`follow_me=True`) sent on:
  - Initial activation
  - Recovery after temp-disable (sensor came back)
  - Every 30s tick IF AC C0 readback shows `follow_me=false`
    (e.g. after AC power cycle)

- **End** (`follow_me=False`) sent on:
  - User toggle off
  - Sensor goes stale / out of guard range (temp-disable)
  - Every 30s tick IF AC still reports `follow_me=true` after End was sent

### State machine

```
                    ┌─────────────────────────┐
        user ON     │     IDLE                │     user OFF /
     ┌─────────────>│ shadow: cleared         │<────options disabled
     │              │ 0x40: none              │
     │              └─────────────────────────┘
     │                         ▲
     │                         │ AC confirms off
     │              ┌──────────┴──────────────┐
     │              │    DISENGAGING          │
     │              │ shadow: cleared         │
     │              │ 0x40: follow_me=False   │
     │              │   every 30s until       │
     │              │   AC confirms off       │
     │              └─────────────────────────┘
     │                         ▲
     │                         │ user OFF
     ▼                         │
┌────┴────────────────────────┴┐
│         ENGAGED              │───── sensor lost/stale/OOR ────┐
│ shadow: armed (temp)         │                                │
│ 0x41: FM frame every 15s    │     ┌──────────────────────┐   │
│   (automatic via poll)       │     │   TEMP-DISABLED      │   │
│ 0x40: follow_me=True        │     │ shadow: cleared      │   │
│   only if AC doesn't confirm│     │ 0x40: follow_me=False│   │
│   (checked every 30s tick)   │     │ polls: standard query│   │
│                              │<────│                      │   │
└──────────────────────────────┘     └──────────────────────┘<──┘
          sensor recovered               sensor still bad:
          → re-arm shadow                  stay here, no action
          → send 0x40 hello
          → resume ENGAGED logic
```

---

## 3. Configuration — two-flag safety design

Follow Me overrides the AC's own thermistor with an external sensor. A
misconfigured external sensor (wrong room, wrong unit, dead battery)
can drive heating / cooling badly. To make accidental activation
hard, the integration uses **two distinct flags** plus the sensor +
guard configuration. Both flags persist across HA restarts.

Open **Settings > Devices & Services > Blaueis Midea AC > Configure**.

| Option | Storage key | Label | Default | Description |
|---|---|---|---|---|
| Configured | `follow_me_function_configured` | "Follow Me — Configured" | `false` | Master availability. Are you set up and ready to use this feature? Hides/shows the on/off switch on the device card. |
| Enabled | `follow_me_function_enabled` | "Follow Me — Enabled" | `false` | Engage state. Same persistent flag as the on/off switch on the device card — change either, the other reflects it. |
| Sensor | `follow_me_function_sensor` | "Follow Me — Temperature sensor" | — | HA temperature-class sensor entity. |
| Guard min | `follow_me_function_guard_temp_min` | "Follow Me — Minimum temperature guard (°C)" | `-15` | Lower temperature bound (°C). Range -40..10. |
| Guard max | `follow_me_function_guard_temp_max` | "Follow Me — Maximum temperature guard (°C)" | `40` | Upper temperature bound (°C). Range 25..50. |
| Timeout | `follow_me_function_safety_timeout` | "Follow Me — Sensor timeout (seconds)" | `900` | Max time since the sensor last reported, in seconds. Range 60..3600. At least 2.2 × the sensor's report interval. |

The two flags do different jobs:

| Flag | Storage key | Role | Surface |
|---|---|---|---|
| Configured | `follow_me_function_configured` | "Is this feature set up and ready?" | Configure menu only |
| Enabled | `follow_me_function_enabled` | "Is Follow Me running right now?" | Configure menu **and** the on/off switch on the device card |

### Lifecycle of the on/off switch

```
Configured           Enabled             What you see
──────────           ──────────          ─────────────────────────────
False                any                 (no switch — entity purged
                                          from the registry; queries
                                          for the entity_id return
                                          404 / "not found")

True                 False               Switch visible, OFF
                                          (manager idle)

True                 True
   sensor unset      —                   Switch visible, "Unavailable"
                                          (configured but no source)

True                 True
   sensor set
   AC powered off    —                   Switch visible, "Unavailable"

True                 True
   sensor set
   AC on, gateway up —                   Switch visible, ON
                                          (manager engaged)
```

The switch is **registered only while Configured is on**. Toggling
Configured off purges the entity registry entry (graceful: the
switch's `async_will_remove_from_hass` stops the FM manager); toggling
it back on dynamically re-adds the switch via the
`async_add_entities` callback that the switch platform stashes on the
coordinator at setup. The `unique_id` is stable
(`{entry_id}_blaueis_follow_me`), so HA re-uses the same
`entity_id` across the round-trip — automations and dashboards that
reference the entity_id stay valid as long as Configured is on when
they fire. See `_sync_fm_switch_registration` in `__init__.py`.

### Boot / reconnect handshake

When HA (re)connects to the gateway, the device library defers firing
its `on_connected` callback until **after the first `rsp_0xc0` has been
ingested**. The switch's `available` therefore only flips True once
`device.read("power")` (and the rest of the C0 fields) have real
values — there is no "available with stale/unknown values" window for
monitoring or automations to trip on at startup or after a gateway
reconnect.

If the AC is silent (e.g. powered off at the breaker, gateway up but
UART quiet), the handshake falls through after `INITIAL_STATUS_TIMEOUT`
(3.0s) and `on_connected` fires anyway — HA still learns about the
connection so device-card entities stop showing the disconnect-side
"Unavailable". See `_post_connect_init` in `blaueis.client.device`.

### Coupling between menu and device card

The menu's "Enabled" and the on/off switch on the device card both
read and write `follow_me_function_enabled`. Either changes:

- the other reflects on next refresh
- `_async_options_updated` sees the flip and starts/stops the manager
  (when `Configured AND Enabled AND sensor` evaluates true/false)
- the new value persists to entry options → survives HA restart

Auto-start on boot fires when `Configured AND Enabled AND sensor` are
all set.

### Invariant: Configured ⇒ Enabled

When the user unticks **Configured**, `_enforce_fmf_invariant` writes
`Enabled = False` back to the entry options before the FM manager and
the visibility helper run. The persisted state always satisfies
`Configured=False ⇒ Enabled=False`, so re-ticking Configured later
does not silently re-arm Follow Me from a stale Enabled flag — the
user must explicitly tick Enabled again. The same check runs at
`async_setup_entry` so a hand-edited or pre-invariant `core.config_entries`
file gets normalised on the next HA boot.

### Legacy key migration (one-shot, automatic)

Pre-rename installs used `follow_me_function_enabled` for the master
flag and `follow_me_function_armed` for engage. `_migrate_fmf_keys` at
setup_entry time renames both, in order, preserving the user's
existing values. Idempotent: a second call is a no-op.

---

## 4. Safety mechanisms

### Temperature guards

Guards reject readings outside `[guard_min, guard_max]` (both in °C). When a
reading is rejected, Follow Me is temporarily disabled until a valid reading
returns.

**Conversion order matters**: °F→°C conversion happens BEFORE the guard check.
This catches a common misconfiguration:

| Scenario | Raw value | After conversion | Guard result |
|---|---|---|---|
| Normal °C sensor | 22.0 °C | 22.0 | Pass |
| Normal °F sensor | 72.0 °F | 22.2 °C | Pass |
| Misconfigured (°F reported as °C) | 72.0 °C | 72.0 | **Rejected** (> 40) |

### Sensor staleness timeout

If `state.last_reported` is older than `safety_timeout` seconds, the reading
is rejected. This catches sensors that stop updating (e.g. dead battery,
disconnected Zigbee device) without changing their state to "unavailable".

The check uses `last_reported`, not `last_updated`: Home Assistant moves
`last_updated` only when the value changes, so a sensor that keeps reporting
the same reading would look stale and trip the watchdog. `last_reported` moves
on every state write, changed or not. A source entity that holds a value must
therefore still write its state at least once per timeout.

Choose the timeout as at least 2.2 × the sensor's report interval, so a single
missed report does not trip it. The default is 900 s, which covers sensors
that report every 5 min (common for battery Zigbee and Matter sensors).
300 s only suits sensors that report faster than about every 2 min.

**Takeaway from the field (2026-10-25):** the earlier default of 300 s was too
short for a typical battery sensor. The source in one installation (IKEA
TIMMERFLOTTE over Matter) reports every 293 s and skips about every 30th
report. With 300 s the watchdog disabled Follow Me 25 times in three days
(2/4/9/10 per day), each for 4.5 to 5 min. On every fallback the AC jumps to
its own sensor (mounted high, 2 to 3.5 K warmer) and adds its +1.5 K
compensation to the set point; at T1 ≥ Tsc + 2 K it stops the compressor at
once, so 9 of those fallbacks cost a compressor stop plus a cold restart.
With the timeout at 900 s no fallback was seen. This led to the 900 s default,
the 2.2 × rule above and the WARNING level for a temp-disable.

### Protocol range clamping

After guard check, values are clamped to `[0, 50]°C` for the wire protocol.
A reading of -10°C (within guards) is sent to the AC as 0°C. The AC protocol
cannot represent temperatures outside this range.

---

## 5. Naming convention

Two distinct layers share the "follow me" name but serve different purposes:

| Layer | Name | Entity | Scope |
|---|---|---|---|
| Protocol / data | `follow_me` | Binary sensor (read-only) | AC's protocol bit from C0 response |
| HA feature | Follow Me Function | Switch (read-write) | State machine, config, manager |

Config option keys all share the `follow_me_function_` prefix so they sort
together in the config entry options dict.

---

## 6. Troubleshooting

### Log lines

| Level | Message | Meaning |
|---|---|---|
| INFO | "Follow Me Function started, source=..." | Activation (manual or auto-start) |
| INFO | "Follow Me Function: sensor recovered, re-enabling" | Temp-disable cleared |
| INFO | "Follow Me Function confirmed off by AC" | Disengage complete |
| WARNING | "sensor lost/out-of-range/stale, temporarily disabling" | Watchdog triggered |
| ERROR | "AC does not confirm follow_me, re-sending hello" | AC power cycle recovery |
| ERROR | "AC still reports follow_me after end, re-sending" | Disengage retry |

### Common scenarios

**Sensor lost**: Integration logs WARNING, clears shadow, sends End frame. Switch
stays ON (persistent intent). When sensor returns, shadow re-armed + hello sent.

**AC power cycle**: AC loses follow_me state. Next 30s tick detects disagreement,
re-sends hello. Shadow register ensures next 15s poll carries the temperature.
Full recovery within 30s.

**Stale sensor**: No state report from the sensor for > `safety_timeout`
seconds. Same behavior as sensor lost — temp-disable until the sensor reports
again. If this repeats for a sensor that is working, the timeout is shorter
than its report interval allows; see "Sensor staleness timeout".

### Diagnostics

In the flight recorder bundle (**Settings > Devices & Services > Blaueis Midea
AC > ... > Download Diagnostics**), look for:

- `cmd_0x41` frames with `body[4]=0x01` — Follow Me data plane active
- `rsp_0xc0` with `follow_me` field — AC readback
- Transition from `body[4]=0x01` to `body[4]=0x03` — shadow cleared (temp-disable)

---

## 7. Protocol reference

For the full R/T bus analysis including frame captures and timing, see
`blaueis-hvacshark/protocols/midea/analysis/analysis_follow_me_serial.md`.

### Frame format (cmd_0x41 Follow Me query)

Built by patching the standard status query (`build_status_query()`):

```
Byte offset   Field           Value
[10]          cmd             0x41
[11]          body[1]         0x81 (standard query marker — MUST be 0x81)
[13]          body[3]         0xFF
[14]          body[4]         0x01 (optCommand = Follow Me)
[15]          body[5]         T*2+50 (temperature encoding)
[-2]          CRC-8           recalculated over body
[-1]          frame checksum  recalculated over full frame
```

### Shadow register lifecycle

```
set_follow_me_shadow(celsius)   → arms shadow, next poll sends FM frame
clear_follow_me_shadow()        → clears shadow, next poll sends standard query
follow_me_shadow_active         → property: True if shadow is armed
```

The shadow is managed exclusively by `BlauiesFollowMeManager`. Direct
manipulation from other code is not supported.
