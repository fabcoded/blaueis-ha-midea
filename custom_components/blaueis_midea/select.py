"""Select entities — auto-mapped from glossary stateful_enum (writable)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
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
    for desc in coordinator.get_entities_for_platform("select"):
        entities.append(BlaueisMideaSelect(coordinator, desc))
    if entities:
        async_add_entities(entities)


class BlaueisMideaSelect(SelectEntity):
    """Generic select backed by a glossary enum field."""

    _attr_has_entity_name = True
    should_poll = False

    def __init__(self, coordinator: BlaueisMideaCoordinator, desc: dict) -> None:
        self._coord = coordinator
        self._field_name = desc["field_name"]
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_{self._field_name}"
        )
        self._attr_name = self._field_name.replace("_", " ").title()

        # Build options from active constraints if available
        constraints = desc.get("active_constraints") or {}
        valid_set = constraints.get("valid_set")
        if valid_set:
            self._attr_options = [str(v) for v in valid_set]
        else:
            self._attr_options = []

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
        power = self._coord.device.read("power")
        return bool(power)

    @property
    def current_option(self) -> str | None:
        val = self._coord.device.read(self._field_name)
        return str(val) if val is not None else None

    async def async_select_option(self, option: str) -> None:
        # Try to convert back to int if the original was numeric
        try:
            value = int(option)
        except ValueError:
            value = option
        await self._coord.device.set(**{self._field_name: value})
