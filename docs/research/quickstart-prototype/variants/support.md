<!-- variant: support -->
<!-- structure: {"lives_in": "blaueis-ha-midea/QUICKSTART.md (repo root, one canonical page). Linked in the first paragraph of BOTH READMEs by absolute GitHub URL. The ha-midea README is what HACS renders inside Home Assistant, so a root-level file in that repo is the page a stranger reaches with one click from where they already are; a root file (not docs/) is visible in the GitHub file listing next to README.md and gives one stable URL to paste into every issue reply.", "split": "ha-midea README = 'what you get' (devices, entity platforms, Follow Me, capability detection) + a 3-line Install section that says only: requirements (HA 2024.10+, HACS, a running gateway), 'follow QUICKSTART.md', and the diagnostics/issue pointer. Drop the Manual-install block, the 'once published' wording and the 'gateway.yaml:psk' reference. libmidea README = library/packages description + a Quick start section reduced to the release-asset one-liner, one sentence 'for the full path (hardware -> Pi -> HA) follow the Quickstart in blaueis-ha-midea', and a link to docs/operations.md for the reference. Drop Bullseye. docs/operations.md stays the reference (systemd layout, config keys, update mechanics, deep troubleshooting); its section 1 is rewritten for the release-asset installer + wizard + blaueis-gw CLI so it agrees with the quickstart, and its section 6 becomes the deep-dive that the quickstart's failure branches point to. Hardware detail that grows beyond the quickstart's minimum (Pi model matrix, CN3 photos/pinouts per unit, tested level-shifter parts, connector part numbers) goes to a new libmidea docs/hardware.md; the quickstart keeps only what a stranger needs to wire safely and links there.", "rationale": "Support-burden minimisation wants exactly one page a stranger follows and one URL a maintainer pastes; every issue reply becomes 'which step of QUICKSTART failed, and what did the command in that step print'. The stranger's goal is the HA climate entity and the HA integration is what they search for and what HACS shows, so the page belongs with ha-midea even though 80% of the content is hardware and gateway; hopping repos mid-wiring is where people get lost. libmidea remains the reference and library repo; operations.md keeps the depth the quickstart deliberately omits. Doc-parity items that must land with 0.1.0 because the current public docs contradict the fact sheet: libmidea README + operations.md section 1 still use the raw-main install.sh URL and say the installer does not start a service; ha-midea README says the library is vendored under custom_components/.../lib/ while the fact sheet says PyPI; both READMEs say CC0 while the fact sheet says MIT."} -->
<!-- assumptions: Exact output wording of `blaueis-gw status` for a healthy instance ("running") is unverified; left as a MAINTAINER TODO in 3.3 together with the two log lines (AC handshake complete / no reply) that support replies will need. | The failure classes in 3.3 (log 'complains about the WebSocket port' / 'about the serial port') are symptom classes, not verified log strings — the fact sheet gives no log text. | The HA config flow succeeds when the gateway is up but the AC is silent (it tests only gateway reachability and PSK), so 'Gateway device present, AC device missing/unavailable' is the symptom of a non-answering AC — inferred from the fact sheet, not stated in it. | `/dev/serial0` resolves to `ttyAMA0` after `dtoverlay=disable-bt` and to `ttyS0` (mini UART) before — standard Raspberry Pi OS behaviour, not in the fact sheet; the 1.4 check depends on it. | `dtoverlay=uart0-pi5` is the config.txt line for the 'uart0-pi5 overlay' the fact sheet names; appending with `tee -a` rather than editing is a generic choice. | Pi header pin numbers for 3.3 V and GND are deliberately not given (fact sheet forbids inventing pin names); the reader is sent to their Pi's pinout. The 2.2 table's 'any GND pin' / '3.3 V' wording follows from that. | The multimeter check (5 V between AC pins 1 and 4 with the AC powered) and powering the AC down before wiring are generic safety practice added to cover the stated CN3 gaps; not in the fact sheet. | The PSK is stored under the YAML key `psk` in `/etc/blaueis-gw/instances/<name>.yaml` (taken from the public docs/operations.md §3.4 example), hence the `sudo grep psk …` recovery command. | `blaueis-gw logs <name> -f` is the only log command in the fact sheet; the issue-report step asks for its output captured until Ctrl-C because a non-follow / line-count form is not documented. | All issues, including gateway-only failures, are directed to the ha-midea tracker because it is the only tracker URL in the fact sheet. | HACS shows the installed version of a custom-repository integration and offers an Update action; an integration update needs an HA restart — generic HACS/HA behaviour. | `gateway.local` may not resolve from the HA host (mDNS); 'try the IP' is a generic fallback. `hostname -I`, `grep … /etc/os-release`, `python3 --version` are generic Linux checks. | The HA host needs internet access on the first restart to pull blaueis-core / blaueis-client from PyPI — derived from the fact sheet's PyPI statement. | raspi-config prompt wording ('login shell accessible over serial?' / 'serial port hardware enabled?') is paraphrased from the fact sheet's 'login shell NO, serial hardware YES'; wizard prompt order and wording are paraphrased too. | 'Wait a minute' after swapping the data lines in step 6 is an unspecified settle time; the fact sheet gives no timing. | License: the fact sheet says MIT, both current READMEs say CC0 1.0. The quickstart states no license; this must be resolved before 0.1.0. | Doc-parity conflicts followed in favour of the fact sheet: current libmidea README and operations.md §1 use the raw-main install.sh URL and say the installer does not start a service (fact sheet: release-asset URL, wizard, enable+start); ha-midea README says the library is vendored under custom_components/…/lib/ (fact sheet: PyPI), still says 'once published' and references 'gateway.yaml:psk'. These need updating alongside the quickstart. | 'Do not paste the PSK' in section 8 and 'It is not USB' in 2.1 are derived cautions (from the PSK being the HA credential and the port being a 5 V TTL UART), not literal fact-sheet lines. -->

