"""Sensor entities — auto-mapped from glossary stateful_numeric/enum (read-only)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from .const import DOMAIN
from .coordinator import BlaueisMideaCoordinator

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
        self._attr_name = self._field_name.replace("_", " ").title()

        # Device class and unit from mapping
        dc_info = SENSOR_DEVICE_CLASS.get(self._field_name)
        if dc_info:
            self._attr_device_class = dc_info[0]
            self._attr_native_unit_of_measurement = dc_info[1]

    async def async_added_to_hass(self) -> None:
        self._coord.register_entity_callback(
            self._field_name, self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        self._coord.unregister_entity_callback(
            self._field_name, self.async_write_ha_state
        )

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    @property
    def available(self) -> bool:
        return self._coord.connected

    @property
    def native_value(self):
        return self._coord.device.read(self._field_name)
