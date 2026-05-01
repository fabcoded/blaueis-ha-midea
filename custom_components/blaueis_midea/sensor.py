"""Sensor entities — auto-mapped from glossary stateful_numeric/enum (read-only)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from ._ux_mixin import field_ux_available
from .coordinator import BlaueisMideaCoordinator

# Per-field power-off read policy, resolved from the glossary's ha.off_behavior
# key. "hide" (the default) masks the value to None when power=off, matching
# the legacy hardcoded whitelist. "available" returns the device's reported
# value regardless of power state — for fields that remain meaningful or
# carry latched values while the unit is in standby (thermistors, error
# codes, cumulative counters, instantaneous power).
OFF_BEHAVIORS = frozenset({"hide", "available"})

# Map glossary field names to HA sensor device classes and units
SENSOR_DEVICE_CLASS = {
    "indoor_temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "outdoor_temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "t1_indoor_coil": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "t2_indoor_temp": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "t3_outdoor_coil_temp": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "t4_outdoor_ambient_temp": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "discharge_pipe_temp": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "humidity_actual": (SensorDeviceClass.HUMIDITY, "%"),
    "humidity_measured": (SensorDeviceClass.HUMIDITY, "%"),
    "compressor_frequency": (SensorDeviceClass.FREQUENCY, "Hz"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    entities = []
    for desc in coordinator.get_entities_for_platform("sensor"):
        entities.append(BlaueisMideaSensor(coordinator, desc))

    # Gateway sensors (Pi stats). System-level (uptime, disk_used) and
    # process-level (process_uptime, process_started_at) live side-by-side
    # so a user can tell a Pi reboot apart from a gateway-service restart:
    #   - uptime_s            jumps back to ~0 only on Pi reboot
    #   - process_uptime_s    jumps back to 0 on every gateway restart
    #   - process_started_at  jumps forward (TIMESTAMP) on every restart
    entities.append(GatewaySensor(coordinator, "cpu_percent", "CPU", SensorDeviceClass.POWER_FACTOR, "%"))
    entities.append(GatewaySensor(coordinator, "ram_used_mb", "RAM Used", None, "MB"))
    entities.append(GatewaySensor(coordinator, "temp_c", "Temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS))
    entities.append(GatewaySensor(coordinator, "disk_used_mb", "Disk Used", None, "MB"))
    entities.append(GatewaySensor(coordinator, "disk_free_mb", "Disk Free", None, "MB"))
    entities.append(GatewaySensor(coordinator, "uptime_s", "Uptime", SensorDeviceClass.DURATION, "s"))
    entities.append(GatewaySensor(coordinator, "process_uptime_s", "Process Uptime", SensorDeviceClass.DURATION, "s"))
    entities.append(
        GatewaySensor(
            coordinator,
            "process_started_at",
            "Process Started",
            SensorDeviceClass.TIMESTAMP,
            None,
            value_transform=_epoch_to_datetime,
        )
    )

    if entities:
        async_add_entities(entities)


class BlaueisMideaSensor(SensorEntity):
    """Generic sensor backed by a glossary field."""

    _attr_has_entity_name = True
    should_poll = False

    def __init__(self, coordinator: BlaueisMideaCoordinator, desc: dict) -> None:
        self._coord = coordinator
        self._field_name = desc["field_name"]
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_{self._field_name}"
        )

        # HA entity metadata (device_class, state_class, unit, precision,
        # display label) comes from the glossary's per-field `ha:` block
        # and top-level `label:` when present — declarative path. Label
        # falls back to mechanical title-case of the field name; other
        # attributes fall back to the hardcoded SENSOR_DEVICE_CLASS map
        # for fields not yet migrated. Both maps will shrink to empty
        # as glossary entries gain their declarative metadata.
        gdef = coordinator.device.field_gdef(self._field_name) or {}
        ha_meta = gdef.get("ha") or {}
        self._attr_name = (
            gdef.get("label") or self._field_name.replace("_", " ").title()
        )
        if "device_class" in ha_meta:
            self._attr_device_class = ha_meta["device_class"]
        if "state_class" in ha_meta:
            self._attr_state_class = ha_meta["state_class"]
        if "unit_of_measurement" in ha_meta:
            self._attr_native_unit_of_measurement = ha_meta["unit_of_measurement"]
        if "suggested_display_precision" in ha_meta:
            self._attr_suggested_display_precision = ha_meta["suggested_display_precision"]
        if "entity_category" in ha_meta:
            from homeassistant.helpers.entity import EntityCategory
            self._attr_entity_category = EntityCategory(ha_meta["entity_category"])
        if ha_meta.get("enabled_default") is False:
            self._attr_entity_registry_enabled_default = False

        off_behavior = ha_meta.get("off_behavior", "hide")
        if off_behavior not in OFF_BEHAVIORS:
            off_behavior = "hide"
        self._off_behavior = off_behavior

        # Legacy hardcoded fallback — kicks in per-attribute when the glossary's
        # `ha:` block doesn't declare it. Delete once all measurement sensors
        # have their device_class / unit migrated into the glossary.
        dc_info = SENSOR_DEVICE_CLASS.get(self._field_name)
        if dc_info:
            if "device_class" not in ha_meta:
                self._attr_device_class = dc_info[0]
            if "unit_of_measurement" not in ha_meta:
                self._attr_native_unit_of_measurement = dc_info[1]

    async def async_added_to_hass(self) -> None:
        self._coord.register_entity_callback(
            self._field_name, self.async_write_ha_state
        )
        # Refresh `available` whenever the mode changes — UX mask may flip
        # even when our own field's value is unchanged.
        self._coord.register_entity_callback(
            "operating_mode", self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        self._coord.unregister_entity_callback(
            self._field_name, self.async_write_ha_state
        )
        self._coord.unregister_entity_callback(
            "operating_mode", self.async_write_ha_state
        )

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    @property
    def available(self) -> bool:
        return field_ux_available(self._coord, self._field_name)

    @property
    def native_value(self):
        value = self._coord.device.read(self._field_name)
        if self._off_behavior == "hide" and not self._coord.device.read("power"):
            return None
        return value


def _epoch_to_datetime(value: Any) -> datetime | None:
    """Convert a Unix epoch (float | int | None) to a UTC ``datetime``.

    Used as the ``value_transform`` for the ``process_started_at``
    sensor — HA's ``SensorDeviceClass.TIMESTAMP`` requires a ``datetime``,
    not a number, so the gateway's float-epoch needs converting on the
    HA side. Returns ``None`` for missing or invalid values, which HA
    renders as ``unknown``.
    """
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class GatewaySensor(SensorEntity):
    """Sensor for gateway Pi stats (CPU, RAM, temp, etc.).

    ``value_transform`` is an optional ``Callable[[Any], Any]`` applied
    to the raw stat value before HA reads ``native_value``. Used to
    convert the gateway's epoch-float ``process_started_at`` into the
    ``datetime`` that ``SensorDeviceClass.TIMESTAMP`` expects.
    """

    _attr_has_entity_name = True
    should_poll = False

    def __init__(
        self,
        coordinator: BlaueisMideaCoordinator,
        stat_key: str,
        name: str,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        *,
        value_transform: Callable[[Any], Any] | None = None,
    ) -> None:
        self._coord = coordinator
        self._stat_key = stat_key
        self._value_transform = value_transform
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_gw_{stat_key}"
        )
        self._attr_name = name
        if device_class:
            self._attr_device_class = device_class
        if unit:
            self._attr_native_unit_of_measurement = unit

    async def async_added_to_hass(self) -> None:
        self._coord.register_entity_callback("_gateway", self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self._coord.unregister_entity_callback("_gateway", self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.gateway_device_info

    @property
    def available(self) -> bool:
        return self._coord.connected

    @property
    def native_value(self):
        raw = self._coord.device.gateway_stats.get(self._stat_key)
        if self._value_transform is not None:
            return self._value_transform(raw)
        return raw
