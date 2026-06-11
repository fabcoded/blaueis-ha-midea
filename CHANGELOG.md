# Changelog

Notable changes to the Blaueis Midea integration.

## [Unreleased]

### Changed
- **BREAKING: session protocol v2.** The vendored library now speaks
  protocol v2 (direction-separated encryption keys and nonces, scrypt
  PSK stretching, key confirmation during connect, gateway pre-auth
  connection cap). A v2 integration cannot talk to a v1 gateway —
  update the gateway and the integration together.

### Added
- **Reauthentication flow.** A wrong PSK is now detected during the
  config flow and at startup (key confirmation) and surfaces as
  "invalid authentication" instead of a connection error. If the
  gateway starts rejecting the stored key at runtime (key rotated),
  HA prompts for the new PSK instead of retrying forever. Only a
  cryptographically confirmed mismatch triggers this — transient
  handshake failures (gateway connection pool full, version-mismatch
  close) stay ordinary connection errors and keep retrying.

### Fixed
- **Wrong PSK no longer passes validation.** Previously the handshake
  carried no key confirmation, so entry setup succeeded with a wrong
  key and every later message failed to decrypt in a silent retry
  loop. Validation now fails fast, and a credential failure during
  reconnect stops the retry loop and asks for reauthentication.
- **Climate presets are now power- and mode-aware.** While the unit is off no
  presets are offered (they can't engage), and a preset invalid in the current
  operating mode (e.g. Frost Protection in cool) is no longer offered either —
  so neither can be selected and then rejected. Presets stay mutually exclusive
  (only one active), the displayed selection is always one of the offered
  options, and a rejected/unapplied preset reverts the card to the
  actually-active selection instead of leaving the attempted pick showing.
- **Vane positions no longer silently break mid-session.** After boot, the
  device can push unsolicited B5 capability frames that inconsistently report
  the B0 vane-angle caps (0x09 / 0x0A) as not-supported. These were re-applied
  live and demoted the angle fields out of the active set, so selecting a vane
  position became a silent no-op until the next restart. Capabilities are now
  frozen after the single boot scan: a later B5 may *escalate* availability but
  can no longer *demote* a field confirmed at boot. Each blocked demotion is
  logged and counted (`frame_counts.cap_demotions_blocked`) so the source stays
  observable.

### Changed
- **Swing / vane option lists are computed live** from current capabilities
  instead of a cached setup-time snapshot, so the dropdown never offers a
  position the set path would reject.
- **Fan: off-grid speeds now show a blank tile** instead of a synthetic
  "Custom" entry; the fan dropdown lists only the named presets.

### Added
- Swing / vane-position option labels are now translated (e.g. `upper_middle`
  → "Upper Middle", `left_center` → "Left Center") instead of rendering raw
  slugs.
