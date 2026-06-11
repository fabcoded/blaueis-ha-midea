"""Write-path gate: validate_or_raise runs the offer gate before the value check.

A blocked write now raises ServiceValidationError naming the axis — mode /
capability-mode → field_inactive_in_mode; runtime interlock → field_blocked_by_feature
— instead of silently greying or surfacing a post-send rejection. Uses the real
strong_wind gate block (visible_in_modes [cool,heat,fan_only] + an interlock on
auxiliary_heat_level scoped to heat/auto).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from blaueis.core.codec import load_glossary, walk_fields
from homeassistant.exceptions import ServiceValidationError

# Import the integration package first (its __init__ front-loads the vendored
# `blaueis` lib path) before importing blaueis directly.
from custom_components.blaueis_midea._preflight import validate_or_raise
from custom_components.blaueis_midea._ux_mixin import field_ux_available

GLOSSARY = load_glossary()
FIELDS = walk_fields(GLOSSARY)
COOL, DRY, HEAT = 2, 3, 4


def _coord(mode, *, aux_heat=0, active_constraints=None, cap_values=None):
    reads = {"operating_mode": mode, "auxiliary_heat_level": aux_heat}
    coord = MagicMock()
    coord.connected = True
    coord.device_fresh = True
    coord.hass.config.language = "en"
    coord.device.field_gdef = lambda n: FIELDS.get(n)
    coord.device.read = lambda n: reads.get(n)
    coord.device.active_constraints = lambda n: active_constraints
    coord.device.caps_bitmap = lambda: {}
    coord.device.cap_values = lambda: (cap_values or {})
    coord.device.status = {"fields": {}}
    coord.device.glossary = GLOSSARY
    return coord


def test_blocked_in_wrong_mode_raises_inactive():
    coord = _coord(DRY)  # strong_wind not offered in dry
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "strong_wind", True)
    assert exc.value.translation_key == "field_inactive_in_mode"


def test_blocked_by_interlock_raises_feature():
    coord = _coord(HEAT, aux_heat=1)  # heat + elec-heat engaged → interlock blocks
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "strong_wind", True)
    assert exc.value.translation_key == "field_blocked_by_feature"
    # names the blocking feature
    assert "blocker" in (exc.value.translation_placeholders or {})


def test_offered_passes_no_raise():
    # cool, no elec-heat → strong_wind offered → gate passes (value validator then Ok)
    coord = _coord(COOL, aux_heat=0)
    validate_or_raise(coord, "strong_wind", True)


def test_interlock_inactive_outside_guard_modes():
    # in cool the interlock's mode guard (heat/auto) is inactive, so a set bit
    # on the mode-muxed dependency does NOT block the write.
    coord = _coord(COOL, aux_heat=1)
    validate_or_raise(coord, "strong_wind", True)


def test_field_ux_available_parity_via_shared_verdict():
    # the refactor: availability and the write gate share field_gate_verdict.
    assert field_ux_available(_coord(COOL), "strong_wind") is True
    assert field_ux_available(_coord(DRY), "strong_wind") is False
    assert field_ux_available(_coord(HEAT, aux_heat=1), "strong_wind") is False
