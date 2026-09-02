<!-- variant: stranger -->
<!-- structure: {"lives_in": "blaueis-ha-midea/QUICKSTART.md (repo root), linked as the first call-to-action from the top of BOTH READMEs (\"New here? Follow the Quickstart\") and from blaueis-libmidea/docs/operations.md \u00a71. The HA integration repo is the one a stranger reaches first (HACS renders its README; the issue tracker named in the fact sheet lives there), so the end-to-end page sits where the stranger lands and stays one page, even though three of its four parts are gateway-side.", "split": "QUICKSTART.md (ha-midea root) = the only end-to-end path: hardware \u2192 Pi UART prep \u2192 gateway one-liner + wizard \u2192 HACS \u2192 config flow \u2192 checkpoints \u2192 \"when it does not work\" table \u2192 update/uninstall. blaueis-ha-midea/README.md = what you get (entities, two devices), one-paragraph Getting started that links to QUICKSTART.md, HACS install in three lines (drop the \"once published\" wording and move the manual git-clone install to docs/integration.md), architecture line, docs index, diagnostics, acknowledgments. blaueis-libmidea/README.md = package table, gateway one-liner (URL updated to releases/latest/download/install.sh) + \"for the full hardware-to-HA path see the Quickstart\" link, developer install, tests, docs index. blaueis-libmidea/docs/operations.md = the gateway reference (what the installer creates, blaueis-gw CLI, config keys, systemd, update/rollback, troubleshooting); \u00a71 gets the new URL, the wizard, and the fact that the installer now enables and starts the instance; it links to the Quickstart for the hardware/UART preparation instead of repeating it. Rule: hardware pinout, UART prep, and the step-by-step live ONLY in QUICKSTART.md; the READMEs point, operations.md explains.", "rationale": "One page beats two half-pages for the stranger test: the hand-off between repos is exactly where a first-timer gets lost. Putting it in ha-midea matches the entry point (HA user searching for a Midea integration, HACS showing that README) and the issue tracker. The READMEs shrink to orientation + link so there is one place to keep in sync when the installer or config flow changes; operations.md remains the authoritative gateway reference and is not duplicated. Alternative considered: blaueis-libmidea/docs/quickstart.md (closer to the installer code, which changes most often) \u2014 rejected because the stranger does not start there and the page would then have to link forward into a second repo for the HA half."} -->
<!-- assumptions: Pi header pin numbers not in the fact sheet: pin 6 = GND and pin 1 = 3.3 V (standard 40-pin header). The fact sheet only names pins 8 and 10. Confirm before publishing or drop the numbers and say 'a GND pin' / 'a 3.3 V pin'. | Level-shifter reference wiring (AC 5 V to the HV reference pin, Pi 3.3 V to the LV reference pin, common GND, one channel per data direction) is generic level-shifter usage, not stated in the fact sheet. The fact sheet's 'share GND only' is interpreted as 'do not connect the AC's 5 V to the Pi'; the 5 V line still has to reach the shifter's HV reference. | The 'measure 5 V between pin 1 and pin 4 with a multimeter before connecting the Pi' check and 'unplug the indoor unit from mains before opening it' are general electrical-safety advice added for the stranger, not fact-sheet items. | The Pi 5 overlay is written as the config.txt line 'dtoverlay=uart0-pi5'; the fact sheet only says 'the uart0-pi5 overlay'. Same for 'dtoverlay=disable-bt' written via an echo >> append — the fact sheet gives the line but not a command. | 'Other models with the 40-pin header — no extra step' is inferred from the fact sheet listing only Zero W / Zero 2 W / 3 / 4 as needing Bluetooth moved and Pi 5 as special. | The raspi-config prompt wording ('Would you like a login shell to be accessible over serial?' / '...serial port hardware to be enabled?') is quoted from memory of raspi-config; the fact sheet gives only 'login shell NO, serial hardware YES'. | Commands 'sudo apt install git', 'hostname -I', 'cat /proc/device-tree/model', 'grep VERSION_CODENAME /etc/os-release' are standard Raspberry Pi OS / Linux and not in the fact sheet. | The exact wizard question order and prompt phrasing are assumed; the fact sheet lists the questions but not their wording. 'Press Enter to generate a key' is assumed to be how the generate-vs-enter choice is presented. | Part 3 checkpoint has an explicit TBD: the fact sheet does not say which log line confirms the AC answered the handshake. I did not invent one; it must be filled in from a real install before release. | The gateway version shown in HA is written as 'v0.1.0' per the fact sheet's example; assumed to be exactly the release tag string. | Everything is pointed at the blaueis-ha-midea issue tracker (the only tracker the fact sheet names), including hardware/wiring questions that arguably belong to blaueis-libmidea. | The HACS UI path is written as 'HACS → Custom repositories'; the exact menu location (three-dot menu) is not stated in the fact sheet and not elaborated. | 'Set a target temperature — the AC should follow' as the final checkpoint is inferred from the climate entity having target temperature; no explicit latency or reaction claim is made. | Uninstall on the HA side ('remove the config entry, then remove the integration in HACS') is standard HA/HACS procedure, not in the fact sheet. | The architecture line (WebSocket / UART 9600 8N1 / port 8765) mirrors the public READMEs; I deliberately omitted the encryption detail (AES-256-GCM from the README) to keep every claim on the fact sheet. | Fact-sheet vs public-file conflicts I did NOT resolve, only followed the fact sheet on: (a) license — fact sheet says MIT, both READMEs say CC0 1.0; I left the license out of the quickstart entirely. (b) One-liner URL — READMEs and operations.md §1 use raw.githubusercontent.com/.../main/scripts/install.sh; the fact sheet's releases/latest/download/install.sh is used. (c) operations.md §1 says the installer 'does not start a service'; the fact sheet says the installer runs the wizard and enables+starts the instance. All three need to be updated in the READMEs/operations.md in the same release. | I read operations.md in full because the Read tool returned the whole file; only content from sections 1-3 was used (the psk: key in the instance file, the systemd instance naming). Nothing from sections 4-7 (e.g. the 'RUNNING' state wording) was used in the draft. | No artifact was published: the orchestrating script reads only the StructuredOutput, so the Markdown is returned inline rather than as a page. -->

