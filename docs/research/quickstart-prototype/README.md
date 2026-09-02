# Quickstart prototype — ticket "The stranger's quickstart"

Throwaway prototype for the 0.1.0 wayfinder map (fabcoded/blaueis-ha-midea#16, ticket #25). `QUICKSTART.md` here is the synthesized draft to react to; `variants/` holds the three independent drafts it was synthesized from (angles: stranger-first, support-burden-first, structure-first). Nothing in this directory is production documentation.

## Structure recommendation

All three variants converged independently on the same home, so it is proposed as the decision:

- **`QUICKSTART.md` at the root of blaueis-ha-midea** — the one end-to-end page (wire → gateway → HACS → connect → update). The stranger lands on the integration (HACS renders its README; the issue tracker lives there); the goal completes in HA; a root file has a stable URL that survives HACS's README-only rendering when the README carries an absolute link.
- **blaueis-ha-midea `README.md`** — gains a four-bullet *Quick start* directly under the description with the absolute link to `QUICKSTART.md`; the *Install* section loses "once published" and the `gateway.yaml:psk` reference and gets the three HACS custom-repository steps; the manual git-clone block moves to `docs/integration.md`; the config-flow paragraph names the dialog title and the two error strings.
- **blaueis-libmidea `README.md`** — *Quick start* becomes: "Home Assistant users: follow the quickstart in blaueis-ha-midea" (absolute link), the release-asset one-liner, a five-line hardware summary, the `blaueis-gw` command table, and the existing developer install.
- **blaueis-libmidea `docs/operations.md`** — stays the gateway reference and is renumbered so §1 is *Hardware and UART* (the canonical wiring table, power rule, per-model UART steps, exclusivity rule); §2 *Install* rewritten for the release-asset installer, the wizard and enable+start; updating puts `blaueis-gw update` first with the developer paths (WebSocket command, scp) under a subsection.
- **Ownership rule** — `operations.md` §1 is canonical for hardware facts; `QUICKSTART.md` §1 is the stranger-depth copy. Both repos ship under one release number during 0.x, so every co-release is the reconciliation point: if they disagree, `operations.md` wins and the quickstart is corrected in the same release.

## Synthesis notes

- Skeleton and stage table from *structure*; checkpoints, the multimeter check and the failure table from *stranger*; the reporting checklist, PSK recovery command and "do not paste the PSK" from *support*.
- The two maintainer TODOs every variant left were filled from the gateway source: the handshake completes with the log line `ANNOUNCE → RUNNING`; a silent AC shows as repeated `DISCOVER: no response, retrying in 5.0s`; startup prints `Starting gateway <version> on ws://…` and `UART connected`; `blaueis-gw status` shows systemd's `active (running)`.
- **Engineering call made here:** the variants disagreed on where the level shifter's 5 V reference comes from. The draft feeds both references from the Pi (header pin 2 = 5 V, pin 1 = 3.3 V) and leaves CN3 pin 1 unconnected — the AC's 5 V never leaves the AC, "share GND only" stays literally true, and there is one fewer way to put 5 V on a Pi pin. The alternative (reference from CN3 pin 1) works electrically and matches the AC's own logic level exactly; the bench-check ticket (#26) should record which the live gateway uses.
- Header pin numbers 1 (3.3 V), 2 (5 V) and 6 (GND) are the standard 40-pin layout; the hardware research cited only pins 8/10.
- Deliberately not mentioned: USB-serial adapters (untested against the AC's 5 V UART), the license (both READMEs still say CC0; the map decided MIT), and the exact raspi-config prompt wording (paraphrased).

## Doc-parity items the drafts exposed (release-checklist input)

Current public docs contradict the decided 0.1.0 state in these places; all must change in the same release: the installer URL (`raw…/main/scripts/install.sh` → `releases/latest/download/install.sh`) in libmidea README and `operations.md` §1; `operations.md` §1 "does not start a service" and its Bullseye mention; ha-midea README "vendored under `lib/`", "once published" and `gateway.yaml:psk`; the CC0 license lines in both READMEs.

## Open points

- Confirm on the bench (ticket #26): CN3 photo and pitch, which CN3 pin is the AC's TX on our unit, the shifter wiring actually in use, whether CN3 pin 1 needs to be populated for the AC to talk.
- The switches decision (ticket #20) may add a line to stage 4's "what you should see".
- Whether `gateway.local` resolves from the HA host depends on mDNS; the draft offers the IP as the fallback.

## Review round (four parallel reviewers, distinct lenses, ~1 minute)

28 findings, 3 blocking — all folded into the draft (v2):

- **Power sequence in the hardware stage contradicted itself** (stranger lens): the intro said "power up only after wiring", 2.1 measured with the AC on, and the UART prep needed a booted Pi. Fix: the Pi is prepared first as its own stage (OS check, serial console off, model step, reboot, checkpoint), the wiring stage states its power sequence once (measure with the AC on and nothing connected → AC off → wire → Pi first, then AC).
- **A multimeter was required but not listed** (stranger lens): added to *Before you start*; the check now carries the mains warning the hardware reviewer asked for (DC volts, touch only the CN3 pins).
- **PyPI packages are installed when the integration is first added, not on the post-HACS restart** (HA lens): moved to stage 5 step 1, with the internet-access note and "can take a minute"; the stage-4 checkpoint no longer misattributes a missing entry to the restart.

Minor findings applied: the 300 mA rating carries no vendor attribution; "any shifter does the job" became "a BSS138-type module should work; none is verified"; `ws://<host>:8765` instead of a bind address; the Zero/3/4 checkpoint now observes `serial0 → ttyAMA0` (vs `ttyS0`); `blaueis-gw configure` is followed by a systemd restart; back-powering note when the Pi is off and the AC on; "the AC's 5 V supply pin is never used" (its data levels do reach the shifter); the hostname example is qualified with "the IP is the safe choice"; Follow Me dropped from *Next*.

Fact-checker findings not applied, deliberately: the per-model current range and the multimeter check are engineering additions the maintainer stands behind; the Pi header pins 1/2/6 are the standard layout; `docs/integration.md` and `docs/operations.md` exist.
