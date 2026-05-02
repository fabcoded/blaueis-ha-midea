"""Unit tests for BlaueisMideaSensor — default-enabled state.

Two equivalent triggers must set _attr_entity_registry_enabled_default = False:
1. New unified vocabulary: feature_available ending in '-opt'
2. Legacy ha.enabled_default: false (kept for back-compat during migration)

Both paths active simultaneously; either one triggers the disabled-default state.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.blaueis_midea.sensor import BlaueisMideaSensor


def _make_sensor(gdef: dict) -> BlaueisMideaSensor:
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.device = MagicMock()
    coord.device.field_gdef.return_value = gdef
    desc = {"field_name": "fixture_field"}
    return BlaueisMideaSensor(coord, desc)


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
def test_feature_available_drives_registry_disabled(feature_available, expected_disabled):
    """*-opt feature_available values flag the entity disabled-by-default."""
    s = _make_sensor({"feature_available": feature_available})
    actual = getattr(s, "_attr_entity_registry_enabled_default", True)
    if expected_disabled:
        assert actual is False
    else:
        # Default is True; only the disabled case explicitly sets False
        assert actual is not False


def test_legacy_ha_enabled_default_false_still_works():
    """ha.enabled_default: false legacy path remains active during migration."""
    s = _make_sensor({
        "feature_available": "readable",
        "ha": {"enabled_default": False},
    })
    assert s._attr_entity_registry_enabled_default is False


def test_new_and_legacy_both_set():
    """Setting both triggers is idempotent — disabled-by-default."""
    s = _make_sensor({
        "feature_available": "readable-opt",
        "ha": {"enabled_default": False},
    })
    assert s._attr_entity_registry_enabled_default is False


def test_neither_trigger_set_means_default_enabled():
    """No '-opt' suffix and no ha.enabled_default: false → entity enabled by default."""
    s = _make_sensor({"feature_available": "readable"})
    actual = getattr(s, "_attr_entity_registry_enabled_default", True)
    assert actual is not False
