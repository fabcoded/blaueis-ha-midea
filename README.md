# blaueis-ha-midea

Home Assistant custom integration for Midea air conditioners via a
Blaueis gateway (Raspberry Pi).

**Requires Home Assistant 2024.10+** and a running
[blaueis-libmidea](https://github.com/fabcoded/blaueis-libmidea) gateway on
your network.

## What you get

A single config entry per gateway produces **two HA devices**:

- **AC device** — climate entity with mode, target temperature, fan speed,
  swing, and presets (turbo, eco, sleep, frost protection). Plus individual
  sensors and switches for everything else the unit exposes. Only features
  your AC actually has appear — the integration queries B5 capabilities on
  startup and hides what isn't supported.
- **Gateway device** — Pi health sensors (CPU, RAM, temperature, disk,
  uptime).

### Entity platforms

| Platform | Source | Examples |
|---|---|---|
| Climate | Hardcoded single entity | Mode, temp, fan, swing, presets |
| Sensor | Auto-mapped from glossary | Indoor/outdoor temp, compressor freq, coil temps, energy, error codes |
| Binary sensor | Auto-mapped (read-only bool) | Follow Me status, compressor idle |
| Switch | Auto-mapped (writable bool) | Self-clean, screen display, dry clean |
| Select | Auto-mapped (writable enum) | Breezeless mode, swing angle positions |
| Number | Auto-mapped (slider constraint) | Fan speed fine control, louver angle (1-100) |

### Blaueis Follow Me

Couples any HA temperature sensor to the AC's Follow Me / I Feel function.
The AC uses the external sensor's reading instead of its built-in thermistor
for the control loop.

**Setup:** Settings → Devices & Services → Blaueis Midea → Configure →
pick a temperature sensor. Then enable the "Blaueis Follow Me" switch entity.

**How it works:** A 15-second timer reads the source sensor and sends the
temperature to the AC via the Follow Me protocol frame. Every 30 seconds
it also re-asserts the Follow Me flag as a keepalive. If HA stops or the
connection drops, the AC reverts to its built-in sensor within ~60 seconds
(protocol timeout).

### Capability detection

The integration sends a B5 capability query at startup. The response
determines which features become entities. Standalone entities for fields without B5 confirmation
stay hidden. The climate entity provides basic mode fallbacks
when B5 data is unavailable. The glossary YAML in blaueis-core
defines all known Midea AC fields, their wire encoding, B5 cap IDs, and
HA metadata.

### Engineering telemetry

Beyond the standard climate controls, the integration decodes C1 group
queries (compressor frequency, coil temperatures T1-T4, EEV position, DC
bus voltage, fan speeds, fault flags, runtime counters) and B1 property
responses (louver angles). These appear as sensor entities, many disabled
by default to keep the UI clean.

## Install

**HACS** (preferred, once published): add as a custom source, install
**Blaueis Midea AC**, restart HA.

**Manual:**

```sh
cd /config/custom_components
git clone https://github.com/fabcoded/blaueis-ha-midea.git _tmp
cp -r _tmp/custom_components/blaueis_midea ./
rm -rf _tmp
# restart HA
```

Then **Settings → Devices & Services → Add Integration → Blaueis Midea AC**,
enter host / port / PSK (matching the gateway's `gateway.yaml:psk`).

## Architecture

```
HA  <--WebSocket (AES-256-GCM)--> Pi Gateway <--UART 9600 baud--> AC indoor unit
```

The gateway runs on a Raspberry Pi connected to the AC's CN3 connector,
impersonating the OEM WiFi dongle. The HA integration connects over
encrypted WebSocket — no cloud, no polling delay. State changes push
immediately.

## Documentation

- [docs/integration.md](docs/integration.md) — install, configure, entity model, debugging, reload-vs-restart.
- [Flight recorder design](https://github.com/fabcoded/blaueis-libmidea/blob/main/docs/flight_recorder.md) (in sibling repo) — what the HA "Download Diagnostics" bundle contains.

## Debugging

HA UI → **Settings → Devices & Services → Blaueis Midea → ⋮ → Download
Diagnostics**. The JSON includes both the HA-side and gateway-side
flight-recorder rings, merged by timestamp. Full frame-level capture
with provenance tracking — no need to raise log levels.

## License

[CC0 1.0 Universal](https://github.com/fabcoded/blaueis-libmidea/blob/main/LICENSE) — public-domain dedication. No warranty.
