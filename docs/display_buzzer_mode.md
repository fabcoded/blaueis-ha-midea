# Display & Buzzer mode

## What it does

On the device's Controls card you'll find a **Display & Buzzer mode**
select with four options:

| Option | Display LED | Buzzer behaviour | Stored policy | Enforcer running |
|---|---|---|---|---|
| `On` | currently ON | audible | `non_enforced` | no |
| `Off` | currently OFF | silent | `non_enforced` | no |
| `Forced on` | held ON | audible | `forced_on` | yes |
| `Forced off` | held OFF | silent | `forced_off` | yes |

In **non-enforced** modes (`On` / `Off`) the select mirrors the live
state of the AC's display LED — pressing the LED button on the remote
will visibly flip the select option from `On` to `Off` (or vice-versa).
Picking `On`/`Off` from the dropdown sends one toggle frame **only** if
the current state doesn't already match (no spurious chirps).

In **forced** modes (`Forced on` / `Forced off`) the integration
actively re-asserts your choice if the display drifts (e.g. you press
the remote's LED button), with a 15-second cooldown between corrections.
The forced policy is persisted to the config entry, so it survives an
HA restart.

There is no separate display-on/off switch on the device card any more
— this select is the single control for the display LED and the
buzzer-via-display-latch behaviour.

**Why this exists.** On this SKU the firmware couples the display-LED
state and the indoor-unit buzzer: while the display is OFF, the AC
suppresses chimes on every command it receives — including the
`cmd_0xb0` property writes the integration uses to change vane angle.
Live-confirmed 2026-04-20 (see
`blaueis-research/internal-tests/findings/07_display_and_buzzer.md`
§4.8 for the physics, §4.9 for the integration loop, §4.10 for the
quad-option model).

## How enforcement works (forced modes)

In `Forced on` or `Forced off`, the integration subscribes to every AC
state update. When the observed display state drifts from your declared
mode (for example, you pressed the LED button on the remote), the
integration re-issues a toggle command. To avoid fighting your remote,
there's a **15-second cooldown** between correction attempts, and up to
**three retries** within one correction attempt if the AC ignores the
first toggle.

In non-enforced modes the integration does **not** correct drift —
it just mirrors whatever state the AC is in.

## A single chirp on each transition

The `cmd_0x41` toggle frame the AC requires has the "emit UX feedback"
bit set (firmware always chimes on this command family). That means:

- Picking `Off` while display was `On`: the toggle **will chirp once**
  as the display turns off. Afterwards all `cmd_0xb0` writes are silent.
- Picking `On` while display was `Off`: one chirp as the display comes
  back on.
- Picking the same option as current state: no toggle, no chirp.
- Pressing the remote's LED-on while mode is `Forced off`: your press
  chirps (firmware), then the integration toggles the display back off
  within 15 s; that correction toggle also chirps.

There is no silent path through the toggle command on this firmware;
the chirp is fundamental to the frame shape the AC requires.

## When the feature is not available

The Display & Buzzer mode entity **only appears on devices that
advertise the `screen_display` capability** in their B5 response. On
unsupported devices the select entity is not created; you won't see it
in the HA UI.

If a device that previously advertised the cap stops advertising it
(unusual — would require a firmware change or re-pairing), the
integration stops enforcing and the entity goes `unavailable` in the
UI. A one-time WARNING is logged. If the cap returns, the entity
becomes available again and enforcement resumes automatically.

## Reliability caveat

Sometimes the firmware ignores a toggle frame — live captures showed up
to 5 identical toggles in a row before the state flipped. In **forced
modes**, the integration handles this: it reads the state back via
`rsp_0xC0 body[14]` bits[6:4] and retries. You may briefly see the
display stay in the "wrong" state for a few seconds before the
correction takes; that's normal.

In **non-enforced modes** picks are fire-and-forget — if the firmware
ignores the single toggle the select will simply continue mirroring
the (still-wrong) state until you pick again.

## After a disconnect

When the gateway or HA reconnects to the AC, the integration receives a
fresh `rsp_0xC0` and re-evaluates. In a forced mode, if the display
state drifted while we were offline, you may hear one correction chirp
within the first 15 seconds after reconnect. In a non-enforced mode the
select simply picks up the current state — no toggles fired.

## Changing the mode

Two places in HA:

1. **Per-device**: the `select.<device>_display_buzzer_mode` entity on
   the device's Controls card. Changes take effect immediately. Picking
   `Forced on`/`Forced off` writes the choice to the config entry so it
   persists across restarts. Picking `On`/`Off` from a forced state
   resets the stored policy to non-enforced.
2. **Per-config-entry default**: Settings → Devices & Services →
   Blaueis Midea AC → Configure → Display & Buzzer mode. This sets the
   stored policy directly. The dropdown shows three options (the
   non-enforced policy plus the two forced modes); `On`/`Off` are not
   policy values, just live-state mirrors of non-enforced.

## Migration from earlier versions

Earlier versions of this integration used a separate `switch.screen_display`
plus a 3-state mode select (`auto` / `permanent_on` / `permanent_off`).
On upgrade:

- The old switch is removed from the HA entity registry on first load
  (no manual cleanup needed; automations referencing it will need to be
  updated to use the select).
- The stored mode is rewritten: `auto → non_enforced`,
  `permanent_on → forced_on`, `permanent_off → forced_off`.

## See also

- `blaueis-research/internal-tests/findings/07_display_and_buzzer.md`
  §4.8 (physics), §4.9 (integration loop), §4.10 (quad-option model
  live confirmation).
- `architecture.md` — IngressHook + Device.write_lock patterns this
  feature uses.