# Quickstart — Midea AC in Home Assistant via a Raspberry Pi (0.1.0)

This page takes you from an unopened Raspberry Pi and a Midea air conditioner to a working `climate` entity in Home Assistant. Follow it top to bottom. Each part ends with a checkpoint; do not move on until the checkpoint holds.

```
Home Assistant  <-- WebSocket (port 8765) -->  Raspberry Pi gateway  <-- UART 9600 8N1 -->  AC indoor unit
```

Two pieces of software are involved, both released together as **0.1.0**:

- **blaueis-libmidea** — the gateway daemon that runs on the Pi and talks to the AC over its serial port. <https://github.com/fabcoded/blaueis-libmidea>
- **blaueis-ha-midea** — the Home Assistant integration, installed through HACS. <https://github.com/fabcoded/blaueis-ha-midea>

During 0.x the two must always be on the same release number.

---

## Before you start — what you need

| Item | Requirement |
|---|---|
| Raspberry Pi | Any model with the 40-pin header. Its own 5.1 V power supply. |
| Pi operating system | Raspberry Pi OS **Bookworm or newer**. (Python 3.11+ is required; Bullseye ships 3.9 and will not work.) `git` and `sudo` must be available. |
| Level shifter | A **bidirectional 5 V ↔ 3.3 V level shifter**. Not optional — see Part 1. We have not yet published a tested part number; any bidirectional TTL level-shifter module with two or more channels does the job. |
| Wiring | Four wires and whatever fits your AC's dongle socket (see Part 1). |
| Air conditioner | A Midea indoor unit with a Wi-Fi dongle connector (commonly labelled **CN3**). |
| Home Assistant | **2024.10 or newer**, with **HACS** installed. |

Time budget: most of the work is Part 1 (wiring). Parts 2–4 are a few minutes each.

---

## Part 1 — Wire the Pi to the AC

> **Read this first.** The AC's dongle port is a **5 V** serial port. The Pi's serial pins are **3.3 V** and are **damaged by 5 V**. The AC in turn does not answer 3.3 V signals. So every data line goes through the level shifter, and the AC's 5 V line never touches a Pi pin.

> Unplug the indoor unit from mains before you open its cover. Only reconnect power when the wiring is complete and checked.

### 1.1 Find the dongle port on the AC

On the indoor unit, look for the connector where the original Wi-Fi dongle plugs in. It is commonly labelled **CN3**. It comes in one of two shapes:

