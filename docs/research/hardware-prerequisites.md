# Hardware prerequisites — what a "What you need" paragraph can state today

Research note for the installation docs. Question: what does a stranger need
before step one of installing a Blaueis gateway (Raspberry Pi on the indoor
unit's Wi-Fi-dongle UART), and how much of it is already written down in our
public repos? Sources are the four public Blaueis repos, the official
Raspberry Pi documentation, and community projects that document the dongle
connector. Every fact carries its source; facts stated in our own words.

## Summary

- The Pi side is fully documented by Raspberry Pi: the primary UART is GPIO14/15 (header pins 8/10) on every model except Pi 5; `/dev/serial0` is the symlink to it; on Pi Zero W / Zero 2 W / 3 / 4 that UART is the mini UART unless Bluetooth is moved (`dtoverlay=disable-bt` + `systemctl disable hciuart`); on Pi 5 `serial0` is the 3-pin debug header, not the GPIO pins.
- The serial console must be turned off (`raspi-config` → Interface Options → Serial Port: login shell No, hardware Yes). The installer already prints these steps; the paragraph can point at them.
- The AC-side port is a 5 V TTL UART at 9600 8N1. Raspberry Pi UARTs are 3.3 V and documented as damaged by 5 V; ESPHome documents that the AC does not respond to 3.3 V drive. A bidirectional level shifter is therefore a statable requirement.
- Connector: most units expose a USB-A-shaped socket (sometimes keyed) or a 4-pin JST-XH; pin 1 = 5 V, pin 4 = GND, pins 2/3 = the data pair. Which of 2/3 is the AC's TX is stated inconsistently across sources — say "swap if no reply".
- Power: the OEM Smart Kit is rated DC 5 V / 300 mA, so that is the only known budget of the port. Every Pi except the Zero / Zero W typically draws more; nobody has measured the port's real limit. Tell the reader to power the Pi from its own 5.1 V supply.
- Software: Python 3.11+ means Raspberry Pi OS Bookworm or newer; Bullseye ships 3.9.
- Gaps: a photo and pin count / pitch of CN3 and of the dongle harness on our unit; a bench check of which CN3 wire is AC-TX (our own docs disagree); a measurement of the port's current capability; a Pi 5 and a USB-serial-adapter run; the Pi model we actually run.
- Our own docs also need four small corrections (Pi 5 Bluetooth claim, `config.txt` path, config-dir path in an error hint, Bullseye/Python 3.11 contradiction) — listed in §4.

## 1. Facts the paragraph can state today

Repo file references use `<github repo>: <path>`; official pages by URL.

### 1.1 Raspberry Pi model and UART

| Fact | Source |
|---|---|
| The gateway opens one serial device, default `/dev/serial0`, at 9600 baud; both are config keys (`uart_port`, `uart_baud`) so any device path can be substituted. | fabcoded/blaueis-libmidea: `docs/operations.md` §3.1; `packages/blaueis-gateway/src/blaueis/gateway/server.py` (`uart_port` default, `_uart_loop`) |
| The installer probes `/dev/serial0`, `/dev/ttyAMA0`, `/dev/ttyUSB0`, `/dev/ttyUSB1`, `/dev/ttyACM0`, so a USB-to-serial adapter is an accepted alternative to the GPIO UART. | fabcoded/blaueis-libmidea: `scripts/install.sh` ("Serial port check"); `packages/blaueis-gateway/src/blaueis/gateway/configure.py` |
| On every Raspberry Pi except Pi 5 the primary UART is on GPIO 14 (transmit, header pin 8) and GPIO 15 (receive, header pin 10). | https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts ("Primary and secondary UARTs") |
| `/dev/serial0` is a symlink Raspberry Pi OS creates to the primary UART; it resolves to `/dev/ttyS0` (mini UART), `/dev/ttyAMA0` (first PL011) or `/dev/ttyAMA10` (Pi 5 debug UART) depending on model. | same page, "Linux device names" |
| Pi Zero, Pi 1, Pi 2, Compute Modules 1/3/3+/4: primary UART is `UART0` (PL011) — the good UART is already on the pins and there is no Bluetooth to move. | same page, table "Primary and secondary UARTs" |
| Pi Zero W, Zero 2 W, Pi 3, Pi 4 (and 400): primary UART is `UART1` (mini UART, `/dev/ttyS0`); the PL011 is wired to Bluetooth. | same page, same table |
| The mini UART has no parity, smaller FIFOs, no flow control, and its baud clock follows the VPU core clock; it is disabled when the core clock is variable and needs `enable_uart=1` (which fixes the core at 250 MHz) to work as primary. Raspberry Pi describes it as more prone to losing characters at higher baud rates. | same page, "UART types" and "Mini UART and core frequency" |
| To put the PL011 on the GPIO pins instead: `sudo systemctl disable hciuart`, add `dtoverlay=disable-bt` to `/boot/firmware/config.txt`, reboot. Alternative that keeps Bluetooth: `dtoverlay=miniuart-bt` plus a fixed core clock (`core_freq=250` or `force_turbo=1`). | same page, "Disable Bluetooth and make UART0 primary" / "Switch Bluetooth to use mini UART" |
| The installer already tells the user to disable Bluetooth with `dtoverlay=disable-bt` and `systemctl disable hciuart`, and the gateway's "port not found" error hint asks whether `dtoverlay=disable-bt` is set. | fabcoded/blaueis-libmidea: `scripts/install.sh` ("Serial Port Exclusivity"); `server.py` `_uart_loop` FileNotFoundError branch |
| Pi 5 / 500 / CM5: no mini UART; `UART0`–`UART4` on the GPIO header are PL011 but disabled by default; the primary UART (and therefore `/dev/serial0`) is the 3-pin debug header `UART10` (`/dev/ttyAMA10`). Bluetooth uses a dedicated UART, so there is no Bluetooth conflict. GPIO 14/15 need the `uart0-pi5` overlay. | same page, tables "UART by Raspberry Pi model" and "Primary and secondary UARTs"; "Enable additional UARTs" |
| `enable_uart` defaults to 1 when the primary UART is PL011 and to 0 when it is the mini UART. | https://www.raspberrypi.com/documentation/computers/config_txt.html (`enable_uart`); configuration page, "Default enable_uart behaviour" |
| The serial login console must be released: `sudo raspi-config` → `3 Interface Options` → `I6 Serial Port` → login shell **No**, serial hardware **Yes**, reboot. | configuration page, "Disable the Linux serial console"; the same steps are printed by fabcoded/blaueis-libmidea `scripts/install.sh` |
| The service user must be in `dialout` to open the port; the installer does this, and the gateway logs the `usermod -aG dialout` fix on `PermissionError`. | fabcoded/blaueis-libmidea: `docs/operations.md` §1 and §6; `server.py` `_uart_loop` |

### 1.2 The AC-side connector and signal levels

| Fact | Source |
|---|---|
| The bus the gateway impersonates is the Wi-Fi dongle ↔ mainboard UART, 9600 bps 8N1, reached through the connector labelled CN3 on the display board of the unit we captured. | fabcoded/blaueis-hvacshark: `protocols/midea/spec/protocol_uart.md` §1.1–1.2; `protocols/midea/devices/device_xtremesaveblue.md` §1 |
| CN3 carries two unidirectional UART wires (brown and orange on our unit); each direction is a separate wire, not a half-duplex line. | fabcoded/blaueis-hvacshark: `protocols/midea/spec/protocol_uart.md` §4.3 |
| The UART signal level is 5 V TTL. | fabcoded/blaueis-hvacshark: `protocols/midea/spec/protocol_shared.md` §8 (bus table: "5 V TTL, CN3 connector"); https://github.com/reneklootwijk/node-mideahvac/blob/master/custom-dongle.md; https://github.com/reneklootwijk/midea-uartsniffer/blob/master/ADAPTER.md |
| The AC does not appear to accept 3.3 V logic; a level shifter is required when building a dongle from a 3.3 V microcontroller. | https://esphome.io/components/climate/midea.html (UART section) |
| Raspberry Pi UARTs are 3.3 V; connecting them to a 5 V system causes damage; use a level shifter. GPIO inputs are 3.3 V-tolerant only. | configuration page, "UART types" warning; https://www.raspberrypi.com/documentation/computers/raspberry-pi.html ("Voltage specifications") |
| Therefore a **bidirectional 5 V ↔ 3.3 V level shifter on TX and RX** is mandatory for a GPIO-UART wiring (AC TX would damage the Pi; Pi TX would not be seen by the AC). | conjunction of the two rows above |
| Units expose either a USB-A-shaped female socket or a JST-XH male header for the dongle. Pin assignment on both, same numbering: 1 = 5 V, 2 = RX, 3 = TX, 4 = GND (RX/TX from the dongle's point of view). | https://github.com/reneklootwijk/node-mideahvac/blob/master/custom-dongle.md (pin table, photos `pics/USB.jpeg`, `pics/JST-XH.jpeg`); https://github.com/reneklootwijk/midea-uartsniffer/blob/master/ADAPTER.md |
| Independent confirmation of the same pair: USB pin 2 (D−) carries the appliance's transmit line, pin 3 (D+) its receive line, pin 4 is 5 V power in that write-up's numbering — i.e. sources agree on "one data pin per direction, power and ground on the outer pins", but not on which USB pin number is 5 V vs GND. | https://github.com/Chreece/ESPHome-Dehumidifier (USB-A pin table) |
| Some indoor units label the four pads on the PCB (GND, VCC, TX, RX) and use a keyed USB-A socket with extra ridges that a plain USB plug does not fit without force. | https://www.digitalforgesystems.com/2024/09/removing-the-chinese-wifi-from-midea-mr-cool-minisplit-with-esphome/ |
| Some display boards have CN3 as a 5-pin right-angle JST footprint, and on at least one board the 5 V pin of CN3 is only powered when a 0 Ω link is populated. | https://community.home-assistant.io/t/midea-branded-ac-s-with-esphome-no-cloud/265236/1181 |
| TX/RX naming is perspective-dependent and a frequent source of swapped wiring; our own troubleshooting already says "check physical wiring polarity" when the AC never replies. | https://community.home-assistant.io/t/midea-branded-ac-s-with-esphome-no-cloud/265236 (post 3); fabcoded/blaueis-libmidea: `docs/operations.md` §6 "Gateway starts but never reaches RUNNING" |
| Ground must be shared between Pi and AC (the pinout has a GND pin for that reason). | node-mideahvac pin table above |

### 1.3 Power

| Fact | Source |
|---|---|
| The port supplies 5 V; community dongles power an ESP from it through a regulator. | node-mideahvac `custom-dongle.md`; midea-uartsniffer `ADAPTER.md`; https://github.com/reneklootwijk/mideahvac-dongle |
| The OEM Wi-Fi Smart Kit (US-SK103 / EU-OSK105 family) is rated "Power input: DC 5V/300mA". That is the only published figure for what the port is designed to deliver. | https://www.manualslib.com/manual/1493154/Midea-Us-Sk103.html (specification table); FCC filing 2ADQOMDNA19 user manual https://fccid.io/2ADQOMDNA19/User-Manual/User-manual-of-US-SK103-4101817 |
| Typical bare-board active current per Pi model: Zero 100 mA, Zero W 150 mA, Zero 2 W 350 mA, 3B 400 mA, 3B+ 500 mA, 4B 600 mA, 5 800 mA; boot and stress peaks are higher (e.g. Zero 0.20 A boot / 0.35 A stress, 3B 0.75 A / 1.34 A, 4B 0.85 A / 1.25 A). All models require a 5.1 V supply; recommended PSU 1.2 A (Zero/Zero W), 2 A (Zero 2 W), 2.5 A (Pi 3), 3 A (Pi 4), 5 A (Pi 5). | https://www.raspberrypi.com/documentation/computers/raspberry-pi.html ("Typical power requirements") |
| Consequence the paragraph can state: only a Pi Zero / Zero W sits inside the 300 mA figure at typical load, and nothing sits inside it at boot peaks; do not power the Pi from the AC port — use the Pi's own supply and connect only GND, TX, RX (through the shifter). | derived from the two rows above |
| Raspberry Pi warns that feeding 5 V into the board from a downstream device bypasses its input protection circuitry. | https://www.raspberrypi.com/documentation/computers/raspberry-pi.html ("Back-powering") |

### 1.4 Software and safety

| Fact | Source |
|---|---|
| Gateway requires Python ≥ 3.11 (`requires-python`); the installer aborts without it. | fabcoded/blaueis-libmidea: `packages/blaueis-gateway/pyproject.toml`; `scripts/install.sh`; `README.md` |
| Raspberry Pi OS Bookworm (Debian 12) ships Python 3.11.2; Bullseye (Debian 11) ships 3.9.2. So "Bookworm or newer" is the statable OS requirement. | https://packages.debian.org/bookworm/python3; https://packages.debian.org/bullseye/python3 |
| Install is one `curl | bash` line that creates the service user, venv and systemd template; it does not start a service. | fabcoded/blaueis-libmidea: `docs/operations.md` §1; `README.md` "Quick start" |
| The HA side needs Home Assistant 2024.10+ and a reachable gateway (host / port / PSK). | fabcoded/blaueis-ha-midea: `README.md` |
| Opening the indoor unit exposes mains wiring; the project's existing disclaimer already says the code should not encourage anyone to work on their HVAC system and disclaims injury/damage. The "What you need" paragraph should carry the same warning. | fabcoded/blaueis-hvacshark: `README.md` "Disclaimer and intended use" |

## 2. Gaps needing measurement or a photo

1. **CN3 on our unit — photo, pin count, pitch, wire colours.** Our docs name CN3 and two wire colours (brown/orange) but never say how many pins it has, its pitch, or what the other pins carry. A community board shows a 5-pin CN3; the OEM harness on most units ends in a USB-A-shaped socket. A photo of CN3, of the harness, and of the socket the OEM dongle plugs into is needed before the paragraph can tell a reader what to buy (USB-A plug vs JST-XH housing vs bare pins).
2. **Which CN3 wire is AC-TX.** Our own public docs disagree: `protocol_uart.md` §4.3 says brown = dongle TX → display RX (`toACdisplay`) and orange = display TX → dongle RX; the traces repo's Session 1 `SessionNotes.md` labels brown as "Wi-Fi module RX (display → wifi)" and orange as "Wi-Fi module TX". One of them is the pre-validation naming (Session 2 had the probes physically swapped). Needs one scope/meter check and a fix in whichever file is wrong.
3. **Port current capability.** 300 mA is the OEM kit's rating, not the port's limit. Measure the CN3 5 V rail under load (regulator part number on the display board, or a load test) before saying anything stronger than "do not power the Pi from it".
4. **Does the CN3 5 V pin need a populated link on our board?** One community board needed a 0 Ω resistor moved to bring 5 V to CN3. Verify with a meter on our unit.
5. **Level-shifter type actually validated.** Nothing in our repos says what shifter (BSS138 auto-direction board, 74AHCT/74LVC pair, resistor divider) sits between our Pi and CN3, or that one is used at all. Record the part used on the live gateway and, ideally, a scope shot of an AC-side edge at 9600 baud through it.
6. **Pi model and OS we run.** No public doc names the Pi model or OS release of the live gateway (`cat /proc/device-tree/model`, `/etc/os-release`). The paragraph should be able to say "tested on X".
7. **Pi 5 path untested.** The docs say `serial0` is the debug header on Pi 5, so the gateway default `/dev/serial0` would not be the GPIO UART; the expected fix (`dtoverlay=uart0-pi5`, `uart_port: /dev/ttyAMA0`) is derived from Raspberry Pi docs, not tried.
8. **USB-serial adapter path untested.** A 5 V-TTL USB-UART adapter (`/dev/ttyUSB0`) would remove the level-shifter requirement entirely; the installer accepts it but nobody has run the gateway that way.
9. **Mini-UART-as-primary at 9600 baud.** Whether the gateway is reliable on `/dev/ttyS0` without `disable-bt` (i.e. with Bluetooth left on) is not measured; the installer simply tells users to disable Bluetooth.
10. **USB pin numbering.** Sources agree on the electrical roles but number the outer pins differently (5 V = pin 1 vs pin 4). A photo of a USB-A plug with the four pads labelled, taken on our bench, settles it for the docs.

## 3. Where it is already documented in our repos

| Topic | Present today | Missing |
|---|---|---|
| `/dev/serial0`, 9600 baud, `dialout`, config keys | libmidea `docs/operations.md` §1, §3.1, §6; `README.md` | — |
| Disable serial console, disable Bluetooth (`disable-bt`, `hciuart`), check for other UART users | libmidea `scripts/install.sh` (printed at install time only); `server.py` error hint | Not in any `docs/*.md`; the model table (which Pi has the mini UART on the pins) is nowhere |
| "Pi connected to the AC's CN3 connector, impersonating the OEM Wi-Fi dongle" | ha-midea `README.md` "Architecture" | Nothing on pinout, level, connector type, power |
| CN3 = Wi-Fi dongle connector, two unidirectional wires, brown/orange, 9600 8N1 | hvacshark `protocols/midea/spec/protocol_uart.md` §1.2, §4.3; `devices/device_xtremesaveblue.md` §1; traces `Midea-XtremeSaveBlue-logicanalyzer/README.md` | Pin count / pitch / photo; the two docs disagree on wire direction (gap 2) |
| "5 V TTL, CN3 connector" | hvacshark `protocols/midea/spec/protocol_shared.md` §8 (one table cell, in a project-internal bus-classification table) | Not stated anywhere a reader installing the gateway would look |
| Wiring polarity as a failure cause | libmidea `docs/operations.md` §6 | — |
| `tools/dongle/` | hvacshark `tools/dongle/mid-xye/` is the **XYE RS-485** sniffer (ESP32 + Python bridge), not a Wi-Fi-UART dongle | Nothing there about CN3 |
| Level shifting, power budget, Pi model guidance, OS release | — | Entirely absent from all four repos |

Corrections to make in our own docs while writing the paragraph (all public files):

- `scripts/install.sh` says Bluetooth shares the PL011 on "Pi 3/4/5". Per Raspberry Pi, Pi 5 has Bluetooth on a dedicated UART and no mini UART; the models that do share are Zero W, Zero 2 W, 3 and 4 (and 400).
- `scripts/install.sh` points at `/boot/config.txt`; Raspberry Pi documents `/boot/firmware/config.txt` for Bookworm and later.
- `server.py` FileNotFoundError hint names `/etc/blaueis/instances/<name>.yaml`; the documented directory is `/etc/blaueis-gw/instances/`.
- `docs/operations.md` §1 says "Bookworm / Bullseye" while requiring Python 3.11; Bullseye ships 3.9.

## 4. Sources

Public Blaueis repos (workspace copies read; cite by repo and path):

- fabcoded/blaueis-libmidea — `README.md`; `docs/operations.md`; `scripts/install.sh`; `packages/blaueis-gateway/pyproject.toml`; `packages/blaueis-gateway/src/blaueis/gateway/server.py`; `packages/blaueis-gateway/src/blaueis/gateway/configure.py`
- fabcoded/blaueis-ha-midea — `README.md`
- fabcoded/blaueis-hvacshark — `README.md`; `protocols/midea/spec/protocol_uart.md`; `protocols/midea/spec/serial_protocol.md`; `protocols/midea/spec/protocol_shared.md`; `protocols/midea/devices/device_xtremesaveblue.md`; `tools/dongle/mid-xye/py-mid-xye/README.md`
- fabcoded/blaueis-hvacshark-traces — `Midea-XtremeSaveBlue-logicanalyzer/README.md`; `Midea-XtremeSaveBlue-logicanalyzer/Session 1/SessionNotes.md`

Raspberry Pi (official):

- https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts — UART types, per-model primary/secondary UART table, device names, mini UART and core clock, serial console, `disable-bt` / `miniuart-bt`, Pi 5 (source text: `documentation/asciidoc/computers/configuration/interfaces.adoc` in github.com/raspberrypi/documentation)
- https://www.raspberrypi.com/documentation/computers/raspberry-pi.html — GPIO voltage specifications, TX GPIO14 / RX GPIO15, typical power requirements table, back-powering (`raspberry-pi/gpio-on-raspberry-pi.adoc`, `raspberry-pi/power-supplies.adoc`)
- https://www.raspberrypi.com/documentation/computers/config_txt.html — `enable_uart` (GPIOs 14/15 = header pins 8/10)

Community documentation of the dongle connector:

- https://github.com/reneklootwijk/node-mideahvac/blob/master/custom-dongle.md — USB-A / JST-XH pin table, 5 V TTL, level shifter + regulator, 9600 8N1
- https://github.com/reneklootwijk/midea-uartsniffer/blob/master/ADAPTER.md — same pin table, inline sniffer wiring
- https://github.com/reneklootwijk/mideahvac-dongle — 5 V TTL statement, USB-A vs JST-XH variants
- https://github.com/dudanov/MideaUART — 9600 8N1 (no wiring detail in the README)
- https://esphome.io/components/climate/midea.html — 5 V logic required, 3.3 V does not work, use a level shifter; `baud_rate: 9600`
- https://github.com/Chreece/ESPHome-Dehumidifier — USB-A pin roles (D− = appliance TX, D+ = appliance RX)
- https://www.digitalforgesystems.com/2024/09/removing-the-chinese-wifi-from-midea-mr-cool-minisplit-with-esphome/ — keyed USB-A socket, PCB pad labels
- https://community.home-assistant.io/t/midea-branded-ac-s-with-esphome-no-cloud/265236 — wire colours, TX/RX perspective warning (post 3), 4-pin JST variant (post 14); post 1181 — 5-pin CN3 footprint and the 5 V link
- https://www.manualslib.com/manual/1493154/Midea-Us-Sk103.html and https://fccid.io/2ADQOMDNA19/User-Manual/User-manual-of-US-SK103-4101817 — OEM Smart Kit "DC 5V/300mA"

Debian package versions:

- https://packages.debian.org/bookworm/python3 (3.11.2); https://packages.debian.org/bullseye/python3 (3.9.2)
