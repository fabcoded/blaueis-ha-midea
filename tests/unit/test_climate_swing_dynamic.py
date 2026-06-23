"""The swing option lists are computed LIVE from available_fields.

``swing_modes`` / ``swing_horizontal_modes`` are plain @property overrides that
call ``axis_options`` each read, not a cached __init__ snapshot. So if a cap
leaves available_fields after setup, the offered options shrink immediately and
the dropdown can never offer a vane position the set path then rejects.
"""

from unittest.mock import MagicMock

from custom_components.blaueis_midea.climate import BlaueisMideaClimate

HOST, PORT = "127.0.0.1", 8765
V_SWING = "louver_swing_vertical"
V_ANGLE = "louver_swing_angle_ud_enum"
H_SWING = "louver_swing_horizontal"
H_ANGLE = "louver_swing_angle_lr_enum"

V_FULL = ["off", "swing", "upper", "upper_middle", "middle", "lower_middle", "lower"]
H_FULL = ["off", "swing", "left", "left_center", "center", "right_center", "right"]


def _entity(avail):
    coord = MagicMock()
    coord.host, coord.port = HOST, PORT
    coord.device.available_fields = avail
    coord.device.read = lambda name: None
    entry = MagicMock()
    entry.options = {}
    return BlaueisMideaClimate(coord, entry)


def test_positions_listed_when_angle_available():
    ent = _entity({V_SWING: {}, V_ANGLE: {}, H_SWING: {}, H_ANGLE: {}})
    assert ent.swing_modes == V_FULL
    assert ent.swing_horizontal_modes == H_FULL


def test_options_recompute_live_when_angle_drops():
    # Same dict object the entity reads -> mutating it = a live cap change.
    avail = {V_SWING: {}, V_ANGLE: {}, H_SWING: {}, H_ANGLE: {}}
    ent = _entity(avail)
    assert "upper_middle" in ent.swing_modes

    # Angle caps leave available_fields AFTER __init__ (no entity rebuild).
    del avail[V_ANGLE]
    del avail[H_ANGLE]

    # Plain @property recomputes: positions gone, swing/off remain. The feature
    # itself stays supported (the swing field is still present).
    assert ent.swing_modes == ["off", "swing"]
    assert ent.swing_horizontal_modes == ["off", "swing"]


def test_swing_modes_none_when_feature_absent():
    # Neither swing nor angle for either axis -> feature unsupported -> None.
    ent = _entity({"fan_speed": {}})
    assert ent.swing_modes is None
    assert ent.swing_horizontal_modes is None
