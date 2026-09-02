# Blaueis Midea — Quickstart

From a Raspberry Pi, a Midea air conditioner and a Home Assistant install to a working climate entity. Four stages, in this order — each ends with a checkpoint; do not move on until it holds.

| Stage | Where | You end up with |
|---|---|---|
| 1. Wire | AC + Pi | The Pi's UART connected to the AC's dongle port through a level shifter |
| 2. Gateway | Pi | `blaueis-gateway@<name>` running, and a pre-shared key (PSK) in hand |
| 3. Integration | Home Assistant | **Blaueis Midea AC** installed through HACS |
| 4. Connect | Home Assistant | Two devices: your AC and the gateway |

Two components, released together under the same version number (0.1.0 for both): the gateway daemon ([blaueis-libmidea](https://github.com/fabcoded/blaueis-libmidea)) and the integration ([blaueis-ha-midea](https://github.com/fabcoded/blaueis-ha-midea)). During 0.x you update them together (stage 5).

```
Home Assistant  <-- WebSocket, port 8765 -->  Raspberry Pi gateway  <-- UART 9600 8N1 -->  AC indoor unit
```

## Before you start

- **A Raspberry Pi with the 40-pin header**, any model (Pi 5 needs one extra config line, 1.5), with **its own 5.1 V power supply**.
- **Raspberry Pi OS Bookworm or newer.** The gateway needs Python 3.11+; Bullseye ships 3.9 and will not work. `git` and `sudo` must be available.
- **A bidirectional 5 V ↔ 3.3 V level shifter.** Mandatory: the Pi's UART pins are 3.3 V and are damaged by 5 V, and the AC does not answer 3.3 V signalling. Any bidirectional TTL level-shifter module with two or more channels does the job.
- **Wires and a plug that fits your AC's dongle socket** (1.1 describes the socket; the exact part depends on your unit).
- **Home Assistant 2024.10 or newer** with **HACS** installed, and a network path from Home Assistant to the Pi on TCP port 8765.

Check the Pi first:

```sh
grep VERSION_CODENAME /etc/os-release   # expected: bookworm (or newer)
python3 --version                        # expected: 3.11 or newer
git --version                            # missing? sudo apt install git
```

## 1. Wire the Pi to the AC

**Read the whole stage before touching anything.** Two mistakes destroy hardware: 5 V on a Pi UART pin, and powering the Pi from the AC. Unplug the indoor unit from mains before opening its cover; power everything up only after the checkpoint in 1.4.

### 1.1 The AC side: the Wi-Fi dongle connector

Midea indoor units have a connector for the OEM Wi-Fi dongle, commonly labelled **CN3** on the indoor unit's board. Electrically it is a **5 V TTL UART, 9600 8N1**, on four pins. It is not USB, even when the socket is USB-A-shaped.

| CN3 pin | Signal |
|---|---|
| 1 | 5 V |
| 2 | data — the AC's TX *or* RX |
| 3 | data — the other one |
| 4 | GND |

The socket is either **USB-A-shaped** (sometimes keyed) or a **4-pin JST-XH** header. Which of pins 2 and 3 carries the AC's transmit line is reported differently for different units: wire it one way; if the gateway never hears from the AC (2.2), swap the two data lines. Nothing breaks either way as long as the level shifter is in place.

Before connecting anything to the Pi: with the AC powered and the Pi *not* connected, measure between pin 1 and pin 4 with a multimeter. You should read about 5 V. If you do not, you have the wrong pins or the wrong connector — stop and ask (see *Where to ask*). Power the AC down again before wiring.

> **Honest gap.** We do not yet have a photo or pinout of CN3 on a specific unit, the exact mating connector part, or a tested level-shifter part number. If you identify these for your unit, open an issue with a photo of the socket and the indoor unit's model label — that is exactly what is needed to close this gap for the next person.

### 1.2 Power: the Pi gets its own supply

The AC's dongle port is rated **5 V / 300 mA** (the OEM smart kit's rating). A Pi draws **100 mA (Zero) to 800 mA (Pi 5)**. Power the Pi from its own 5.1 V supply, share **GND only**, and leave **CN3 pin 1 (5 V) unconnected**.

### 1.3 The Pi side: the primary UART

| Header pin | Signal |
|---|---|
| 8 | GPIO14 — **TX** (Pi → AC) |
| 10 | GPIO15 — **RX** (AC → Pi) |
| 6 | GND |
| 1 | 3.3 V — reference for the level shifter's low-voltage side |
| 2 | 5 V — reference for the level shifter's high-voltage side |

On Linux this UART is `/dev/serial0` (on a Pi 5 it becomes `/dev/ttyAMA0` — see 1.5).

### 1.4 Connections through the level shifter

Level-shifter modules have a **high-voltage side** and a **low-voltage side**, each with a reference pin, a shared GND, and matching channel pins. Both references come from the Pi, so the AC's 5 V never leaves the AC:

| From | Via | To |
|---|---|---|
| Pi pin 2 (5 V) | — | shifter **HV reference** |
| Pi pin 1 (3.3 V) | — | shifter **LV reference** |
| AC pin 4 (GND) | — | shifter GND **and** Pi pin 6 (GND) |
| AC pin 2 | shifter channel A | Pi pin 10 (RX) |
| AC pin 3 | shifter channel B | Pi pin 8 (TX) |
| AC pin 1 (5 V) | — | **not connected** |

(If the AC never answers later: swap the two AC data wires — pin 2 to channel B, pin 3 to channel A.)

**Checkpoint.** Before applying power: no wire runs from AC pin 1 to anything; AC GND, shifter GND and Pi GND are connected together; both data lines pass through the shifter, none directly; the Pi has its own supply. Then power the Pi, then the AC.

### 1.5 Give the UART to the gateway

The UART must belong to the gateway alone: serial console off, Bluetooth moved off it on the models listed below, no other serial daemons. The installer warns about this but cannot fix it for you.

1. `sudo raspi-config` → **Interface Options → Serial Port**: login shell over serial **No**, serial port hardware **Yes**.
2. **Pi Zero W, Zero 2 W, 3, 4** — `/dev/serial0` is the mini UART until Bluetooth is moved off the primary one:

   ```sh
   echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt
   sudo systemctl disable hciuart
   ```

3. **Pi 5** — `/dev/serial0` is the 3-pin debug header, not pins 8/10. Enable the header UART instead:

   ```sh
   echo "dtoverlay=uart0-pi5" | sudo tee -a /boot/firmware/config.txt
   ```

   and choose **`/dev/ttyAMA0`** in the wizard (2.1).
4. **Other models with the 40-pin header** — no extra step.
5. `sudo reboot`.

**Checkpoint.** `ls -l /dev/serial0` prints a device (on a Pi 5: `ls -l /dev/ttyAMA0`). `No such file or directory` means the serial hardware is not enabled — repeat step 1. Note the Pi's address for stage 4: `hostname -I`.

## 2. Install the gateway on the Pi

```sh
bash -c "$(curl -sL https://github.com/fabcoded/blaueis-libmidea/releases/latest/download/install.sh)"
```

It asks for your `sudo` password, then: creates the system user `blaueis-gw` and adds it to `dialout`; checks the latest release out to `/opt/blaueis-gw` with its own Python venv; creates `/etc/blaueis-gw/` for configuration; installs the systemd template service `blaueis-gateway@<instance>`; links the `blaueis-gw` command into `/usr/local/bin`; and starts the setup wizard.

### 2.1 The wizard

| Prompt | What to answer |
|---|---|
| Serial port (lists what it detected: `/dev/serial0`, `/dev/ttyAMA0`, `/dev/ttyUSB0`, …) | `/dev/serial0` — on a Pi 5 with the overlay from 1.5, `/dev/ttyAMA0` |
| Instance name | Lowercase letters, digits, hyphens — e.g. `living-room`. It becomes the service name `blaueis-gateway@living-room`. |
| Pre-shared key (PSK) | Accept the generated 44-character key, or type your own (12 characters minimum). |
| WebSocket port | `8765` unless something else uses it. |
| Device name | How the AC will be named in Home Assistant. |

**Copy the PSK the wizard prints — Home Assistant asks for it in stage 4.** It is stored as the `psk:` line in `/etc/blaueis-gw/instances/<name>.yaml` (needs `sudo` to read). The installer then enables and starts `blaueis-gateway@<name>`, so it also comes up after a reboot.

### 2.2 Checkpoint: the gateway runs and the AC answers

```sh
blaueis-gw status              # your instance shows systemd's "active (running)"
blaueis-gw logs <name> -f      # Ctrl-C to stop following
```

In the log you should see, in this order: `Starting gateway v0.1.0 on ws://0.0.0.0:8765`, `UART connected`, `DISCOVER: sending SN query (0x07)`, `DISCOVER: found appliance=…`, `MODEL: model=…`, and finally **`ANNOUNCE → RUNNING`** — that line means the AC answered and the handshake is complete.

If instead the log repeats **`DISCOVER: no response, retrying in 5.0s`**, the AC is not answering: power the AC down, swap the two AC data lines (1.4), power up, and watch again. Still nothing: check the AC is powered, the shifter has both references and GND, and the port you picked is the one you wired (`blaueis-gw configure` changes it).

If the instance is not running at all, `blaueis-gw logs <name>` shows why — a serial port that is missing, busy or denied means stage 1.5 was skipped or the wrong port was chosen; a WebSocket port in use means another program has 8765 (`blaueis-gw configure`, pick another port, remember it for stage 4).

### 2.3 `blaueis-gw` commands you will need later

| Command | Purpose |
|---|---|
| `blaueis-gw status` | State of all instances |
| `blaueis-gw logs <name> -f` | Follow an instance's log |
| `blaueis-gw configure` | Add another AC or edit an instance (changing the PSK makes HA ask to re-authenticate) |
| `sudo blaueis-gw update` | Check for a newer release; `--apply` installs it; `--rollback` returns to the previous release |
| `sudo blaueis-gw uninstall` | Remove the gateway |

## 3. Install the integration in Home Assistant

1. **HACS → ⋮ → Custom repositories.** Add `https://github.com/fabcoded/blaueis-ha-midea`, type **Integration**.
2. Search **Blaueis Midea AC** and download it.
3. **Restart Home Assistant.** On this restart HA installs the Python packages `blaueis-core` and `blaueis-client` from PyPI by itself — the HA host needs internet access for that one restart.

**Checkpoint.** Settings → Devices & Services → Add Integration → search `Blaueis` shows **Blaueis Midea AC**. If it is missing, the download did not complete or HA has not restarted yet.

## 4. Connect Home Assistant to the gateway

1. **Settings → Devices & Services → Add Integration → Blaueis Midea AC.**
2. The dialog is titled **Blaueis Gateway** ("Connect to a Blaueis HVAC gateway running on your network."). Fill in:

   | Field | Value |
   |---|---|
   | Host | The Pi's IP from `hostname -I`, or its hostname (e.g. `gateway.local`) |
   | Port | `8765`, or the port you chose in the wizard |
   | Pre-shared key (passphrase) | The PSK from 2.1 |

3. Submit. The flow tests the connection and the key before creating anything.

| Message | Meaning | Do this |
|---|---|---|
| **Failed to connect** | HA cannot reach the gateway at that host/port, or gateway and integration speak different protocol versions (not updated together) | `blaueis-gw status` on the Pi; try the IP instead of the hostname; make sure both sides are on the same release (stage 5) |
| **Invalid authentication** | The PSK does not match | `sudo grep psk /etc/blaueis-gw/instances/<name>.yaml` on the Pi and enter it again |

**Checkpoint — what you should now see.** Two devices under the new entry:

- **Your AC** — a climate entity (mode, target temperature, fan speed, swing, presets) plus sensors and switches for what the unit supports. Only capabilities the unit itself advertises appear, so the list differs between models — a shorter list than someone else's is normal.
- **The gateway** — Pi health sensors and the gateway version (the release tag, e.g. `v0.1.0`).

Set a target temperature on the climate entity; the AC should follow. One config entry corresponds to one gateway instance. If the gateway's PSK changes later, Home Assistant asks you to re-authenticate.

## 5. Updating — during 0.x always both

Gateway and integration must run the same release number. Update both, then restart Home Assistant:

```sh
sudo blaueis-gw update             # reports whether a newer release exists
sudo blaueis-gw update --apply     # installs it
sudo blaueis-gw update --rollback  # returns to the previous release if the new one misbehaves
```

In HA: HACS → **Blaueis Midea AC** → Update → restart. **Failed to connect** right after an update usually means only one side was updated.

## When it does not work

| Symptom | Likely cause | What to do |
|---|---|---|
| One-liner fails: `git: command not found` | git not installed | `sudo apt install git`, run it again |
| Installer refuses: Python too old | Raspberry Pi OS Bullseye | Reinstall Bookworm or newer, redo stage 1.5 |
| Wizard does not list `/dev/serial0` | Serial hardware not enabled, or no reboot since | Redo 1.5; on a Pi 5 pick `/dev/ttyAMA0` after adding the overlay |
| Log repeats `DISCOVER: no response` | Data pair swapped, AC unpowered, shifter reference or GND missing, wrong port | 2.2, in that order |
| Instance not running | UART not exclusive, or port 8765 in use | `blaueis-gw logs <name>`; redo 1.5, or change the port with `blaueis-gw configure` |
| **Failed to connect** in HA | Wrong host/port; gateway not running; sides on different releases | `blaueis-gw status`; try the IP; stage 5 |
| **Invalid authentication** in HA | PSK mismatch | `sudo grep psk /etc/blaueis-gw/instances/<name>.yaml`; re-enter |
| HA asks to re-authenticate | The gateway's PSK was changed | Enter the new key |
| Fewer entities than expected | The unit does not advertise that capability | Expected; nothing to configure |

## Where to ask

Open an issue at <https://github.com/fabcoded/blaueis-ha-midea/issues>. Say which stage failed and attach:

1. **The diagnostics bundle** — Settings → Devices & Services → Blaueis Midea → ⋮ → **Download Diagnostics** (needs stage 4 to have succeeded; if it did not, say so).
2. The output of `blaueis-gw status` and of `blaueis-gw logs <name> -f` covering the failure.
3. Pi model, `grep PRETTY_NAME /etc/os-release`, `ls -l /dev/serial0`, and the gateway and integration releases (they must match).
4. For wiring or connector questions: the indoor unit's model label and a photo of the dongle socket.

Do not paste the PSK.

## Uninstall

On the Pi: `sudo blaueis-gw uninstall`. In HA: Settings → Devices & Services → Blaueis Midea → ⋮ → Delete, then remove the integration in HACS.

## Next

- The integration README — what the entities are, Blaueis Follow Me, capability detection.
- `docs/integration.md` in blaueis-ha-midea — entity model, debugging, reload vs restart.
- `docs/operations.md` in blaueis-libmidea — gateway configuration reference, systemd layout, logs.
