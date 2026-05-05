# blaueis-ha-midea — Integration Guide

> Install, configure, troubleshoot. The integration consumes a Blaueis
> gateway over WebSocket and exposes one Midea AC as a first-class Home
> Assistant device. For the library's internal design see
> `../blaueis-libmidea/docs/architecture.md`.

---

## Design philosophy: dual audience by default

The integration deliberately serves two distinct user populations from
the same install, without forcing either to compromise:

1. **The Home Assistant user** who wants their AC to "just work" —
   expose climate, fan, and the handful of toggles a wall remote
   offers, hide the rest, and respect HA conventions (entity
   categories, device classes, state classes for energy and history
   graphs, sensible default-on / default-off).

2. **The HVAC enthusiast, integrator, or protocol researcher** who
   needs unrestricted visibility into the unit's behaviour — every
   capability the firmware advertises, every diagnostic thermistor,
   every byte the field-inventory scan classified as populated, plus
   the tooling to capture and interpret what the wire is carrying.

The reconciliation between these audiences is **structural, not
editorial**. Two independent axes in the glossary, applied in
combination, produce a per-field disposition that lands the field on
the right surface for the right user:

### The two axes

| Axis | Glossary key | Decides |
|---|---|---|
| **Existence + default-active** | `feature_available` | Whether the entity is registered, *and* whether it is enabled by default once registered |
| **Visual placement** | `ha.entity_category` | Where the entity renders on the device card |

These are **independent and combine** — they are not alternatives.
A field can carry zero, one, or both flags.

#### Axis 1: `feature_available` (the integration's gate)

The vocabulary unifies registration with default-enabled state. The
six-value enum encodes both decisions in one key — the `-opt` suffix
on the cap-confirmed and always-readable tiers means "register, but
disabled by default; user opts in via the entity registry."

| Value | Registered? | Enabled by default? | Effect |
|---|---|---|---|
| `never` | No | n/a | Not registered. No HA entity, no state, no row in registry. The field lives in the glossary as documentation; see `disabled_fields.md` (in `blaueis-libmidea`) for the contribution path to promote each. |
| `capability` | Iff B5 cap confirms | Yes | Registered only if the device's B5 capability scan confirms support on this hardware. Once confirmed, fully active. |
| `capability-opt` | Iff B5 cap confirms | **No** | Registered only if cap-confirmed, then registered-but-disabled. Use when the cap is reported but historically misbehaves on the hardware variant ("ignored cap"); user opts in if their unit happens to be one of the working ones. |
| `readable` | Yes | Yes | Always registered (no cap dependency), enabled. |
| `readable-opt` | Yes | **No** | Always registered, **disabled by default**. User flips on via Settings → Devices → Entities. Use for diagnostic readouts that are noisy, irrelevant on most SKUs, or only useful to investigators. |
| `always` | Yes | Yes | Always registered + writable from the start. |

When the value ends in `-opt`, HA stores `disabled_by="integration"`
on the entity registry row. The entity is registered but **HA does
not collect its state** — no poll, no history, no statistics, doesn't
show on any card or in any list of "current entities." It appears in
the entity registry's *disabled* list, where the user can flip it on.
Once enabled, the flag clears and the entity behaves normally.

Think of `-opt` as **"hidden behind a door the user can open"** —
applied when the field's *value* may be irrelevant on a given
hardware variant (humidity sensor not present), confusing (raw
bytes), or noisy in history graphs.

#### Axis 2: `ha.entity_category: diagnostic` (HA presentation level)

The entity is fully alive — state collected, history recorded,
automations work, statistics compile. It just renders under a
collapsible "Diagnostic" subsection of the device card, separate
from the main controls and primary sensors.

Think of this as **"shelf placement on the same display"** — applied
when the value is meaningful and we want history, but the average
user doesn't need it on the front of their device card. Service
technicians, automation authors, and the "show me how the AC is
feeling" user expand the Diagnostic section.

### How the axes combine

