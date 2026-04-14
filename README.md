# blaueis-ha-midea

Home Assistant custom integration for Midea air conditioners via a
Blaueis gateway (Pi or ESPHome).

**Requires Home Assistant 2024.10+** and a running
[blaueis-libmidea](https://github.com/fabcoded/blaueis-libmidea) gateway on
your network. Status: active, feature-complete — config flow + 5 entity
platforms + diagnostics bundle + in-process flight-recorder.

## What you get

A single config entry per gateway produces **two HA devices**:

- **AC device** — a climate card with all the usual controls (mode, target
  temperature, fan, swing, presets), plus individual sensors and switches
  for everything else the unit exposes. Your AC only shows the features it
  actually has — the integration asks the device and hides what isn't
  supported.
- **Gateway device** — Pi health sensors (CPU, RAM, temperature, uptime)
  from the gateway's `pi_status` broadcast.

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

## Documentation

- [docs/integration.md](docs/integration.md) — install, configure, entity model, debugging, reload-vs-restart.
- [Flight recorder design](https://github.com/fabcoded/blaueis-libmidea/blob/main/docs/flight_recorder.md) (in sibling repo) — what the HA "Download Diagnostics" bundle contains.

## Debugging in one line

HA UI → **Settings → Devices & Services → Blaueis Midea → ⋮ → Download Diagnostics**. The JSON you get back includes both the HA-side and gateway-side flight-recorder rings, merged by timestamp. No need to raise log levels.

## License

Same as the parent library — [CC0 1.0 Universal](https://github.com/fabcoded/blaueis-libmidea/blob/main/LICENSE), public-domain dedication. No warranty.
