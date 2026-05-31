"""Unit tests for the per-axis swing / vane-position mapping (``_swing.py``).

The climate entity folds oscillation ("swing") and the fixed vane positions
into ONE native enum per axis (``swing_mode`` = vertical,
``swing_horizontal_mode`` = horizontal). On the hardware the two are mutually
exclusive, so a tap sends exactly one field and the firmware enforces the
exclusion by clearing the sibling.

These tests cover the pure mapping across every capability combination, the
single-field-per-tap invariant, and tie the position grid back to the real
glossary so the HA option strings and the codec values can't silently drift.
"""

import pytest

from custom_components.blaueis_midea._swing import (
    axis_mode,
    axis_options,
    axis_set_changes,
)
from custom_components.blaueis_midea.const import (
    POS_LABELS,
    SWING_AXES,
    SWING_OFF,
    SWING_ON,
    SWING_ON_RAW,
)

# Position option strings in raw order, per axis (Gree scheme — see POS_LABELS).
VPOS = ["upper", "upper_middle", "middle", "lower_middle", "lower"]
HPOS = ["left", "left_center", "center", "right_center", "right"]
RAWS = [1, 25, 50, 75, 100]
AXES = ["vertical", "horizontal"]
AXIS_POS = [("vertical", VPOS), ("horizontal", HPOS)]


def _avail(*fields):
    """A minimal available_fields mapping (only the keys are inspected)."""
    return {f: {} for f in fields}


def _reader(values):
    """A read(field) -> raw callable backed by a dict (missing key -> None)."""
    return lambda name: values.get(name)


def _fields(axis):
    return SWING_AXES[axis]["swing"], SWING_AXES[axis]["angle"]


# ── axis_options: one list per capability combo ───────────────────────────
@pytest.mark.parametrize("axis,pos", AXIS_POS)
def test_options_both_caps(axis, pos):
    sw, ang = _fields(axis)
    assert axis_options(axis, _avail(sw, ang)) == [SWING_OFF, SWING_ON, *pos]


@pytest.mark.parametrize("axis", AXES)
def test_options_swing_only(axis):
    sw, ang = _fields(axis)
    assert axis_options(axis, _avail(sw)) == [SWING_OFF, SWING_ON]


@pytest.mark.parametrize("axis,pos", AXIS_POS)
def test_options_position_only(axis, pos):
    sw, ang = _fields(axis)
    assert axis_options(axis, _avail(ang)) == [SWING_OFF, *pos]


@pytest.mark.parametrize("axis", AXES)
def test_options_neither(axis):
    assert axis_options(axis, _avail()) == [SWING_OFF]


# ── axis_mode: getter round-trip ──────────────────────────────────────────
@pytest.mark.parametrize("axis", AXES)
def test_mode_swing_wins_over_stale_angle(axis):
    sw, ang = _fields(axis)
    # Swinging AND a non-zero angle still present -> "swing" takes priority.
    m = axis_mode(axis, _avail(sw, ang), _reader({sw: SWING_ON_RAW, ang: 50}))
    assert m == SWING_ON


@pytest.mark.parametrize("axis,pos", AXIS_POS)
def test_mode_positions(axis, pos):
    sw, ang = _fields(axis)
    for raw, opt in zip(RAWS, pos):
        assert axis_mode(axis, _avail(sw, ang), _reader({sw: 0, ang: raw})) == opt


@pytest.mark.parametrize("axis", AXES)
def test_mode_off(axis):
    sw, ang = _fields(axis)
    assert axis_mode(axis, _avail(sw, ang), _reader({sw: 0, ang: 0})) == SWING_OFF
    # Nothing read yet (None reads) -> off, not a crash.
    assert axis_mode(axis, _avail(sw, ang), _reader({})) == SWING_OFF


@pytest.mark.parametrize("axis", AXES)
def test_mode_offgrid_angle_is_off(axis):
    sw, ang = _fields(axis)
    # Firmware shouldn't emit an off-grid raw, but it must degrade to off.
    assert axis_mode(axis, _avail(sw, ang), _reader({sw: 0, ang: 37})) == SWING_OFF


