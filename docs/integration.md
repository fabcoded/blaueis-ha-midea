# blaueis-ha-midea — Integration Guide

> Install, configure, troubleshoot. The integration consumes a Blaueis
> gateway over WebSocket and exposes one Midea AC as a first-class Home
> Assistant device. For the library's internal design see
> `../blaueis-libmidea/docs/architecture.md`.

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

Or via HAOS SSH (see `../../AGENTS.md` §"Home Assistant access"):

```sh
scp -r custom_components/blaueis_midea \
    root@192.168.210.25:/config/custom_components/
```

Restart HA (`ha core restart` — manifest + Python files are picked up at startup).

---

## 3. Configure

1. **Settings → Devices & Services → Add Integration → Blaueis Midea AC**.
2. Fill in:
   - **Host** — gateway IP (e.g. `192.168.210.30`).
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
| `number` | `stateful_numeric` | ✓ (future) | — |

Source: `const.py:FIELD_CLASS_MAP`.

### 4.2 The `climate` entity

A single aggregate entity, unlike the per-field entities above. Absorbs fields listed in `CLIMATE_EXCLUSIVE_FIELDS`:

- `operating_mode` → HVAC mode (auto / cool / dry / heat / fan_only).
- `target_temperature` → target_temp.
- `fan_speed` → fan_mode (mapped via `DEFAULT_FAN_PRESETS` → auto / low / medium / high).
- `indoor_temperature` → current_temp (also surfaced separately as a `sensor`).
- `swing_vertical`, `swing_horizontal` → swing_mode.
- Preset fields (`turbo_mode`, `eco_mode`, `sleep_mode`, `frost_protection`) → HA preset.

Callback fields — changes to any of `CLIMATE_CALLBACK_FIELDS` refresh the climate entity state.

### 4.3 Two HA devices per config entry

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
| `const.py`, glossary YAML (declarative data) | Reload config entry | ~1 s |
| Any `.py` file in `custom_components/blaueis_midea/**` | `ha core restart` | 30–60 s, whole HA |
| Any `.py` in vendored `lib/blaueis/**` | `ha core restart` | Same |
| New platform added (e.g. adding `number.py`) | `ha core restart` | Same |

The token-driven API shortcut (avoids UI round-trip, useful for scripted debugging):

```sh
TOKEN=$(cat ~/ha.token)
ENTRY_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  http://192.168.210.25:8123/api/config/config_entries/entry \
  | jq -r '.[] | select(.domain=="blaueis_midea").entry_id')

curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://192.168.210.25:8123/api/services/homeassistant/reload_config_entry \
  -d "{\"entry_id\": \"$ENTRY_ID\"}"
```

(Full context + when-which-mechanism in the workspace `AGENTS.md` under "Home Assistant access".)

---

## 7. Troubleshooting

### 7.1 `cannot_connect` on config flow

- Gateway not running: `ssh hvac@192.168.210.30 sudo systemctl status blaueis-gateway@atelier`.
- PSK mismatch: crypto handshake fails silently on the wire — check journal for `HandshakeError`.
- Firewall: `nc -zv 192.168.210.30 8765` from HA host.
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
| Know what `frame_spacing_ms=150` means | `../../HVAC-shark-dumps/data-analysis/midea/uart/timing-analysis.md` |
| Extend the integration (new entity type, new glossary field) | `custom_components/blaueis_midea/` + `../blaueis-libmidea/docs/architecture.md` §4 |
| SSH / token / update workflow | Workspace root `AGENTS.md` |
