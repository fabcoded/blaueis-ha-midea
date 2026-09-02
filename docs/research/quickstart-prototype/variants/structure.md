<!-- variant: structure -->
<!-- structure: {"lives_in": "blaueis-ha-midea/QUICKSTART.md \u2014 a new root-level file in the integration repo (next to README.md and CONTRIBUTING.md), reachable by absolute GitHub URL from the first screen of BOTH READMEs. Not the README itself, not docs/, not the library repo.", "split": "=== blaueis-ha-midea (integration repo; the HACS entry point) ===\n\nQUICKSTART.md (new, root) \u2014 the full page drafted in `markdown`. Owns the stranger's linear path (wire \u2192 gateway \u2192 HACS \u2192 connect \u2192 update) at stranger depth. Hardware facts appear here as a bounded copy of the libmidea reference (see ownership rule below).\n\nREADME.md \u2014 four edits, no new hardware content:\n- `## Quick start` (new, placed directly under the one-line description, before `## What you get`) \u2014 four bullets, one line each: 1. Wire the Pi to the AC's dongle port through a 5 V\u21943.3 V level shifter; 2. Install the gateway on the Pi with one command, keep the PSK the wizard prints; 3. Install the integration via HACS custom repository; 4. Add the integration, enter host/port/PSK. Then: \"Full walkthrough: https://github.com/fabcoded/blaueis-ha-midea/blob/main/QUICKSTART.md\" (absolute URL so it resolves inside the HACS panel).\n- `## Install` \u2014 replace \"HACS (preferred, once published)\" with the three HACS custom-repository steps (add URL as type Integration \u2192 install Blaueis Midea AC \u2192 restart HA); keep the manual git-clone block as a fallback; add the line that blaueis-core/blaueis-client come from PyPI automatically.\n- Config-flow paragraph \u2014 dialog is \"Blaueis Gateway\", fields Host / Port / Pre-shared key, \"the PSK the gateway wizard printed\" (drop `gateway.yaml:psk`); \"Failed to connect\" vs \"Invalid authentication\" one line each.\n- `## Documentation` \u2014 QUICKSTART.md listed first; \"Requires Home Assistant 2024.10+\" line gains \"and HACS\".\n\ndocs/integration.md \u2014 unchanged role (deep reference: entity model, debugging, reload vs restart); QUICKSTART links to it under \"Next\".\n\n=== blaueis-libmidea (library/gateway repo; the Pi) ===\n\nREADME.md `## Quick start` rewritten into four subsections:\n- `### Home Assistant users` \u2014 one line: \"Follow the end-to-end quickstart in blaueis-ha-midea\" + absolute URL; the rest of this section is the same material at reference depth for people using the gateway without HA.\n- `### Hardware` \u2014 five lines: the dongle connector is a 5 V TTL UART at 9600 8N1 (commonly CN3; pin 1 = 5 V, pin 4 = GND, pins 2/3 = data, swap if no reply); Pi UART on header pins 8 (GPIO14 TX) / 10 (GPIO15 RX) = /dev/serial0, Pi 5 needs the uart0-pi5 overlay and /dev/ttyAMA0; a bidirectional 5 V\u21943.3 V level shifter is mandatory; Pi on its own 5.1 V supply, share GND only, never power the Pi from the AC port; \"wiring table and per-model UART steps: docs/operations.md \u00a71\".\n- `### Install the gateway` \u2014 the `releases/latest/download/install.sh` one-liner (replacing the raw-main URL); one line on what it creates (user blaueis-gw, /opt/blaueis-gw, venv, /etc/blaueis-gw/, blaueis-gateway@<instance>, dialout, `blaueis-gw` CLI); one line on the wizard (port, instance name, PSK, WS port, device name \u2014 keep the PSK; it is what HA asks for); the `blaueis-gw` command table (status / logs <i> -f / configure / sudo update [--apply|--rollback] / sudo uninstall).\n- `### Use the client library` \u2014 the existing dev-machine `git clone` + `pip install -e` block, unchanged.\n\ndocs/operations.md \u2014 renumbered so hardware comes first:\n- `## 1. Hardware and UART` (new) \u2014 the canonical wiring table (identical to QUICKSTART \u00a71.4), the power rule (300 mA port vs 100\u2013800 mA Pi), raspi-config Serial Port (login shell No / hardware Yes), per-model notes (Zero W / Zero 2 W / 3 / 4: dtoverlay=disable-bt + systemctl disable hciuart; Pi 5: uart0-pi5 overlay + uart_port: /dev/ttyAMA0), the exclusivity rule (console off, Bluetooth moved, no other UART daemons), and the honest-gap note (no CN3 photo, connector part, or tested shifter part yet).\n- `## 2. Install` (rewritten) \u2014 what the 0.1.0 installer does: release-asset one-liner, checkout pinned to the latest release, venv, /etc/blaueis-gw/, template unit, dialout, `blaueis-gw` symlink, runs the wizard, enables and starts blaueis-gateway@<name> (replaces \"does not start a service\"); Raspberry Pi OS Bookworm or newer / Python 3.11+ (drop Bullseye); git and sudo required.\n- `## 3. systemd layout` \u2014 as today, with `blaueis-gw status` / `blaueis-gw logs <instance> -f` shown as the front door before raw systemctl/journalctl; crash-protection paragraph kept.\n- `## 4. Configuration reference` \u2014 as today, plus: `instances/<name>.yaml` is written by the wizard; example file shows the wizard's keys; `uart_port: /dev/ttyAMA0` called out for Pi 5.\n- `## 5. Updating` \u2014 `sudo blaueis-gw update` / `--apply` / `--rollback` first, with the rule \"gateway and integration share a release number during 0.x \u2014 update both\"; the existing WS-command and SSH/scp paths move under a `### Developer paths` subsection.\n- \u00a7\u00a7 Logs, Troubleshooting \u2014 unchanged.\n\n=== Ownership rule ===\noperations.md \u00a71 is canonical for hardware facts; QUICKSTART.md \u00a71 is the stranger-depth copy. Because both repos ship under the same release number during 0.x, every co-release is the reconciliation point: if the two disagree, operations.md wins and QUICKSTART is corrected in the same release.", "rationale": "1. The stranger lands on the integration README \u2014 HACS renders it in its panel and \"Midea + Home Assistant\" searches find it. The goal (a climate entity) completes in HA. The page that walks end-to-end belongs where the goal completes, and must be one screen-click from the landing page.\n2. Neither README should BE the quickstart. The integration README is a product overview that HACS shows before install; a hardware walkthrough ahead of \"What you get\" is the wrong first screen. The library README serves two audiences (Pi daemon, dev-machine library) plus the package map; a 200-line HA flow does not belong there. A dedicated page gives one linear flow and one place to keep current.\n3. Root-level QUICKSTART.md rather than docs/quickstart.md: visible in the GitHub file list next to README/CONTRIBUTING, stable short URL, and it survives HACS's README-only rendering because the README carries the absolute link.\n4. Bounded duplication is the price of not bouncing the stranger at the hardest step (wiring). What is duplicated is physical constants (pins, voltages, current ratings) and a release-stable one-liner; wizard prompts are described by intent, not verbatim, so the copy does not drift on wording. The 0.x co-release rule already forces both repos to move together, which is the natural sync point.\n5. Rejected alternatives: (a) split by dependency order \u2014 hardware+gateway in libmidea, HA in ha-midea \u2014 sends the stranger across two repos exactly at the wiring step and leaves the HACS-rendered README without the prerequisite that the config flow will demand (a PSK); (b) everything in the libmidea README \u2014 strangers arriving via HACS never see it; (c) quickstart in the library repo's docs/ \u2014 same discoverability problem plus a repo whose primary audience is developers."} -->
<!-- assumptions: Level-shifter reference rails: the fact sheet says 'share GND only' and 'do not power the Pi from the AC port' but not where the shifter's 5 V and 3.3 V references come from. The draft feeds both from the Pi (5 V pin and 3.3 V pin) and leaves CN3 pin 1 unconnected, which keeps 'share GND only' literally true. Pi 3.3 V / 5 V header pin numbers are deliberately not stated (not in the fact sheet). | `dtoverlay=uart0-pi5` as the config.txt line: the fact sheet names the overlay; the `dtoverlay=<name>` syntax is copied from the `disable-bt` line. Also assumed that on a Pi 5 the header UART is still physically on pins 8/10 once the overlay is applied — inferred from 'serial0 is the 3-pin debug header'. | Log-check guidance in §2.2 ('traffic arriving from the AC' vs 'only transmitting') paraphrases operations.md §6 ('if only uart_tx → AC not replying, check wiring polarity'). The exact 0.1.0 log line wording is not in the fact sheet, so the draft describes what to look for rather than quoting a line. | `sudo systemctl restart blaueis-gateway@<name>` for a restart after rewiring comes from operations.md §2; the fact sheet lists no `blaueis-gw restart` subcommand. | `psk:` as the key name in `/etc/blaueis-gw/instances/<name>.yaml`, and that reading it needs sudo, come from operations.md §3 (config reference, 640 permissions); the fact sheet only says the wizard writes that file. | Troubleshooting row 'Gateway won't start → UART not exclusive or port 8765 in use': the fact sheet says the installer warns about exclusivity; the port-in-use cause is from operations.md §6. Both are causes, not fact-sheet-stated symptoms. | Network reachability from HA to the Pi on TCP 8765 is implied by the Host/Port fields, not stated. | Single issue tracker: hardware and gateway questions are routed to blaueis-ha-midea/issues because it is the only tracker in the fact sheet; a libmidea tracker is not referenced. | HACS renders the integration README in its panel and relative links may not resolve there — hence the README pointer uses the absolute GitHub URL to QUICKSTART.md. HACS rendering behaviour is not in the fact sheet. | 'Power everything off before you wire' and 'power down before swapping the data lines' are general safety advice, not fact-sheet items. | The instance-name example `living-room` and the 'four stages' framing are editorial. | Existing public docs contradict the fact sheet in places and need parity updates at 0.1.0 (listed under split): the installer URL (raw main vs releases/latest), 'Bullseye' as supported, 'does not start a service', PSK in `gateway.yaml`, 'once published' wording, and the license line (both READMEs say CC0 1.0 while the fact sheet says MIT). The quickstart follows the fact sheet and omits license entirely; the CC0/MIT discrepancy is flagged for the maintainer, not resolved here. | USB-serial adapters (`/dev/ttyUSB0` appears in the wizard's list) are deliberately not mentioned, to avoid implying tested support with the AC's 5 V UART. -->

# Blaueis Midea — Quickstart

From a Raspberry Pi, a Midea air conditioner and a Home Assistant install to a working climate entity. Four stages, in this order:

| Stage | Where | You end up with |
|---|---|---|
| 1. Wire | AC + Pi | The Pi's UART connected to the AC's dongle port through a level shifter |
| 2. Gateway | Pi | `blaueis-gateway@<name>` running, and a pre-shared key (PSK) in hand |
| 3. Integration | Home Assistant | **Blaueis Midea AC** installed through HACS |
| 4. Connect | Home Assistant | Two devices: your AC and the gateway |

The gateway ([blaueis-libmidea](https://github.com/fabcoded/blaueis-libmidea)) and the integration ([blaueis-ha-midea](https://github.com/fabcoded/blaueis-ha-midea)) are released together under the same version number — 0.1.0 for both. During 0.x you update them together (stage 5).

## Before you start

- **A Raspberry Pi with the 40-pin header.** Any model. Pi 5 needs one extra config line (stage 1.5).
- **Raspberry Pi OS Bookworm or newer.** The gateway needs Python 3.11+; Bullseye ships 3.9 and will not work. `git` and `sudo` must be available.
- **A 5.1 V power supply for the Pi.** The Pi is never powered from the AC (stage 1.2).
- **A bidirectional 5 V ↔ 3.3 V level shifter.** Mandatory. The Pi's UART pins are 3.3 V and are damaged by 5 V; the AC does not answer 3.3 V signalling.
- **A plug or cable that fits your AC's dongle socket.** Stage 1.1 describes the socket; the exact part depends on your unit.
- **Home Assistant 2024.10 or newer** with **HACS** installed.
- **A network path** from Home Assistant to the Pi on TCP port 8765 (the default; you can change it in the wizard).

## 1. Wire the Pi to the AC

Power everything off before you wire.

### 1.1 The AC side: the Wi-Fi dongle connector

Midea indoor units have a connector for the OEM Wi-Fi dongle, commonly labelled **CN3** on the indoor unit's board. Electrically it is a **5 V TTL UART, 9600 8N1**, on four pins:

| CN3 pin | Signal |
|---|---|
| 1 | 5 V |
| 2 | Data — the AC's TX *or* RX (see below) |
| 3 | Data — the other one |
| 4 | GND |

The socket is either **USB-A-shaped** (sometimes keyed so the OEM dongle fits only one way) or a **4-pin JST-XH** header. Which of pins 2 and 3 carries the AC's transmit line is reported differently for different units. Wire it one way; if the gateway never hears from the AC (stage 2.2), swap the two data lines.

> **Honest gap.** We do not yet have a photo or pinout of CN3 on a specific unit, the exact mating connector part, or a tested level-shifter part number. If you identify these for your unit, please open an issue (see *Where to ask*) so they can be added here.

### 1.2 Power: the Pi gets its own supply

- The AC's dongle port is rated **5 V / 300 mA** — the OEM smart kit's rating. A Pi draws **100 mA (Zero) to 800 mA (Pi 5)**.
- **Power the Pi from its own 5.1 V supply. Do not power the Pi from the AC port.**
- Between AC and Pi, **share GND only**. Leave CN3 pin 1 (5 V) unconnected.

### 1.3 The Pi side: the primary UART

| Header pin | GPIO | Direction |
|---|---|---|
| 8 | GPIO14 | TX — Pi → AC |
| 10 | GPIO15 | RX — AC → Pi |

This UART is `/dev/serial0` (on a Pi 5 it becomes `/dev/ttyAMA0` — see 1.5).

### 1.4 Connections through the level shifter

Every data line crosses the shifter: AC signals on its 5 V side, Pi signals on its 3.3 V side. Feed the shifter's 5 V reference from the Pi's 5 V pin and its 3.3 V reference from the Pi's 3.3 V pin, following your shifter's labelling; tie its GND to the shared ground.

| AC CN3 | Level shifter | Pi header |
|---|---|---|
| pin 2 (or 3) — AC TX | 5 V side → 3.3 V side | pin 10 — RX |
| pin 3 (or 2) — AC RX | 3.3 V side → 5 V side | pin 8 — TX |
| pin 4 — GND | GND | GND |
| pin 1 — 5 V | not connected | — |

### 1.5 Give the UART to the gateway

The UART must belong to the gateway alone: serial console off, Bluetooth moved off it on the models listed below, no other serial daemons. The installer warns about this, but cannot fix it for you.

1. `sudo raspi-config` → **Interface Options → Serial Port**. *Login shell over serial:* **No**. *Serial port hardware enabled:* **Yes**.
2. **Pi Zero W, Zero 2 W, 3, 4:** `/dev/serial0` is the mini UART unless Bluetooth is moved off the primary one. Add this line to `/boot/firmware/config.txt`:

   ```
   dtoverlay=disable-bt
   ```

   then run `sudo systemctl disable hciuart`.
3. **Pi 5:** `/dev/serial0` is the 3-pin debug header, not pins 8/10. Add to `/boot/firmware/config.txt`:

   ```
   dtoverlay=uart0-pi5
   ```

   The header UART then appears as `/dev/ttyAMA0` — choose that in the wizard (stage 2.1).
4. Reboot.

## 2. Install the gateway on the Pi

On the Pi (SSH or a local terminal):

```sh
bash -c "$(curl -sL https://github.com/fabcoded/blaueis-libmidea/releases/latest/download/install.sh)"
```

You will be asked for `sudo`. The installer:

- creates the system user `blaueis-gw` and adds it to `dialout`;
- checks out the latest release into `/opt/blaueis-gw` with its own Python venv;
- creates `/etc/blaueis-gw/` for configuration;
- installs the systemd template service `blaueis-gateway@<instance>`;
- links the `blaueis-gw` command into `/usr/local/bin`;
- then starts the setup wizard.

### 2.1 The wizard

The wizard (`blaueis-gw configure`) asks five things:

| Prompt | What to answer |
|---|---|
| Serial port | Pick from the detected list. Header UART: `/dev/serial0`. Pi 5 with the overlay from 1.5: `/dev/ttyAMA0`. |
| Instance name | Lowercase letters, digits, hyphens — e.g. `living-room`. It becomes the service name `blaueis-gateway@living-room`. |
| Pre-shared key (PSK) | Accept the generated 44-character key, or type your own (12 characters minimum). |
| WebSocket port | `8765` unless you have a reason to change it. |
| Device name | How the AC will be named. |

**Write down the PSK the wizard prints.** It is what you type into Home Assistant in stage 4.

The wizard writes `/etc/blaueis-gw/instances/<name>.yaml`; the installer then enables and starts `blaueis-gateway@<name>`.

### 2.2 Confirm the gateway talks to the AC

```sh
blaueis-gw status              # all instances
blaueis-gw logs <name> -f      # follow this instance's log
```

You want to see traffic **arriving from** the AC, not only the gateway sending. If the gateway keeps transmitting and nothing ever comes back:

1. Power down, swap the two data lines (CN3 pins 2 and 3), power up.
2. `sudo systemctl restart blaueis-gateway@<name>` and watch the log again.

Still nothing: check that the AC is powered, that the shifter's rails and GND are connected, and that the port you picked in the wizard is the one you wired (1.5). Run `blaueis-gw configure` again to change the port.

### 2.3 `blaueis-gw` commands you will need later

| Command | Purpose |
|---|---|
| `blaueis-gw status` | State of all instances |
| `blaueis-gw logs <name> -f` | Follow an instance's log |
| `blaueis-gw configure` | Add another instance or edit one (changing the PSK makes HA ask to re-authenticate) |
| `sudo blaueis-gw update` | Check for a newer release; `--apply` installs it; `--rollback` returns to the previous release |
| `sudo blaueis-gw uninstall` | Remove the gateway |

## 3. Install the integration in Home Assistant

1. **HACS → Custom repositories.** Add `https://github.com/fabcoded/blaueis-ha-midea`, type **Integration**.
2. Install **Blaueis Midea AC**.
3. **Restart Home Assistant.**

The Python packages the integration needs (`blaueis-core`, `blaueis-client`) are installed from PyPI automatically when the integration loads — nothing to do by hand.

## 4. Connect Home Assistant to the gateway

1. **Settings → Devices & Services → Add Integration**, search **Blaueis Midea AC**.
2. The dialog is titled **Blaueis Gateway** ("Connect to a Blaueis HVAC gateway running on your network."). Fill in:

   | Field | Value |
   |---|---|
   | Host | The Pi's IP address or hostname, e.g. `gateway.local` |
   | Port | `8765`, or what you chose in the wizard |
   | Pre-shared key (passphrase) | The PSK from stage 2.1 |

3. Submit. The flow tests both the connection and the key:
   - **Failed to connect** — the gateway is unreachable from HA, or gateway and integration are on different versions. Check `blaueis-gw status` on the Pi, the host and port, and stage 5.
   - **Invalid authentication** — the PSK does not match. Lost it? It is the `psk:` line in `/etc/blaueis-gw/instances/<name>.yaml` (needs `sudo` to read), or set a new one with `blaueis-gw configure`.

You get **two devices**:

- **Your AC** — a climate entity (mode, target temperature, fan speed, swing, presets) plus sensors and switches for what the unit supports. Only capabilities the unit advertises appear, so the entity list differs from unit to unit.
- **The gateway** — Pi health sensors and the gateway version (the release tag, e.g. `v0.1.0`).

One config entry per gateway instance. If the gateway's PSK changes later, Home Assistant asks you to re-authenticate.

## 5. Updating: gateway and integration together

During 0.x, gateway and integration must run the same release number. Update both:

- **Pi:** `sudo blaueis-gw update` reports whether a newer release exists; `sudo blaueis-gw update --apply` installs it. Something wrong afterwards: `sudo blaueis-gw update --rollback`.
- **Home Assistant:** update **Blaueis Midea AC** in HACS, then restart HA.

The gateway device in HA shows the gateway's version. **Failed to connect** right after an update usually means only one side was updated.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Gateway log shows only transmits, nothing received | Data pair swapped, AC unpowered, or wrong port picked in the wizard | Swap CN3 pins 2/3; check AC power; `blaueis-gw configure` to change the port (2.2) |
| Gateway won't start | UART not exclusive (serial console, Bluetooth, another daemon), or port 8765 already in use | `blaueis-gw logs <name>` shows the reason; redo 1.5 |
| `Failed to connect` in HA | HA cannot reach the Pi on that port, or gateway/integration versions differ | `blaueis-gw status`; check host/port; stage 5 |
| `Invalid authentication` in HA | Wrong PSK | Re-enter the key the wizard printed (4.3) |
| HA asks to re-authenticate | The gateway's PSK was changed | Enter the new key |
| Fewer entities than expected | The unit does not advertise that capability | Expected — only advertised capabilities become entities |

## Where to ask

Open an issue at <https://github.com/fabcoded/blaueis-ha-midea/issues>. For anything on the HA side, attach the diagnostics bundle: **Settings → Devices & Services → Blaueis Midea → ⋮ → Download Diagnostics**. For wiring and connector questions, a photo of your unit's dongle socket helps everyone who comes after you.

## Next

- The integration README — what the entities are, Blaueis Follow Me, capability detection.
- `docs/integration.md` in blaueis-ha-midea — entity model, debugging, reload vs restart.
- `docs/operations.md` in blaueis-libmidea — gateway configuration reference, systemd layout, logs.
