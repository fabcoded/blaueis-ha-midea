"""Unit tests — registry-disabled-default behavior across all 4 entity platforms.

A field's ``feature_available`` ending in ``-opt`` flips
``_attr_entity_registry_enabled_default`` to False. Verified for sensor /
binary_sensor / select / switch — every glossary-auto-mapped platform.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.blaueis_midea.binary_sensor import BlaueisMideaBinarySensor
from custom_components.blaueis_midea.select import BlaueisMideaSelect
from custom_components.blaueis_midea.sensor import BlaueisMideaSensor
from custom_components.blaueis_midea.switch import BlaueisMideaSwitch


def _coord(gdef: dict) -> MagicMock:
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.device = MagicMock()
    coord.device.field_gdef.return_value = gdef
    return coord


def _make_sensor(gdef: dict) -> BlaueisMideaSensor:
    return BlaueisMideaSensor(_coord(gdef), {"field_name": "fixture_field"})


def _make_binary_sensor(gdef: dict) -> BlaueisMideaBinarySensor:
    return BlaueisMideaBinarySensor(_coord(gdef), {"field_name": "fixture_field"})


def _make_select(gdef: dict) -> BlaueisMideaSelect:
    return BlaueisMideaSelect(_coord(gdef), {"field_name": "fixture_field"})


def _make_switch(gdef: dict) -> BlaueisMideaSwitch:
    entry = MagicMock()
    return BlaueisMideaSwitch(_coord(gdef), entry, {"field_name": "fixture_field"})


PLATFORM_FACTORIES = {
    "sensor": _make_sensor,
    "binary_sensor": _make_binary_sensor,
    "select": _make_select,
    "switch": _make_switch,
}


@pytest.mark.parametrize("platform", list(PLATFORM_FACTORIES.keys()))
@pytest.mark.parametrize(
    "feature_available,expected_disabled",
    [
        ("readable", False),
        ("readable-opt", True),
        ("capability", False),
        ("capability-opt", True),
        ("always", False),
        ("excluded", False),
    ],
)
def test_feature_available_drives_registry_disabled(platform, feature_available, expected_disabled):
    """*-opt feature_available values flag the entity disabled-by-default,
    on every platform that auto-maps from the glossary."""
    factory = PLATFORM_FACTORIES[platform]
    e = factory({"feature_available": feature_available})
    actual = getattr(e, "_attr_entity_registry_enabled_default", True)
    if expected_disabled:
        assert actual is False
    else:
        # Default is True; only the disabled case explicitly sets False
        assert actual is not False
