"""State machine tests: ENGAGED <-> TEMP-DISABLED, DISENGAGING."""

import pytest

SENSOR = "sensor.room_temp"


@pytest.fixture
def armed_manager(hass, manager):
    """Manager in ENGAGED state — active, shadow armed, sensor OK."""
    manager._active = True
    manager._stopping = False
    manager._temp_disabled = False
    manager._source_entity_id = SENSOR
    manager._guard_temp_min = -15.0
    manager._guard_temp_max = 40.0
    manager._safety_timeout = 300
    hass.set_sensor(SENSOR, 22.0)
    return manager


# ── ENGAGED → TEMP-DISABLED ──


@pytest.mark.asyncio
async def test_sensor_lost_triggers_temp_disable(hass, coordinator, armed_manager):
    """Sensor goes unavailable → shadow cleared, follow_me=False sent."""
    hass.set_sensor(SENSOR, "unavailable", unit=None)
    coordinator.device._fields["follow_me"] = True

    await armed_manager._tick()

    assert armed_manager._temp_disabled is True
    assert coordinator.device._shadow is None
    coordinator.device.set.assert_awaited_with(follow_me=False)


@pytest.mark.asyncio
async def test_guard_trip_triggers_temp_disable(hass, coordinator, armed_manager):
    """Sensor reports >guard_max → temp-disable."""
    hass.set_sensor(SENSOR, 45.0)

    await armed_manager._tick()

    assert armed_manager._temp_disabled is True
    assert coordinator.device._shadow is None


@pytest.mark.asyncio
async def test_temp_disabled_stays_disabled(hass, coordinator, armed_manager):
    """Already temp-disabled, sensor still bad → no duplicate actions."""
    armed_manager._temp_disabled = True
    hass.set_sensor(SENSOR, "unavailable", unit=None)
    coordinator.device.set.reset_mock()

    await armed_manager._tick()

    assert armed_manager._temp_disabled is True
    coordinator.device.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_sensor_triggers_temp_disable(hass, coordinator, armed_manager):
    """Sensor is stale → temp-disable."""
    from datetime import datetime, timedelta, timezone

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=400)
    hass.set_sensor(SENSOR, 22.0, last_updated=stale_time)

    await armed_manager._tick()

    assert armed_manager._temp_disabled is True
    assert coordinator.device._shadow is None


# ── TEMP-DISABLED → ENGAGED (recovery) ──


@pytest.mark.asyncio
async def test_sensor_recovery_rearms(hass, coordinator, armed_manager):
    """Sensor comes back → shadow re-armed, hello sent if AC disagrees."""
    armed_manager._temp_disabled = True
    hass.set_sensor(SENSOR, 22.0)
    coordinator.device._fields["follow_me"] = False

    await armed_manager._tick()

    assert armed_manager._temp_disabled is False
    assert coordinator.device._shadow is not None
    coordinator.device.set.assert_awaited_with(follow_me=True)


@pytest.mark.asyncio
async def test_sensor_recovery_no_hello_if_ac_confirms(hass, coordinator, armed_manager):
    """Sensor recovers, AC already confirms follow_me → no hello needed."""
    armed_manager._temp_disabled = True
    hass.set_sensor(SENSOR, 22.0)
    coordinator.device._fields["follow_me"] = True

    await armed_manager._tick()

    assert armed_manager._temp_disabled is False
    coordinator.device.set.assert_not_awaited()


# ── ENGAGED steady state — hello resend ──


@pytest.mark.asyncio
async def test_ac_disagrees_triggers_hello(hass, coordinator, armed_manager):
    """AC doesn't confirm follow_me → hello resent."""
    coordinator.device._fields["follow_me"] = False

    await armed_manager._tick()

    coordinator.device.set.assert_awaited_with(follow_me=True)


@pytest.mark.asyncio
async def test_ac_agrees_no_hello(hass, coordinator, armed_manager):
    """AC confirms follow_me → no action needed."""
    coordinator.device._fields["follow_me"] = True

    await armed_manager._tick()

    coordinator.device.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_shadow_updated_on_tick(hass, coordinator, armed_manager):
    """Each tick re-arms shadow with current sensor value."""
    hass.set_sensor(SENSOR, 25.0)
    coordinator.device._fields["follow_me"] = True

    await armed_manager._tick()

    assert coordinator.device._shadow == {"celsius": 25.0}


# ── DISENGAGING ──


@pytest.mark.asyncio
async def test_disengaging_ac_confirms_off(coordinator, armed_manager):
    """AC confirms follow_me=false → timer killed, stopping cleared."""
    armed_manager._active = False
    armed_manager._stopping = True
    coordinator.device._fields["follow_me"] = False

    await armed_manager._tick()

    assert armed_manager._stopping is False


@pytest.mark.asyncio
async def test_disengaging_ac_still_on(coordinator, armed_manager):
    """AC still reports follow_me after end → re-send follow_me=False."""
    armed_manager._active = False
    armed_manager._stopping = True
    coordinator.device._fields["follow_me"] = True

    await armed_manager._tick()

    coordinator.device.set.assert_awaited_with(follow_me=False)


# ── Not connected ──


@pytest.mark.asyncio
async def test_tick_skips_when_disconnected(coordinator, armed_manager):
    coordinator._connected = False

    await armed_manager._tick()

    coordinator.device.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_tick_skips_when_not_active(coordinator, manager):
    manager._active = False
    manager._stopping = False

    await manager._tick()

    coordinator.device.set.assert_not_awaited()


# ── Disengaging while disconnected ──


@pytest.mark.asyncio
async def test_disengaging_skips_when_disconnected(coordinator, armed_manager):
    armed_manager._active = False
    armed_manager._stopping = True
    coordinator._connected = False

    await armed_manager._tick()

    assert armed_manager._stopping is True
    coordinator.device.set.assert_not_awaited()
