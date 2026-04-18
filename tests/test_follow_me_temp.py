"""Temperature reading, conversion, guard, and clamping tests."""

from datetime import datetime, timedelta, timezone

import pytest

SENSOR = "sensor.room_temp"


@pytest.fixture(autouse=True)
def configure_manager(manager):
    manager._source_entity_id = SENSOR
    manager._guard_temp_min = -15.0
    manager._guard_temp_max = 40.0
    manager._safety_timeout = 300


# ── Normal readings ──


def test_celsius_passthrough(hass, manager):
    hass.set_sensor(SENSOR, 22.0)
    assert manager._read_source_temp() == 22.0


def test_fahrenheit_conversion(hass, manager):
    hass.set_sensor(SENSOR, 72.0, unit="°F")
    result = manager._read_source_temp()
    assert result == pytest.approx(22.22, abs=0.1)


# ── Guard boundaries ──


def test_guard_min_just_inside(hass, manager):
    """−14.9°C is inside guard_min (−15), clamped to 0 for protocol."""
    hass.set_sensor(SENSOR, -14.9)
    result = manager._read_source_temp()
    assert result == 0.0


def test_guard_min_just_outside(hass, manager):
    """−15.1°C is below guard_min (−15) → rejected."""
    hass.set_sensor(SENSOR, -15.1)
    assert manager._read_source_temp() is None


def test_guard_min_exact_boundary(hass, manager):
    """−15.0°C is exactly at guard_min — should pass (clamped to 0)."""
    hass.set_sensor(SENSOR, -15.0)
    result = manager._read_source_temp()
    assert result == 0.0


def test_guard_max_just_inside(hass, manager):
    hass.set_sensor(SENSOR, 39.9)
    assert manager._read_source_temp() == 39.9


def test_guard_max_just_outside(hass, manager):
    hass.set_sensor(SENSOR, 40.1)
    assert manager._read_source_temp() is None


def test_guard_max_exact_boundary(hass, manager):
    """40.0°C is exactly at guard_max — should pass."""
    hass.set_sensor(SENSOR, 40.0)
    assert manager._read_source_temp() == 40.0


def test_guard_max_boundary_fahrenheit(hass, manager):
    """104°F = 40°C exactly — at boundary, should pass."""
    hass.set_sensor(SENSOR, 104.0, unit="°F")
    result = manager._read_source_temp()
    assert result == pytest.approx(40.0, abs=0.01)


def test_guard_max_over_fahrenheit(hass, manager):
    """105°F = 40.6°C — above guard_max → rejected."""
    hass.set_sensor(SENSOR, 105.0, unit="°F")
    assert manager._read_source_temp() is None


# ── Protocol clamping ──


def test_negative_clamped_to_zero(hass, manager):
    """−10°C inside guards but below protocol min → clamped to 0."""
    hass.set_sensor(SENSOR, -10.0)
    assert manager._read_source_temp() == 0.0


def test_above_50_clamped(hass, manager):
    """Guard max raised to 55 — 52°C inside guards, clamped to 50 for protocol."""
    manager._guard_temp_max = 55.0
    hass.set_sensor(SENSOR, 52.0)
    assert manager._read_source_temp() == 50.0


# ── Invalid / missing ──


def test_nan_rejected(hass, manager):
    hass.set_sensor(SENSOR, float("nan"))
    assert manager._read_source_temp() is None


def test_inf_rejected(hass, manager):
    hass.set_sensor(SENSOR, float("inf"))
    assert manager._read_source_temp() is None


def test_negative_inf_rejected(hass, manager):
    hass.set_sensor(SENSOR, float("-inf"))
    assert manager._read_source_temp() is None


def test_unavailable_rejected(hass, manager):
    hass.set_sensor(SENSOR, "unavailable", unit=None)
    assert manager._read_source_temp() is None


def test_unknown_rejected(hass, manager):
    hass.set_sensor(SENSOR, "unknown", unit=None)
    assert manager._read_source_temp() is None


def test_none_string_rejected(hass, manager):
    hass.set_sensor(SENSOR, "None", unit=None)
    assert manager._read_source_temp() is None


def test_non_numeric_rejected(hass, manager):
    hass.set_sensor(SENSOR, "hello")
    assert manager._read_source_temp() is None


def test_no_source_entity(manager):
    manager._source_entity_id = None
    assert manager._read_source_temp() is None


def test_entity_not_in_hass(hass, manager):
    assert manager._read_source_temp() is None


# ── Safety: misconfigured unit ──


def test_misconfigured_fahrenheit_as_celsius(hass, manager):
    """Sensor reports 72 with unit °C (actually °F) → 72°C > guard_max → caught."""
    hass.set_sensor(SENSOR, 72.0, unit="°C")
    assert manager._read_source_temp() is None


# ── Staleness timeout ──


def test_stale_sensor_rejected(hass, manager):
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=400)
    hass.set_sensor(SENSOR, 22.0, last_updated=stale_time)
    assert manager._read_source_temp() is None


def test_fresh_sensor_accepted(hass, manager):
    fresh_time = datetime.now(timezone.utc) - timedelta(seconds=100)
    hass.set_sensor(SENSOR, 22.0, last_updated=fresh_time)
    assert manager._read_source_temp() == 22.0


def test_just_under_timeout_accepted(hass, manager):
    """Sensor age just under timeout — still accepted."""
    edge_time = datetime.now(timezone.utc) - timedelta(seconds=299)
    hass.set_sensor(SENSOR, 22.0, last_updated=edge_time)
    assert manager._read_source_temp() == 22.0


def test_custom_timeout(hass, manager):
    """Custom timeout of 60s — 90s old sensor should be rejected."""
    manager._safety_timeout = 60
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=90)
    hass.set_sensor(SENSOR, 22.0, last_updated=stale_time)
    assert manager._read_source_temp() is None


# ── Guard reconfiguration ──


def test_configure_guards_from_options(manager):
    from custom_components.blaueis_midea.const import (
        CONF_FMF_GUARD_TEMP_MAX,
        CONF_FMF_GUARD_TEMP_MIN,
        CONF_FMF_SAFETY_TIMEOUT,
    )

    manager.configure_guards(
        {
            CONF_FMF_GUARD_TEMP_MIN: -20.0,
            CONF_FMF_GUARD_TEMP_MAX: 45.0,
            CONF_FMF_SAFETY_TIMEOUT: 600,
        }
    )
    assert manager._guard_temp_min == -20.0
    assert manager._guard_temp_max == 45.0
    assert manager._safety_timeout == 600


def test_configure_guards_defaults(manager):
    manager.configure_guards({})
    assert manager._guard_temp_min == -15.0
    assert manager._guard_temp_max == 40.0
    assert manager._safety_timeout == 300
