"""Binary sensor entities — auto-mapped from glossary stateful_bool (read-only)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from ._ux_mixin import field_ux_available
from .coordinator import BlaueisMideaCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    entities = []
    for desc in coordinator.get_entities_for_platform("binary_sensor"):
        entities.append(BlaueisMideaBinarySensor(coordinator, desc))
    if entities:
        async_add_entities(entities)


class BlaueisMideaBinarySensor(BinarySensorEntity):
    """Generic binary sensor backed by a glossary bool field."""

    _attr_has_entity_name = True
    should_poll = False

    def __init__(self, coordinator: BlaueisMideaCoordinator, desc: dict) -> None:
        self._coord = coordinator
        self._field_name = desc["field_name"]
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_{self._field_name}"
        )

        gdef = coordinator.device.field_gdef(self._field_name) or {}
        ha_meta = gdef.get("ha") or {}
        # Label from glossary (preferred) or mechanical title-case fallback.
        self._attr_name = (
            gdef.get("label") or self._field_name.replace("_", " ").title()
        )
        if "device_class" in ha_meta:
            from homeassistant.components.binary_sensor import BinarySensorDeviceClass
            self._attr_device_class = BinarySensorDeviceClass(ha_meta["device_class"])
        if "entity_category" in ha_meta:
            from homeassistant.helpers.entity import EntityCategory
            self._attr_entity_category = EntityCategory(ha_meta["entity_category"])
        if gdef.get("feature_available", "").endswith("-opt"):
            self._attr_entity_registry_enabled_default = False

        off_behavior = ha_meta.get("off_behavior", "hide")
        if off_behavior not in ("hide", "available"):
            off_behavior = "hide"
        self._off_behavior = off_behavior

    async def async_added_to_hass(self) -> None:
        self._coord.register_entity_callback(
            self._field_name, self.async_write_ha_state
        )
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
        if not field_ux_available(self._coord, self._field_name):
            return False
        if self._off_behavior == "available":
            return True
        power = self._coord.device.read("power")
        return bool(power)

    @property
    def is_on(self) -> bool | None:
        return self._coord.device.read(self._field_name)
