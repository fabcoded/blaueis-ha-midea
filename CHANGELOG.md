# Changelog

Notable changes to the Blaueis Midea integration.

## [Unreleased]

### Changed
- **Unique ids are keyed on the config entry, not the gateway address.**
  Every entity `unique_id` is now `{entry_id}_{suffix}` and the two
  devices are `{entry_id}_ac` / `{entry_id}_gw`, so a changed host or
  port can no longer produce a duplicate device with fresh entities.
  Existing installs migrate in place on the first setup after the update:
  entity ids, names, settings, history and both devices are kept, and
  nothing changes in the UI. See `docs/integration.md` §4.5.
- **BREAKING: session protocol v2.** The vendored library now speaks
  protocol v2 (direction-separated encryption keys and nonces, scrypt
  PSK stretching, key confirmation during connect, gateway pre-auth
  connection cap). A v2 integration cannot talk to a v1 gateway —
  update the gateway and the integration together.
- **License changed from CC0 to the MIT License.** The repository was
  previously dedicated to the public domain; it is now distributed
  under MIT, which requires keeping the copyright and license notice
  in copies and derivative works.

### Added
- **Repairs issue when the gateway stays unreachable.** If the gateway
  cannot be reached for 15 minutes — setup keeps failing, or a running
  entry's connection drops and does not come back — a warning issue
  appears in Repairs (one per config entry). Shorter outages stay silent,
  and the issue clears itself on the next successful connection. See
  `docs/integration.md` §7.2.
- **Reauthentication flow.** A wrong PSK is now detected during the
  config flow and at startup (key confirmation) and surfaces as
  "invalid authentication" instead of a connection error. If the
  gateway starts rejecting the stored key at runtime (key rotated),
  HA prompts for the new PSK instead of retrying forever. Only a
  cryptographically confirmed mismatch triggers this — transient
  handshake failures (gateway connection pool full, version-mismatch
  close) stay ordinary connection errors and keep retrying.

### Fixed
- **The AC device no longer shows the gateway's version.** Its
  `sw_version` carried the gateway's version string; the AC's own
  firmware version is unknown, so the field is now empty (and a stored
  value is cleared on setup). The gateway device keeps its version.
- **A failed setup no longer leaks its debug ring.** The in-memory debug
  log was attached before the gateway connect but only detached on
  unload, which HA never runs for a setup that failed — so every retry
  against an unreachable gateway stacked another handler (up to 5 MB
  each). Every failed setup path now detaches it.
- **Field-rename migration survives a duplicate.** When both the old and
  the renamed unique_id were registered, the migration raised and setup
  failed. It now keeps the entity that already has the new id, removes
  the stale one, and logs a warning.
- **No false "connected" after the gateway restarts.** A gateway restart
  could leave the integration showing "connected" for a link that had
  already dropped, and a reconnect could send one plaintext message
  before the key was confirmed. The vendored library now reports
  connected only for a link that is still up, sends nothing until the
  key is confirmed, and the gateway closes a connection that sends bad
  input cleanly instead of leaving it half-open.
- **Swing "off" releases a fixed vane position.** Selecting `off` while
  the vane was parked at a fixed position wrote an angle reset the
  firmware ignores, so the vane stayed put. It now engages swing and then
  stops it (two writes). Units without a swing capability keep the old
  single write.
- **Stale slider numbers are now cleaned up.** The registry sweep
  skipped every `<field>_slider` number, so a slider whose field left
  `available_fields` survived as a permanently unavailable ghost. Sliders
  now follow their base field: removed when the field is no longer
  available, or when its cap no longer offers a slider (the retired
  louver-angle sliders), climate-exclusive or not. The fan-speed slider, which
  sits alongside the climate entity's fan-mode dropdown on purpose, is kept.
- **Configure dialog saves without a Follow Me sensor.** The Follow Me
  source field was rendered with an empty default the entity selector
  rejects, so an entry with no sensor configured could not save the
  dialog at all — not even a glossary override. The field now has no
  default until a sensor is picked; leaving it untouched keeps it unset.
- **Entities of deleted glossary fields are now cleaned up.** The
  registry sweep only recognised fields still present in the glossary,
  so an entity whose field had been removed outright (`run_status`,
  dropped in May) survived as a permanently unavailable `restored`
  ghost. A `_REMOVED_FIELDS` table now lists such fields and the sweep
  removes their sensor and any slider on next setup.
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