| feature_available | entity_category | What the user sees |
|---|---|---|
| `readable` / `always` | (none) | **Primary** — top-level on device card, fully active |
| `readable` / `always` | `diagnostic` | **Diagnostic shelf** — under Diagnostic subsection, fully active |
| `readable-opt` | (none) | **Hidden** — opt-in via registry. Once opt-in: Primary |
| `readable-opt` | `diagnostic` | **Hidden** — opt-in via registry. Once opt-in: Diagnostic shelf |
| `capability` / `capability-opt` | (any) | If B5 confirms: behaves per the same row but with the `-opt` enabled / not-enabled distinction. If not confirmed: not registered |
| `never` | n/a | **Doesn't exist** — glossary documentation only |

### Worked examples

- `target_temperature`, `power`, `operating_mode` — Axis 1 `always`,
  no Axis 2 flag → **Primary**. Folded into the climate entity;
  the user controls them directly.
- `outdoor_temperature` — Axis 1 `readable`, no Axis 2 flag →
  **Primary** standalone sensor. Useful for weather correlations and
  visible by default.
- `compressor_frequency`, `t4_outdoor_ambient_temp` — Axis 1
  `readable`, Axis 2 `diagnostic` → **Diagnostic shelf**. Modulation
  visibility and raw thermistor reading; useful but not what a
  typical user looks at on the front of a device card.
- `humidity_actual` (when uncertain whether the hardware has a
  sensor) — Axis 1 `readable-opt` → **Hidden**. User on a premium
  SKU enables it; user on a basic SKU never sees a no-data-here
  ghost entity.
- `compressor_running` — Axis 1 `readable-opt` → **Hidden**. The
  bit misbehaves on at least one hardware variant
  (XtremeSaveBlue cap-0x16=0 reads body[6]=0 always); leaving it
  disabled-by-default avoids reporting a wrong value on those units.
- `vane_*_angle` (per memory: dead sensors) — Axis 1 `never` →
  **Doesn't exist**. Promoting back requires evidence per
  `disabled_fields.md`.

### What this is NOT

- **Not a permissions model.** Both axes are user-overridable in
  the standard HA UI: the user can enable any `*-opt`-disabled
  entity and expand any Diagnostic shelf via Settings → Devices →
  Entities. The integration's defaults express *expectations*, not
  hard locks. For `feature_available: never`, the path is the
  Glossary-Overrides textarea (see `glossary_overrides.md`) — pin
  the field to `readable-opt` or `readable` per device.
- **Not editorial curation.** No "we don't want users to see this"
  decisions. A field is hidden because either (a) its data is not
  reliable on the available evidence (`feature_available: never`,
  see `disabled_fields.md`), (b) its hardware presence varies across
  SKUs (`feature_available: readable-opt` or `capability-opt`), or
  (c) its information density is too high for the front of a device
  card (`entity_category: diagnostic`). All three conditions are
  documentable; none are taste.

### Tinkerer surfaces

Capability layered on top of, not replacing, the default-clean
experience:

- **`run_field_inventory` HA service** — injects a superset of read
  queries and produces a markdown report of which bytes populate.
  See `field_inventory.md`.
- **Glossary overrides (`glossary_overrides_yaml`)** — per-instance
  YAML patch over the canonical glossary, applied at entry load.
  See `glossary_overrides.md`.
- **Flight recorder** — gateway-side full-frame capture for protocol
  research. See `../blaueis-libmidea/docs/flight_recorder.md`.

The result is **one integration, two surfaces**: the default surface
shaped by what HA users expect on a device card, the investigative
surface one toggle / one menu / one service call away — never deeper,
never present where it would clutter the default view.

---

## 1. Requirements

- Home Assistant 2024.10+ (for `type BlaueisMideaConfigEntry = ConfigEntry[...]` syntax).
- A running Blaueis gateway reachable from the HA host (see `../blaueis-libmidea/docs/operations.md`).
- The gateway's **PSK** — the same value configured in the gateway's `gateway.yaml`.

