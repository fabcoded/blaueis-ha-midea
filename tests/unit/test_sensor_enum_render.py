"""Unit tests — BlaueisMideaSensor renders glossary `values:` enums as strings.

Covers raw → label translation, the Unknown (N) fallback for codes outside
the enum, and pass-through for sensors without a `values:` block.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.blaueis_midea.sensor import BlaueisMideaSensor


def _make_sensor(gdef: dict, raw_value: int | None) -> BlaueisMideaSensor:
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.device = MagicMock()
    coord.device.field_gdef.return_value = gdef

    def read(field_name):
        if field_name == "power":
            return True  # power on so off_behavior=hide path is skipped
        return raw_value

    coord.device.read.side_effect = read
    return BlaueisMideaSensor(coord, {"field_name": "fixture_field"})


ERROR_CODE_VALUES = {
    "ok":             {"raw": 0,  "description": "OK (0)"},
    "ipm_protection": {"raw": 13, "description": "IPM module protection (13)"},
    "evap_protect":   {"raw": 29, "description": "Evaporator high/low-temperature protection (29)"},
}


def test_known_value_renders_description():
    """Known raw → description string."""
    s = _make_sensor({"feature_available": "readable", "values": ERROR_CODE_VALUES}, raw_value=13)
    assert s.native_value == "IPM module protection (13)"


def test_zero_value_renders_label():
    """raw=0 still goes through the lookup, not bypassed as falsy."""
    s = _make_sensor({"feature_available": "readable", "values": ERROR_CODE_VALUES}, raw_value=0)
    assert s.native_value == "OK (0)"


def test_unknown_value_falls_back_to_string():
    """Raw value not in values: → 'Unknown (N)' string, preserving the raw int."""
    s = _make_sensor({"feature_available": "readable", "values": ERROR_CODE_VALUES}, raw_value=19)
    assert s.native_value == "Unknown (19)"


def test_no_values_block_passes_through():
    """Sensors without a `values:` block return the raw value unchanged."""
    s = _make_sensor({"feature_available": "readable"}, raw_value=243)
    assert s.native_value == 243


def test_label_preferred_over_description():
    """When both `label:` and `description:` exist on a value, label wins."""
    values = {"high": {"raw": 80, "description": "synthetic anchor", "label": "High"}}
    s = _make_sensor({"feature_available": "readable", "values": values}, raw_value=80)
    assert s.native_value == "High"


def test_yaml_key_fallback_when_no_label_or_description():
    """Value entry with only `raw:` → fall back to the YAML key."""
    values = {"some_state": {"raw": 5}}
    s = _make_sensor({"feature_available": "readable", "values": values}, raw_value=5)
    assert s.native_value == "some_state"


def test_none_value_passes_through():
    """When read() returns None (no source data yet), pass through unchanged."""
    s = _make_sensor({"feature_available": "readable", "values": ERROR_CODE_VALUES}, raw_value=None)
    assert s.native_value is None


def test_off_behavior_hide_masks_to_none_even_with_values():
    """off_behavior=hide + power=False → None, regardless of values: block."""
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.device = MagicMock()
    coord.device.field_gdef.return_value = {"feature_available": "readable", "values": ERROR_CODE_VALUES}

    def read(field_name):
        if field_name == "power":
            return False
        return 13

    coord.device.read.side_effect = read
    s = BlaueisMideaSensor(coord, {"field_name": "fixture_field"})
    assert s.native_value is None


def test_off_behavior_available_keeps_lookup_active():
    """off_behavior=available + power=False + raw=29 → still translated."""
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.device = MagicMock()
    coord.device.field_gdef.return_value = {
        "feature_available": "readable",
        "values": ERROR_CODE_VALUES,
        "ha": {"off_behavior": "available"},
    }

    def read(field_name):
        if field_name == "power":
            return False
        return 29

    coord.device.read.side_effect = read
    s = BlaueisMideaSensor(coord, {"field_name": "fixture_field"})
    assert s.native_value == "Evaporator high/low-temperature protection (29)"
