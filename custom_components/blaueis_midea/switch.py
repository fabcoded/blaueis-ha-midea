"""Switch entities — auto-mapped from glossary stateful_bool (writable)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from .coordinator import BlaueisMideaCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    entities = []
    for desc in coordinator.get_entities_for_platform("switch"):
        entities.append(BlaueisMideaSwitch(coordinator, desc))
    if entities:
        async_add_entities(entities)


class BlaueisMideaSwitch(SwitchEntity):
    """Generic switch backed by a glossary bool field."""

    _attr_has_entity_name = True
    should_poll = False

    def __init__(self, coordinator: BlaueisMideaCoordinator, desc: dict) -> None:
        self._coord = coordinator
        self._field_name = desc["field_name"]
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_{self._field_name}"
        )
        self._attr_name = self._field_name.replace("_", " ").title()

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
        if not self._coord.connected:
            return False
        # Switches are unavailable when AC is off (can't toggle features)
        power = self._coord.device.read("power")
        return bool(power)

    @property
    def is_on(self) -> bool | None:
        return self._coord.device.read(self._field_name)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._coord.device.set(**{self._field_name: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coord.device.set(**{self._field_name: False})
