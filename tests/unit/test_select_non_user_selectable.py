"""Select-entity behavior when the AC reports a non-user-selectable raw.

Some glossary fields (e.g. ``louver_swing_angle_lr_enum``) include
values that the AC sets internally but the user can't legitimately
write — typically a "released" / "AC controls vane" raw=0 reported
while swing mode is active. The integration:

- includes such labels in ``options`` only when they're the current
  state, so HA can render the truthful state without falling back to
  ``unknown``;
- treats picking such an option in the UI as a no-op write, so the AC
  doesn't receive a bogus value the glossary says only it should set.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.blaueis_midea.select import BlaueisMideaSelect


def _coord(*, current_raw: int | None) -> MagicMock:
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.hass.config.language = "en"
    coord.connected = True
    coord.device_fresh = True
    gdef = {
        "label": "Louver Angle LR",
        "field_class": "stateful_enum",
        "data_type": "uint8",
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
        current_raw if name == "louver_swing_angle_lr_enum" else None
    )
    coord.device.set = AsyncMock(
        return_value={"expanded": {}, "rejected": {}, "results": {}}
    )
    return coord


def _make_select(coord) -> BlaueisMideaSelect:
    return BlaueisMideaSelect(coord, {"field_name": "louver_swing_angle_lr_enum"})


# ── Static base options ──────────────────────────────────────────────


def test_static_options_exclude_non_user_selectable():
    """At init, _attr_options must list only user-selectable labels."""
    sel = _make_select(_coord(current_raw=1))
    assert sel._attr_options == [
        "Far Left (1)",
        "Left (25)",
        "Center (50)",
        "Right (75)",
        "Far Right (100)",
    ]


# ── Dynamic options (the fix) ────────────────────────────────────────


def test_options_include_non_user_selectable_when_current():
    """When current raw maps to a non-user-selectable label, surface
    it via the dynamic ``options`` property so HA can render the state."""
    sel = _make_select(_coord(current_raw=0))
    assert "-- (0)" in sel.options


def test_options_omit_non_user_selectable_when_not_current():
    """When current raw is a normal user-selectable value, the
    non-user-selectable label is NOT injected into options."""
    sel = _make_select(_coord(current_raw=1))
    assert "-- (0)" not in sel.options


def test_options_omit_when_field_unread():
    """Pre-first-read (val=None) → options stay at the static base."""
    sel = _make_select(_coord(current_raw=None))
    assert sel.options == sel._attr_options


# ── current_option resolution ────────────────────────────────────────


def test_current_option_returns_non_user_selectable_label():
    sel = _make_select(_coord(current_raw=0))
    assert sel.current_option == "-- (0)"


def test_current_option_for_normal_raw():
    sel = _make_select(_coord(current_raw=25))
    assert sel.current_option == "Left (25)"


# ── async_select_option no-op for non-user-selectable ───────────────


@pytest.mark.asyncio
async def test_select_non_user_selectable_does_not_call_set():
    """Picking the AC-only label in the UI must not call device.set —
    the AC defines that state, the user can't legitimately re-write it."""
    coord = _coord(current_raw=0)
    sel = _make_select(coord)
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("-- (0)")

    coord.device.set.assert_not_called()
    # No-op still triggers a write_ha_state so any optimistic frontend
    # selection snaps back to the actual current_option.
    sel.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_select_user_selectable_calls_set():
    coord = _coord(current_raw=0)
    sel = _make_select(coord)

    await sel.async_select_option("Far Left (1)")

    coord.device.set.assert_awaited_once_with(louver_swing_angle_lr_enum=1)