# Blaueis Midea — Quickstart (0.1.0)

End state: a Home Assistant climate entity for your Midea air conditioner, driven by a Raspberry Pi wired to the indoor unit's Wi-Fi dongle connector. No cloud.

Four parts, in this order: **free the Pi's UART → wire the AC → install the gateway on the Pi → install and connect the integration in Home Assistant.** Every step says what you should see and what to run if you don't. If you get stuck, section 8 says exactly what to put in an issue.

Two components, released together:

| Component | Repo | Installs as |
|---|---|---|
| Gateway daemon | [fabcoded/blaueis-libmidea](https://github.com/fabcoded/blaueis-libmidea) | `blaueis-gw` on the Pi, via a one-line installer |
| HA integration "Blaueis Midea AC" | [fabcoded/blaueis-ha-midea](https://github.com/fabcoded/blaueis-ha-midea) | HACS custom repository |

**During 0.x the gateway and the integration must run the same release number.** A mismatch shows up in HA as "Failed to connect" (section 5).

## 0. What you need

- A Raspberry Pi with the 40-pin header, running Raspberry Pi OS **Bookworm or newer** (Python 3.11+ is required; Bullseye ships 3.9 and does not work), on your network, with `git` and `sudo` available. A Pi 5 works but needs step 1.3.
- The Pi's own 5.1 V power supply. **Never power the Pi from the AC** (section 2).
- A **bidirectional 5 V ↔ 3.3 V level shifter** — mandatory, section 2 says why.
- Wires for four connections (5 V, GND, two data lines) to the AC's dongle socket.
- Home Assistant **2024.10 or newer** with HACS installed.
- A Midea air conditioner whose indoor unit has the Wi-Fi dongle connector (commonly labelled CN3).

Check the Pi before anything else:

```sh
grep VERSION_CODENAME /etc/os-release   # expected: bookworm (or newer)
python3 --version                        # expected: 3.11 or newer
```

If either is older, reinstall the OS first. Nothing below works on Bullseye.

## 1. Free the Pi's UART

The gateway needs the primary UART — header pins 8 (GPIO14, TX) and 10 (GPIO15, RX), `/dev/serial0` — **exclusively**. Nothing else may use it: no serial console, no Bluetooth on it, no other UART daemon. The installer warns about this again in step 3; do it now.

### 1.1 Turn off the serial console (all models)

```sh
sudo raspi-config
```

Interface Options → Serial Port → "login shell accessible over serial?" **No** → "serial port hardware enabled?" **Yes**. Finish and reboot when asked.

### 1.2 Pi Zero W, Zero 2 W, 3, 4: move Bluetooth off the UART

On these models `/dev/serial0` is the mini UART until Bluetooth is moved off it. Do both, then reboot:

```sh
echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt
sudo systemctl disable hciuart
sudo reboot
```

### 1.3 Pi 5: use the header UART, not the debug header

On the Pi 5, `/dev/serial0` is the 3-pin debug header, not pins 8/10. Enable the `uart0-pi5` overlay and reboot:

```sh
echo "dtoverlay=uart0-pi5" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

In step 3.2 pick `/dev/ttyAMA0` as the serial port (the gateway config key is `uart_port: /dev/ttyAMA0`).

### 1.4 Check

```sh
ls -l /dev/serial0
```

**Expected:** a symlink is printed. On the models in 1.2 it points at `ttyAMA0` after the Bluetooth change; if it points at `ttyS0`, Bluetooth is still on the UART — repeat 1.2. On a Pi 5 run `ls -l /dev/ttyAMA0` instead; it must exist.

## 2. Wire the AC to the Pi

**Read the whole section before touching anything.** Two mistakes destroy hardware:

1. The AC's dongle port is **5 V**. The Pi's UART pins are **3.3 V** and are damaged by 5 V. The AC does not answer 3.3 V drive. A bidirectional 5 V ↔ 3.3 V level shifter on both data lines is mandatory — no exceptions.
2. The AC port is rated **5 V / 300 mA** (the OEM smart kit's rating). A Pi draws 100 mA (Zero) to 800 mA (Pi 5). Power the Pi from its own 5.1 V supply. Share **GND only**. Never connect the AC's 5 V to the Pi's power input.

### 2.1 The AC socket

The indoor unit's Wi-Fi dongle connector (commonly labelled **CN3**) is a 5 V TTL UART at 9600 8N1. It is not USB, even when it is USB-A-shaped. Two shapes are known: a USB-A-shaped socket (sometimes keyed) and a 4-pin JST-XH.

| Pin | Signal |
|---|---|
| 1 | 5 V |
| 2 | data |
| 3 | data |
| 4 | GND |

Which of pins 2/3 is the AC's TX differs between sources. Pick one; if the AC never answers (step 6), swap them.

**Gaps we cannot close for you yet:** we have not published a photo or pinout of CN3 on a specific unit, an exact connector part number, or a tested level-shifter part number. So: power the AC, confirm with a multimeter that pin 1 → pin 4 reads about 5 V, then power the AC down again before connecting anything. If your socket looks different or the pin numbering is unclear, stop and open an issue (section 8) with a photo of the socket and the indoor unit's model label — that is exactly the information we need to close this gap.

### 2.2 Connections

The AC's 5 V (pin 1) feeds the level shifter's high-voltage reference; a 3.3 V pin on the Pi header feeds its low-voltage reference. See your Pi's pinout for 3.3 V and GND pins.

| AC | Level shifter | Pi |
|---|---|---|
| pin 1 (5 V) | HV reference | — (not connected to the Pi) |
| pin 4 (GND) | GND | any GND pin |
| pin 2 or 3 | channel A, HV ↔ LV | pin 8 (GPIO14, TX) |
| pin 3 or 2 | channel B, HV ↔ LV | pin 10 (GPIO15, RX) |
| — | LV reference | 3.3 V |

Power the Pi from its own supply, then power the AC. Nothing is observable yet — the AC-answers check is step 6.

## 3. Install the gateway on the Pi

### 3.1 Run the installer

```sh
bash -c "$(curl -sL https://github.com/fabcoded/blaueis-libmidea/releases/latest/download/install.sh)"
```

It asks for `sudo`. It creates the system user `blaueis-gw`, a checkout of the latest release in `/opt/blaueis-gw` with its own Python venv, `/etc/blaueis-gw/` for config, the systemd template service `blaueis-gateway@<instance>`, adds the service user to `dialout`, links the `blaueis-gw` CLI into `/usr/local/bin`, and then starts the setup wizard.

### 3.2 Answer the wizard

| Prompt | Answer |
|---|---|
| Serial port (lists detected ports: `/dev/serial0`, `/dev/ttyAMA0`, `/dev/ttyUSB0`, …) | `/dev/serial0` — on a Pi 5: `/dev/ttyAMA0` |
| Instance name | lowercase letters, digits, hyphens — e.g. `living-room` |
| Pre-shared key | accept the generated 44-character key, or enter your own (12 characters minimum) |
| WebSocket port | `8765` unless something else uses it |
| Device name | free text, shown in Home Assistant |

**The wizard prints the PSK. Copy it now — Home Assistant asks for it in step 5.** It is written to `/etc/blaueis-gw/instances/<name>.yaml`; read it back later with `sudo grep psk /etc/blaueis-gw/instances/<name>.yaml`.

The installer then enables and starts `blaueis-gateway@<name>`.

### 3.3 Check the service

```sh
blaueis-gw status
```

**Expected:** `<name>` is listed and running.

**If not:**

```sh
blaueis-gw logs <name> -f     # Ctrl-C to stop
```

- The log complains about the WebSocket port → another program has it. `blaueis-gw configure`, choose a different port, remember it for step 5.
- The log complains about the serial port (missing, busy, permission denied) → step 1 was skipped, the wrong port was chosen, or something else holds the UART. Redo 1.4, then `blaueis-gw configure` and pick the port again.
- Anything else → section 8, with the log output.

The gateway reaching "running" only proves the service is up. Whether the AC answers is checked in step 6 — but if you want to see it on the Pi first, keep `blaueis-gw logs <name> -f` open while the AC is powered.

> MAINTAINER TODO before publishing: paste here (a) the exact status line `blaueis-gw status` prints for a healthy instance, and (b) the exact log line that marks the AC handshake completing and the one that marks "no reply from AC". These are the two strings every support reply will refer to.

## 4. Install the integration in Home Assistant

1. HACS → ⋮ → **Custom repositories** → Repository `https://github.com/fabcoded/blaueis-ha-midea`, Type **Integration** → Add.
2. In HACS search **Blaueis Midea AC** → Download.
3. Restart Home Assistant. On this restart HA installs `blaueis-core` and `blaueis-client` from PyPI by itself — the HA host needs internet access for that one restart.

**Expected:** after the restart, Settings → Devices & Services → Add Integration → searching "Blaueis Midea AC" finds it.

**If not:** confirm the HACS download finished and that HA actually restarted (Settings → System → Restart), and that Settings → About shows 2024.10 or newer — older HA does not load it.

## 5. Connect Home Assistant to the gateway

Settings → Devices & Services → **Add Integration** → search **Blaueis Midea AC**. The dialog is titled **Blaueis Gateway** — "Connect to a Blaueis HVAC gateway running on your network."

| Field | Value |
|---|---|
| Host | the Pi's IP or hostname, e.g. `gateway.local` (`hostname -I` on the Pi prints the IP) |
| Port | `8765`, or the port you chose in 3.2 |
| Pre-shared key (passphrase) | the PSK from 3.2 |

The flow tests the connection and the key before creating anything.

| Error | Meaning | Do this |
|---|---|---|
| **Failed to connect** | gateway unreachable, or gateway and integration are different releases | 1. On the Pi: `blaueis-gw status` — running? If not, 3.3. 2. Use the IP instead of `gateway.local`. 3. Versions: `sudo blaueis-gw update` on the Pi reports whether a newer release exists; HACS shows the integration's version. Both must be the same release — section 7. |
| **Invalid authentication** | wrong PSK | `sudo grep psk /etc/blaueis-gw/instances/<name>.yaml` on the Pi; paste it again. |

One config entry per gateway instance. If you change the gateway's key later, HA prompts to re-authenticate.

## 6. Check the result

**Expected:** two devices under the integration:

- **The AC** — a climate entity (mode, target temperature, fan speed, swing, presets) plus sensors and switches for what the unit supports. Only capabilities the unit advertises appear, so a shorter entity list than someone else's is normal, not a fault.
- **The Gateway** — Pi health sensors and the gateway version.

**If the Gateway device is there but the AC device is missing or unavailable:** the gateway is up and HA reaches it, but the AC is not answering. In order:

1. Power the AC down. Swap the two data lines (AC pins 2 and 3 — section 2.1). Power the AC up. Wait a minute and check HA again.
2. Redo 1.4: `/dev/serial0` must point at `ttyAMA0` on the models in 1.2; on a Pi 5 the wizard must have been given `/dev/ttyAMA0`. Serial console off.
3. Check the level shifter: 5 V from the AC on the HV side, 3.3 V from the Pi on the LV side, GND shared, both data lines through the shifter.
4. Still nothing → section 8 with the diagnostics bundle. State which data-pin order you ended on.

## 7. Updating — during 0.x always both

Gateway and integration must be on the same release number. Update both, then restart HA.

On the Pi:

```sh
sudo blaueis-gw update             # reports whether a newer release exists
sudo blaueis-gw update --apply     # installs it
sudo blaueis-gw update --rollback  # returns to the previous release
```

In HA: HACS → Blaueis Midea AC → Update → restart Home Assistant.

The gateway's version (the release tag, e.g. `v0.1.0`) is shown on the Gateway device in HA. A mismatch after updating one side shows as "Failed to connect" — update the other side.

Other commands: `blaueis-gw status` (all instances), `blaueis-gw logs <name> -f`, `blaueis-gw configure` (add or edit an instance), `sudo blaueis-gw uninstall`.

## 8. Reporting a problem

Open an issue at <https://github.com/fabcoded/blaueis-ha-midea/issues>. Say which step above failed, and attach:

1. **The diagnostics bundle**: Settings → Devices & Services → Blaueis Midea → ⋮ → **Download Diagnostics**. This needs step 5 to have succeeded; if it did not, say so.
2. The output of `blaueis-gw status`, and of `blaueis-gw logs <name> -f` covering the failure (Ctrl-C after it reproduces).
3. Pi model, `grep PRETTY_NAME /etc/os-release`, `ls -l /dev/serial0`.
4. The gateway release and the integration release (section 7 — they must match).
5. The indoor unit's model label. For wiring or connector questions, a photo of the dongle socket.

Do not paste the PSK.

## 9. Uninstall

On the Pi: `sudo blaueis-gw uninstall`. In HA: Settings → Devices & Services → Blaueis Midea → ⋮ → Delete, then remove the integration in HACS.