Python dependencies pulled by the manifest: `websockets>=12.0`, `pyyaml>=6.0`, `cryptography>=41.0`. HA installs these on first entry setup.

---

## 2. Install

### 2.1 HACS (preferred once published)

Add the repository as a custom HACS source, install **Blaueis Midea AC**, restart HA.

### 2.2 Manual

Copy or symlink the component:

```sh
cd /config
mkdir -p custom_components
cd custom_components
git clone https://github.com/fabcoded/blaueis-ha-midea.git _tmp
cp -r _tmp/custom_components/blaueis_midea ./
rm -rf _tmp
```

Or via HAOS SSH — the "Advanced SSH & Web Terminal" add-on (root@host, port 22):

```sh
scp -i <ssh-key> -r custom_components/blaueis_midea \
    root@<ha-host>:/config/custom_components/
```

Restart HA (`ha core restart` — manifest + Python files are picked up at startup).

---

## 3. Configure

1. **Settings → Devices & Services → Add Integration → Blaueis Midea AC**.
2. Fill in:
   - **Host** — gateway IP or mDNS hostname (e.g. `gateway.local`).
   - **Port** — default `8765`.
   - **PSK** — the gateway's shared key (from `/etc/blaueis-gw/instances/<name>.yaml:psk`).
3. The config flow tests TCP + the full crypto handshake before accepting. Failure → `cannot_connect`; check the gateway is running and the PSK matches.

One config entry per gateway instance. Multiple ACs → multiple gateway instances → multiple config entries, all sharing `host`:`port` is rejected (deduped by `(host, port)`).

---

## 4. Entity model

Entities are **B5-gated** — only capabilities the device explicitly advertises become entities. Discovery happens once at startup; the list is cached until reconnect.

### 4.1 Platforms and how fields map

| Platform | Glossary class | Writable | Read-only |
|---|---|---|---|
| `climate` | folded aggregate | — | always 1 per entry |
| `switch` | `stateful_bool` | ✓ | — |
| `binary_sensor` | `stateful_bool` | — | ✓ |
| `select` | `stateful_enum` | ✓ | — |
| `sensor` | `stateful_enum`, `stateful_numeric`, `sensor` | — | ✓ |
| `number` | `stateful_numeric` (slider in `active_constraints`) | ✓ | — |

Source: `const.py:FIELD_CLASS_MAP`.

> **Two entities for one field is intentional** when a `stateful_enum`
> field's cap declares both a `values` block and a `slider` block —
> e.g. `louver_swing_angle_lr_enum`, which exposes five labelled
> positions plus a continuous 1–100 range. Both a `select` (dropdown
> of the labelled positions) and a `number` (free-range slider) are
> registered. The dropdown serves the "snap to a standard position"
> intent; the slider serves the "park at a specific raw" intent
> (useful for off-grid positions an external controller has set, or
> fine-grained scripting). Both write to the same wire field; the
> AC's snap behaviour decides where the vane physically lands.
> Hiding either would lose a legitimate interaction surface.

### 4.2 The `climate` entity

A single aggregate entity, unlike the per-field entities above. Absorbs fields listed in `CLIMATE_EXCLUSIVE_FIELDS`:

- `operating_mode` → HVAC mode (auto / cool / dry / heat / fan_only).
- `target_temperature` → target_temp.
- `fan_speed` → fan_mode (mapped via `DEFAULT_FAN_PRESETS` → auto / low / medium / high).
- `indoor_temperature` → current_temp (also surfaced separately as a `sensor`).
- `swing_vertical`, `swing_horizontal` → swing_mode.
- Preset fields (`turbo_mode`, `eco_mode`, `sleep_mode`, `frost_protection`) → HA preset.

Callback fields — changes to any of `CLIMATE_CALLBACK_FIELDS` refresh the climate entity state.

### 4.3 Display & Buzzer mode select

