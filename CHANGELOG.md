# Changelog

Notable changes to the Blaueis Midea integration.

## [Unreleased]

### Fixed
- **Climate presets are now mode-aware.** A preset invalid in the current
  operating mode (e.g. Frost Protection in cool) is no longer offered in the
  dropdown, so it can't be selected and rejected. Presets stay mutually
  exclusive (only one active), the displayed selection is always one of the
  offered options, and a rejected/unapplied preset now reverts the card to the
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
