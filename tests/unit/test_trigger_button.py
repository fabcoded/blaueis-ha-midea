"""Glossary ``trigger`` fields map to one-tap Buttons, capability-gated.

``filter_clean_reset`` is a ``trigger`` gated on FILTER_REMIND (0x0217).
On a unit that does not advertise the cap it never enters
``available_fields``, so no button is built — that gating is the whole
point of exposing the reset without it appearing on hardware where the
filter feature is dormant.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.blaueis_midea.const import FIELD_CLASS_MAP
from custom_components.blaueis_midea.coordinator import BlaueisMideaCoordinator


def _coord_with_available(fields: dict) -> MagicMock:
    coord = MagicMock()
    coord.device.available_fields = fields
    return coord


def test_field_class_map_routes_trigger_to_button():
    writable, readonly = FIELD_CLASS_MAP["trigger"]
    assert writable == "button"
    assert readonly is None


def test_writable_trigger_yields_a_button():
    coord = _coord_with_available(
        {
            "filter_clean_reset": {
                "field_class": "trigger",
                "writable": True,
                "feature_available": "always",
            }
        }
    )
    descs = BlaueisMideaCoordinator.get_entities_for_platform(coord, "button")
    assert [d["field_name"] for d in descs] == ["filter_clean_reset"]


def test_capability_gated_trigger_yields_zero_buttons():
    # cap 0x0217 not advertised → field never promoted into available_fields
    coord = _coord_with_available({})
    descs = BlaueisMideaCoordinator.get_entities_for_platform(coord, "button")
    assert descs == []


def test_trigger_does_not_leak_into_other_platforms():
    coord = _coord_with_available(
        {
            "filter_clean_reset": {
                "field_class": "trigger",
                "writable": True,
                "feature_available": "always",
            }
        }
    )
    for platform in ("switch", "binary_sensor", "sensor", "number", "select"):
        descs = BlaueisMideaCoordinator.get_entities_for_platform(coord, platform)
        assert "filter_clean_reset" not in [d["field_name"] for d in descs], platform