A synthetic `select` entity (separate from glossary-derived selects) replaces the would-be `screen_display` switch on devices that advertise the cap. Four options: `on` / `off` / `forced_on` / `forced_off`. The forced modes run an active-driving enforcer that re-asserts the chosen state when the AC drifts (e.g. someone presses the LED button on the remote), with a 15 s cooldown. The forced policy is persisted in the config entry's `options` and survives restarts. Full design + UX rationale in [`display_buzzer_mode.md`](display_buzzer_mode.md); ingress-hook + write-lock plumbing in [`architecture.md`](architecture.md).

### 4.4 Two HA devices per config entry

- **AC device** (`"{host}:{port}_ac"`) — carries the climate entity + all AC sensors / switches / selects.
- **Gateway device** (`"{host}:{port}_gw"`) — carries Pi health sensors (CPU, RAM, temp, uptime) from the gateway's `pi_status` broadcast.

This matches the physical topology: two distinct pieces of hardware, each with its own model / sw_version / configuration_url.

---

## 5. Flight recorder — the debugging path

Every config entry gets a 5 MB in-memory rolling debug buffer attached to the integration's loggers at VERBOSE level. `homeassistant.log` is **unaffected** — filters at its own level. Design: `../blaueis-libmidea/docs/flight_recorder.md`.

### 5.1 Pull the bundle

**Settings → Devices & Services → Blaueis Midea AC → ⋮ → Download Diagnostics**.

File contents (redacted):

```json
{
  "entry": {"title": "...", "host": "...", "port": 8765},
  "gateway_info": {"version": "...", "device_name": "...", "instance": "..."},
  "gateway_session": {"sid": 2, "pool_size": 8, "connected_wall": ..., "next_req_id": ...},
  "local_ring": {"enabled": true, "size_bytes": ..., "record_count": ...},
  "gateway_ring": {"record_count": ..., "parsed_record_count": ...},
  "combined_records": [ /* sorted by ts across both rings */ ]
}
```

Fields redacted: `psk`, any `token`, any `password`.

### 5.2 What's in `combined_records`

One JSON object per event, schema in `flight_recorder.md` §4.3. Minimum filter: `jq '.combined_records[] | select(.event=="uart_rx" or .event=="uart_tx")'`.

Useful filters:

```sh
# All frames caused by HA, with their replies:
jq '.combined_records[] | select(.origin == "ws:0" or .reply_to.origin == "ws:0")' dump.json

# Timing between sending a command and getting a reply:
jq '.combined_records[] | select(.event=="uart_rx" and .reply_to) | {ts,msg_id,reply_to}' dump.json

# Connection events (who connected/disconnected when):
jq '.combined_records[] | select(.event=="ws_connect" or .event=="ws_disconnect")' dump.json
```

### 5.3 Failure modes of the bundle

| `gateway_ring.error` | Meaning |
|---|---|
| `"gateway not connected"` | Integration's WS is down; local ring still delivered |
| `"gateway did not respond within 10 s"` | Gateway alive but slow — try again, check `pi_status` CPU |
| `"<ExceptionType>: ..."` | Unexpected — local ring still delivered; attach to bug report |

---

## 6. Reloading vs restarting

Two flavours, pick by what you changed.

| Changed | Action | HA downtime |
|---|---|---|
| HA **UI config** (host / port / PSK) | Settings → ⋮ → Reload | ~1 s, only this integration |
| Glossary overrides (Configure dialog YAML) | Reload config entry | ~1 s |
| Any `.py` file in `custom_components/blaueis_midea/**` | `ha core restart` | 30–60 s, whole HA |
| Any `.py` in vendored `lib/blaueis/**` | `ha core restart` | Same |
| Bundled `glossary.yaml` (libmidea data) | `ha core restart` | Same |
| New platform added (e.g. adding `number.py`) | `ha core restart` | Same |

