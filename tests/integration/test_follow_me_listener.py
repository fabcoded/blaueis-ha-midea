"""Follow Me source listener and freshness on HA's real state machine.

Covers what the mocked unit suite cannot: that a state write reaches the
manager through ``async_track_state_change_event``, and that HA moves
``last_reported`` (not ``last_updated``) when a sensor re-reports the same
value — the case that made a held reading look stale.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.blaueis_midea.follow_me import BlauiesFollowMeManager

SENSOR = "sensor.room_temp"
ATTRS = {"unit_of_measurement": "°C", "device_class": "temperature"}


def _coordinator() -> MagicMock:
    coord = MagicMock()
    coord.connected = True
    coord.device.set = AsyncMock()
    coord.device.read = MagicMock(return_value=True)
    return coord


async def test_state_change_refreshes_shadow_without_tick(hass: HomeAssistant) -> None:
    hass.states.async_set(SENSOR, "22.0", ATTRS)
    coord = _coordinator()
    manager = BlauiesFollowMeManager(hass, coord)

    await manager.async_start(SENSOR)
    coord.device.set_follow_me_shadow.reset_mock()
    coord.device.set.reset_mock()

    hass.states.async_set(SENSOR, "21.5", ATTRS)
    await hass.async_block_till_done()

    coord.device.set_follow_me_shadow.assert_called_once_with(21.5)
    coord.device.set.assert_not_awaited()

    await manager.async_stop()
    coord.device.set_follow_me_shadow.reset_mock()
    hass.states.async_set(SENSOR, "20.0", ATTRS)
    await hass.async_block_till_done()
    coord.device.set_follow_me_shadow.assert_not_called()
    manager._kill_timer()


async def test_held_value_that_keeps_reporting_is_fresh(hass: HomeAssistant, freezer) -> None:
    """Re-reporting an unchanged value keeps the reading fresh.

    HA leaves last_updated alone on a same-value write and moves only
    last_reported; the staleness check must follow last_reported.
    """
    manager = BlauiesFollowMeManager(hass, _coordinator())
    manager._source_entity_id = SENSOR
    manager._safety_timeout = 300

    hass.states.async_set(SENSOR, "22.0", ATTRS)
    # Copy the timestamps: HA mutates the State object in place on a
    # same-value write.
    first = hass.states.get(SENSOR)
    updated0, reported0 = first.last_updated, first.last_reported
    for _ in range(3):  # 3 x 290 s: last_updated is 870 s old at the end
        freezer.tick(290)
        hass.states.async_set(SENSOR, "22.0", ATTRS)
    held = hass.states.get(SENSOR)

    assert held.last_updated == updated0
    assert (held.last_reported - reported0).total_seconds() == 870
    assert manager._read_source_temp() == 22.0

    freezer.tick(301)  # no further report: now stale
    assert manager._read_source_temp() is None