- a **USB-A-shaped socket** (sometimes keyed so a normal USB plug does not fit), or
- a **4-pin JST-XH** header.

It is a serial port, not USB — do not plug a USB cable or a USB device into it.

**Where we cannot help yet:** we do not have a photo or a verified pinout drawing of this connector for every model, and we cannot tell you the exact connector part to buy. If you are unsure which socket it is on your unit, open an issue with a photo of your unit's board: <https://github.com/fabcoded/blaueis-ha-midea/issues>.

### 1.2 The AC side pinout

The port carries four lines:

| AC pin | Function |
|---|---|
| 1 | **5 V** |
| 2 | data (either the AC's TX or its RX) |
| 3 | data (the other one) |
| 4 | **GND** |

Which of pins 2 and 3 is the AC's transmit line differs between sources. The rule is simple: **wire it one way; if the gateway never gets a reply, swap 2 and 3.** Nothing breaks if you get it wrong the first time, as long as the level shifter is in place.

**Check before you connect anything to the Pi:** with the AC powered and the Pi *not* yet connected, measure between pin 1 and pin 4 with a multimeter. You should read about 5 V. If you do not, you have the wrong pins or the wrong connector — stop and ask.

### 1.3 The Pi side

Use the primary UART on the 40-pin header:

| Pi header pin | Signal |
|---|---|
| 8 | GPIO14 — **TX** (Pi sends) |
| 10 | GPIO15 — **RX** (Pi receives) |
| 6 | GND (the ground pin right next to them) |
| 1 | 3.3 V (reference for the level shifter's low-voltage side) |

On Linux this UART appears as `/dev/serial0` (on a Pi 5: `/dev/ttyAMA0` — see Part 2).

### 1.4 Wiring table

Level shifter modules have a **high-voltage (5 V) side** and a **low-voltage (3.3 V) side**, each with a reference pin, a shared GND, and matching channel pins. Wire:

| From | Via | To |
|---|---|---|
| AC pin 1 (5 V) | — | level shifter **HV reference only**. Never to any Pi pin. |
| AC pin 4 (GND) | — | level shifter GND **and** Pi pin 6 (GND) |
| Pi pin 1 (3.3 V) | — | level shifter **LV reference** |
| AC pin 2 | shifter channel A (HV → LV) | Pi pin 10 (RX) |
| AC pin 3 | shifter channel B (LV → HV) | Pi pin 8 (TX) |

(If the AC never answers later, swap the two AC data wires — pin 2 to channel B, pin 3 to channel A.)

### 1.5 Power

**Power the Pi from its own 5.1 V supply.** Share only GND with the AC.

The AC's dongle port is rated **5 V / 300 mA** (the rating of the original Wi-Fi dongle it was built for). A Pi draws between roughly 100 mA (Zero) and 800 mA (Pi 5). Do not power the Pi from the AC port.

**Checkpoint.** Before applying power, confirm:

- [ ] no wire runs from AC pin 1 (5 V) to any Pi pin;
- [ ] AC GND, level shifter GND and Pi GND are all connected together;
- [ ] both data lines pass through the level shifter, none go direct;
- [ ] the Pi has its own power supply.

Now plug the AC back in and power the Pi.

---

## Part 2 — Prepare the Pi's serial port

Do this on the Pi (keyboard and screen, or SSH). All commands go into a terminal.

### 2.1 Check the OS and Python

```sh
cat /etc/os-release | grep VERSION_CODENAME
python3 --version
git --version
```

**You should see:** `VERSION_CODENAME=bookworm` (or newer), `Python 3.11` or higher, and a git version. If Python is 3.9, you are on Bullseye — reinstall Raspberry Pi OS Bookworm before continuing. If `git` is missing: `sudo apt install git`.

### 2.2 Turn the serial console off and the serial hardware on

The Pi normally uses this serial port as a login console. That must be off, otherwise the console and the gateway fight over the same pins.

```sh
sudo raspi-config
```

Go to **Interface Options → Serial Port** and answer:

- *Would you like a login shell to be accessible over serial?* → **No**
- *Would you like the serial port hardware to be enabled?* → **Yes**

Finish and let it reboot if it offers to (otherwise reboot in 2.4).

### 2.3 Model-specific step

Find your model on the label or with `cat /proc/device-tree/model`.

**Pi Zero W, Zero 2 W, Pi 3, Pi 4** — on these models Bluetooth sits on the good UART and the header pins get the "mini UART". Move Bluetooth off:

```sh
sudo sh -c 'echo "dtoverlay=disable-bt" >> /boot/firmware/config.txt'
sudo systemctl disable hciuart
```

**Pi 5** — on the Pi 5, `/dev/serial0` is the small 3-pin debug header, not pins 8/10. Enable the header UART instead:

```sh
sudo sh -c 'echo "dtoverlay=uart0-pi5" >> /boot/firmware/config.txt'
```

and remember to choose **`/dev/ttyAMA0`** as the port in the setup wizard in Part 3.

**Other models with the 40-pin header** — no extra step.

### 2.4 Reboot and verify

```sh
sudo reboot
```

After the reboot:

```sh
ls -l /dev/serial0        # on a Pi 5: ls -l /dev/ttyAMA0
```

**You should see:** one line describing the device. If you get `No such file or directory`, the serial hardware was not enabled — repeat 2.2.

Also note the Pi's address; you will type it into Home Assistant in Part 4:

```sh
hostname -I
```

---

## Part 3 — Install the gateway on the Pi

### 3.1 Run the installer

```sh
bash -c "$(curl -sL https://github.com/fabcoded/blaueis-libmidea/releases/latest/download/install.sh)"
```

It asks for your `sudo` password. It then:

- creates a system user `blaueis-gw` and adds it to the `dialout` group (serial-port access);
- checks the gateway out to `/opt/blaueis-gw` (pinned to the latest release) and builds a Python venv there;
- creates `/etc/blaueis-gw/` for configuration;
- installs the systemd service template `blaueis-gateway@<instance>`;
- puts the `blaueis-gw` command into `/usr/local/bin`.

The installer warns that the serial port must be **exclusive**: serial console off, Bluetooth moved on the affected models (Part 2), no other program using the UART. If you skipped Part 2, go back now.

### 3.2 Answer the setup wizard

The installer starts the wizard (`blaueis-gw configure`) automatically. It asks:

| Question | What to answer |
|---|---|
| **Serial port** — lists what it detected (`/dev/serial0`, `/dev/ttyAMA0`, `/dev/ttyUSB0`, …) | `/dev/serial0` on most Pis; `/dev/ttyAMA0` on a Pi 5. |
| **Instance name** | A short name, lowercase letters, digits and hyphens only, e.g. `livingroom`. |
| **Pre-shared key (PSK)** | Press Enter to have a 44-character key generated, or type your own (at least 12 characters). |
| **WebSocket port** | Keep the default `8765`. |
| **Device name** | How the AC should be called in Home Assistant, e.g. `Living room AC`. |

**Copy the PSK the wizard prints.** You will paste it into Home Assistant in Part 4. (It is also stored in `/etc/blaueis-gw/instances/<instance>.yaml`, readable with `sudo`.)

The wizard writes `/etc/blaueis-gw/instances/<instance>.yaml`; the installer then enables and starts `blaueis-gateway@<instance>` so it also comes up after a reboot.

### 3.3 Checkpoint

```sh
blaueis-gw status
```

**You should see:** your instance listed and running.

```sh
blaueis-gw logs <instance> -f
```

**You should see:** the gateway starting on your serial port, then no repeating error. Press Ctrl-C to stop following. *(TBD before release: paste here the exact log line that confirms the AC answered the gateway.)* The definitive proof that the AC is talking is the AC device appearing in Home Assistant in Part 4.

Useful commands from here on:

| Command | Purpose |
|---|---|
| `blaueis-gw status` | State of all instances |
| `blaueis-gw logs <instance> -f` | Follow the log |
| `blaueis-gw configure` | Add another AC / edit an instance |
| `sudo blaueis-gw update` | Check for a newer release; `--apply` installs it, `--rollback` returns to the previous one |
| `sudo blaueis-gw uninstall` | Remove the gateway |

---

## Part 4 — Install and configure the Home Assistant integration

### 4.1 Install through HACS

1. Open **HACS**.
2. Open **Custom repositories** and add `https://github.com/fabcoded/blaueis-ha-midea` with type **Integration**.
3. Find **Blaueis Midea AC** and install it.
4. **Restart Home Assistant.**

The integration pulls the Python packages `blaueis-core` and `blaueis-client` from PyPI on first load; nothing to do by hand.

**Checkpoint.** After the restart, go to **Settings → Devices & Services → Add Integration** and search for `Blaueis`. **You should see:** *Blaueis Midea AC* in the list. If it is missing, the restart has not happened yet or the HACS install did not complete.

### 4.2 Connect to the gateway

1. **Settings → Devices & Services → Add Integration → Blaueis Midea AC.**
2. A dialog titled **Blaueis Gateway** opens ("Connect to a Blaueis HVAC gateway running on your network."). Fill in:

| Field | Value |
|---|---|
| **Host** | The Pi's IP address from `hostname -I` in Part 2 (or its hostname, e.g. `gateway.local`) |
| **Port** | `8765` (unless you changed it in the wizard) |
| **Pre-shared key** | The PSK from Part 3 |

3. Submit. Home Assistant tests the connection and the key.

| Message | Meaning |
|---|---|
| **Failed to connect** | The gateway is unreachable at that host/port, or the gateway and the integration are on different releases. |
| **Invalid authentication** | The PSK does not match. |

### 4.3 Checkpoint — what you should now see

Two devices under the new config entry:

- **The AC** — a `climate` entity with mode, target temperature, fan speed, swing and presets, plus sensors and switches for whatever your unit supports. Only capabilities the unit itself advertises appear, so the list differs between models.
- **The Gateway** — Pi health sensors and the gateway version (`v0.1.0`).

Set a target temperature on the climate entity. The AC should follow.

One config entry corresponds to one gateway instance; a second AC on a second Pi (or second instance) is a second config entry.

---

## When it does not work

| Symptom | Likely cause | What to do |
|---|---|---|
| One-liner fails with `git: command not found` | git not installed | `sudo apt install git`, run the one-liner again. |
| Installer refuses: Python too old | Raspberry Pi OS Bullseye (Python 3.9) | Reinstall Bookworm or newer, redo Part 2. |
| Wizard does not list `/dev/serial0` | Serial hardware not enabled, or no reboot since | Redo 2.2, reboot, run `blaueis-gw configure`. On a Pi 5 pick `/dev/ttyAMA0` after adding the `uart0-pi5` overlay. |
| Installer warns the UART is not exclusive | Serial console still on, Bluetooth still on the UART, or another program on the port | 2.2 (console off), 2.3 (`disable-bt` + `hciuart` disabled) — reboot. Stop any other serial daemon. |
| `blaueis-gw status` shows the instance not running | Config or port problem | `blaueis-gw logs <instance>` shows the reason. Re-run `blaueis-gw configure` to fix the port. |
| Gateway runs but the AC device in HA never appears / shows nothing | AC not answering | 1) Swap the two AC data wires (pins 2 and 3). 2) Check the level shifter has both references (5 V from AC pin 1, 3.3 V from Pi pin 1) and GND. 3) Check the AC is powered. |
| HA: **Failed to connect** | Wrong host/port; gateway not running; release mismatch | `blaueis-gw status` on the Pi; ping the host from HA; make sure gateway and integration are both 0.1.0 (`sudo blaueis-gw update` and HACS). |
| HA: **Invalid authentication** | PSK mismatch | `sudo cat /etc/blaueis-gw/instances/<instance>.yaml` shows the `psk:`; re-enter it in HA. |
| HA asks to re-authenticate out of the blue | The gateway's PSK was changed | Enter the new PSK. |
| A feature you expected is missing from the entity | The unit does not advertise it | Only advertised capabilities appear; nothing to configure. |
| Anything else | — | **Settings → Devices & Services → Blaueis Midea → ⋮ → Download Diagnostics** and attach the file to an issue at <https://github.com/fabcoded/blaueis-ha-midea/issues>. |

---

## Updating

Gateway and integration are released together and must be updated **together** during 0.x:

1. On the Pi: `sudo blaueis-gw update` (shows whether a newer release exists), then `sudo blaueis-gw update --apply`.
2. In HA: update *Blaueis Midea AC* in HACS, restart Home Assistant.

If the new release misbehaves: `sudo blaueis-gw update --rollback` returns the gateway to the previous release.

## Uninstalling

On the Pi: `sudo blaueis-gw uninstall`. In HA: remove the config entry, then remove the integration in HACS.

## Getting help

Open an issue at <https://github.com/fabcoded/blaueis-ha-midea/issues>. For wiring questions include a photo of your AC's dongle connector and your Pi model; for everything else attach the Diagnostics download.