> The bundled glossary is parsed once per process and cached in
> `blaueis.core.codec._glossary_cache` — there is no live-reload path
> for it. Glossary *overrides* (the YAML pasted into the Configure
> dialog, persisted in the config entry's options) are re-read on
> entry reload and don't need a restart.

A long-lived HA access token (keep it in a local, gitignored file — or
export via `HA_TOKEN` in your shell) lets you drive runtime operations
without a Python reload. Scripted shortcut:

```sh
TOKEN=$(cat <ha-token-file>)       # or: TOKEN=$HA_TOKEN
ENTRY_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  http://<ha-host>:8123/api/config/config_entries/entry \
  | jq -r '.[] | select(.domain=="blaueis_midea").entry_id')

curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://<ha-host>:8123/api/services/homeassistant/reload_config_entry \
  -d "{\"entry_id\": \"$ENTRY_ID\"}"
```

**Rule of thumb:** Python file changes and bundled-glossary edits need
`ha core restart`. Config-entry options (host/port/PSK, glossary
overrides) and runtime state / service calls are token-driven via the
REST API. Avoiding unnecessary restarts matters — HA takes 30–60s to
come back and interrupts every other integration.

---

## 7. Troubleshooting

### 7.1 `cannot_connect` on config flow

- Gateway not running: `ssh hvac@<gateway-host> sudo systemctl status blaueis-gateway@<instance>`.
- PSK mismatch: crypto handshake fails silently on the wire — check journal for `HandshakeError`.
- Firewall: `nc -zv <gateway-host> 8765` from the HA host.
- Wrong port: default is `8765`.

### 7.2 Integration loads but no entities appear

- The device hasn't completed B5 discovery yet — wait ~30 s.
- Check `homeassistant.log` filter `blaueis_midea`.
- Download diagnostics → look for `uart_tx` with `msg_id=0xb5` and a `reply_to.confidence=="confirmed"` on the matching `uart_rx`. If no reply, the AC doesn't implement that capability query (rare).

### 7.3 Entities appear but state doesn't update

- Ring → look for `ws_in` events with `ctx.type=="frame"` at steady rate. If only `ws_out` (commands going in) but no `ws_in` frames, the WS subscription has gone sideways — reload the entry.
- Check `pi_status` broadcasts (every 60 s) are arriving; if yes, connection is alive and the issue is at the AC (power off?).

### 7.4 Changes to `.py` not picking up

- Reload does **not** reload Python modules (HA/Python caches them). Full `ha core restart` required. This is noted in the workspace memory too.

### 7.5 Slot-pool exhaustion

`{"code":"slot_pool_full"}` error → more than `slot_pool_size` (default 8) concurrent WS clients on the gateway. Usually a stuck test client. Close idle clients, or raise the pool in gateway config. See `../blaueis-libmidea/docs/operations.md` §3.2.

---

## 8. What's where, one-liner reference

| I want to… | Look at |
|---|---|
| Understand WS messages | `../blaueis-libmidea/docs/ws_protocol.md` |
| Tune the gateway or debug a gateway crash | `../blaueis-libmidea/docs/operations.md` |
| Understand the flight recorder schema | `../blaueis-libmidea/docs/flight_recorder.md` |
| Know what `frame_spacing_ms=150` means | `../../blaueis-hvacshark-traces/data-analysis/midea/uart/timing-analysis.md` |
| Extend the integration (new entity type, new glossary field) | `custom_components/blaueis_midea/` + `../blaueis-libmidea/docs/architecture.md` §4 |
| See which glossary fields my AC actually populates | [field_inventory.md](field_inventory.md) — button / service / CLI |
| Find a copy-paste override for a hidden-but-populated field | [field_inventory.md](field_inventory.md) §"Suggested override snippets" |
| Configure Display & Buzzer behaviour | [display_buzzer_mode.md](display_buzzer_mode.md) |
| Build a new active-driving feature (ingress hooks) | [architecture.md](architecture.md) |
| SSH / token / update workflow | Workspace root `AGENTS.md` |
