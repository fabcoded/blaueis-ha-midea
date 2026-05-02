"""Unit tests — registry-disabled-default behavior across all 4 entity platforms.

Two equivalent triggers must set ``_attr_entity_registry_enabled_default = False``:
1. New unified vocabulary: ``feature_available`` ending in ``-opt``
2. Legacy ``ha.enabled_default: false`` (kept for back-compat during migration)

Both paths active simultaneously; either one triggers the disabled-default
state. Parity is verified for sensor / binary_sensor / select / switch.
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
        ("never", False),
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


@pytest.mark.parametrize("platform", list(PLATFORM_FACTORIES.keys()))
def test_legacy_ha_enabled_default_false_still_works(platform):
    """ha.enabled_default: false legacy path remains active during migration —
    on every platform."""
    factory = PLATFORM_FACTORIES[platform]
    e = factory({
        "feature_available": "readable",
        "ha": {"enabled_default": False},
    })
    assert e._attr_entity_registry_enabled_default is False


@pytest.mark.parametrize("platform", list(PLATFORM_FACTORIES.keys()))
def test_new_and_legacy_both_set(platform):
    """Setting both triggers is idempotent — disabled-by-default."""
    factory = PLATFORM_FACTORIES[platform]
    e = factory({
        "feature_available": "readable-opt",
        "ha": {"enabled_default": False},
    })
    assert e._attr_entity_registry_enabled_default is False


@pytest.mark.parametrize("platform", list(PLATFORM_FACTORIES.keys()))
def test_neither_trigger_set_means_default_enabled(platform):
    """No '-opt' suffix and no ha.enabled_default: false → entity enabled by default."""
    factory = PLATFORM_FACTORIES[platform]
    e = factory({"feature_available": "readable"})
    actual = getattr(e, "_attr_entity_registry_enabled_default", True)
    assert actual is not False