@pytest.mark.parametrize("axis,pos", AXIS_POS)
def test_mode_roundtrips_set(axis, pos):
    """Whatever _set writes, _mode reads back as the same option."""
    sw, ang = _fields(axis)
    avail = _avail(sw, ang)
    for opt in [SWING_ON, *pos]:
        ch = axis_set_changes(axis, opt, avail, _reader({}))
        assert axis_mode(axis, avail, _reader(ch)) == opt


# ── axis_set_changes: exactly one field per tap ───────────────────────────
@pytest.mark.parametrize("axis", AXES)
def test_set_swing_writes_only_swing(axis):
    sw, ang = _fields(axis)
    assert axis_set_changes(axis, SWING_ON, _avail(sw, ang), _reader({})) == {
        sw: SWING_ON_RAW
    }


@pytest.mark.parametrize("axis,pos", AXIS_POS)
def test_set_position_writes_only_angle(axis, pos):
    sw, ang = _fields(axis)
    for raw, opt in zip(RAWS, pos):
        assert axis_set_changes(axis, opt, _avail(sw, ang), _reader({})) == {ang: raw}


@pytest.mark.parametrize("axis", AXES)
def test_set_off_clears_active_swing(axis):
    sw, ang = _fields(axis)
    # Currently swinging -> off clears the swing field (one field).
    ch = axis_set_changes(axis, SWING_OFF, _avail(sw, ang), _reader({sw: SWING_ON_RAW}))
    assert ch == {sw: 0}


@pytest.mark.parametrize("axis", AXES)
def test_set_off_clears_active_angle(axis):
    sw, ang = _fields(axis)
    # Currently at a fixed position (not swinging) -> off clears the angle field.
    ch = axis_set_changes(axis, SWING_OFF, _avail(sw, ang), _reader({sw: 0, ang: 50}))
    assert ch == {ang: 0}


@pytest.mark.parametrize("axis", AXES)
def test_set_unsupported_returns_none(axis):
    sw, ang = _fields(axis)
    pos0 = VPOS[0] if axis == "vertical" else HPOS[0]
    # A position option but the unit has no angle cap -> unsupported.
    assert axis_set_changes(axis, pos0, _avail(sw), _reader({})) is None
    # The swing option but no swing cap -> unsupported.
    assert axis_set_changes(axis, SWING_ON, _avail(ang), _reader({})) is None
    # A garbage option -> unsupported.
    assert axis_set_changes(axis, "sideways", _avail(sw, ang), _reader({})) is None


@pytest.mark.parametrize("axis", AXES)
def test_every_option_is_single_field(axis):
    """The core invariant: every offered option writes exactly one field,
    from any starting state."""
    sw, ang = _fields(axis)
    avail = _avail(sw, ang)
    for start in ({sw: SWING_ON_RAW}, {sw: 0, ang: 50}, {}):
        for opt in axis_options(axis, avail):
            ch = axis_set_changes(axis, opt, avail, _reader(start))
            assert ch is not None, f"{opt!r} unexpectedly unsupported"
            assert len(ch) == 1, f"{opt!r} wrote {ch!r} (must be single-field)"


# ── Glossary consistency: HA grid must equal the codec values ─────────────
def _glossary_field(name):
    from blaueis.core.codec import load_glossary

    for fields in load_glossary()["fields"].values():
        if isinstance(fields, dict) and name in fields:
            return fields[name]
    raise AssertionError(f"{name} not in glossary")


@pytest.mark.parametrize("axis", AXES)
def test_position_grid_matches_glossary(axis):
    vals = _glossary_field(SWING_AXES[axis]["angle"])["values"]
    glossary_raws = sorted(v["raw"] for v in vals.values() if v["raw"] != 0)
    assert glossary_raws == sorted(POS_LABELS[axis])
    # Each non-zero glossary label equals the HA-displayed option string
    # (HA title-cases "upper_middle" -> "Upper Middle").
    for v in vals.values():
        if v["raw"] == 0:
            continue
        opt = POS_LABELS[axis][v["raw"]]
        assert v["label"] == opt.replace("_", " ").title()


@pytest.mark.parametrize("axis", AXES)
def test_swing_on_raw_matches_glossary(axis):
    vals = _glossary_field(SWING_AXES[axis]["swing"])["values"]
    assert vals["on"]["raw"] == SWING_ON_RAW
    assert vals["off"]["raw"] == 0
