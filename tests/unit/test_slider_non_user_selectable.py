"""Slider behavior when the AC reports a non-user-selectable raw.

A NumberEntity in slider mode can't represent an AC-controlled
"released" state (e.g. ``louver_swing_angle_lr_enum = 0`` reported
during swing mode). Returning the raw clamped to ``min`` would
display a phantom position. Instead, ``native_value`` returns
``None`` so HA renders the slider's state as unknown, while
``available`` stays True so the user can still drag to engage a
real position.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.blaueis_midea.number import BlaueisMideaSlider


def _coord(*, current_raw: int | None) -> MagicMock:
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.connected = True
    coord.device_fresh = True
    gdef = {
        "values": {
            "off": {
                "raw": 0,
                "user_selectable": False,
                "label": "-- (0)",
            },
            "left": {"raw": 1, "label": "Far Left (1)"},
            "left_mid": {"raw": 25, "label": "Left (25)"},
            "center": {"raw": 50, "label": "Center (50)"},
            "right_mid": {"raw": 75, "label": "Right (75)"},
            "right": {"raw": 100, "label": "Far Right (100)"},
        },
    }
    coord.device.field_gdef.return_value = gdef
    coord.device.read.side_effect = lambda name: (
        current_raw
        if name == "louver_swing_angle_lr_enum"
        else (True if name == "power" else None)
    )
    coord.device.set = AsyncMock(
        return_value={"expanded": {}, "rejected": {}, "results": {}}
    )
    return coord


def _fmeta() -> dict:
    return {
        "active_constraints": {
            "slider": {
                "name": "Louver Angle LR",
                "range": [1, 100],
                "step": 1,
                "mode": "clamp",
            },
            "valid_set": [1, 25, 50, 75, 100],
        },
    }


def _make_slider(coord) -> BlaueisMideaSlider:
    return BlaueisMideaSlider(coord, "louver_swing_angle_lr_enum", _fmeta())


# ── Set construction ────────────────────────────────────────────────


def test_non_user_selectable_set_built_from_glossary():
    sl = _make_slider(_coord(current_raw=1))
    assert sl._non_user_selectable_raws == {0}


# ── native_value behavior ───────────────────────────────────────────


def test_native_value_returns_none_for_released_state():
    """When AC reports raw=0 (non-user-selectable), the slider must
    not clamp it up to min=1 and lie about the position."""
    sl = _make_slider(_coord(current_raw=0))
    assert sl.native_value is None


def test_native_value_normal_for_user_selectable_raw():
    sl = _make_slider(_coord(current_raw=25))
    assert sl.native_value == 25.0


def test_native_value_clamps_off_grid_user_value():
    """An off-grid user-selectable read (e.g. 23 from external control)
    still clamps to slider range — that's distinct from the released
    state and represents a real position."""
    sl = _make_slider(_coord(current_raw=23))
    assert sl.native_value == 23.0  # within range, no clamp triggers


def test_native_value_none_when_field_unread():
    sl = _make_slider(_coord(current_raw=None))
    assert sl.native_value is None


# ── available stays True so user can still drag ─────────────────────


def test_available_remains_true_during_released_state():
    """The slider stays available so the user can engage a position;
    only native_value reflects the unknown state."""
    sl = _make_slider(_coord(current_raw=0))
    assert sl.available is True
