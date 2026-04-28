"""Switch entities — auto-mapped from glossary stateful_bool (writable),
plus the synthetic Follow Me Function switch."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from ._set_result import check_set_result
from ._ux_mixin import field_ux_available
from .const import (
    CONF_FMF_CONFIGURED,
    CONF_FMF_ENABLED,
    CONF_FMF_SENSOR,
)
from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    for desc in coordinator.get_entities_for_platform("switch"):
        entities.append(BlaueisMideaSwitch(coordinator, entry, desc))

    entities.append(BlauiesFollowMeSwitch(coordinator, entry))

    async_add_entities(entities)


class BlaueisMideaSwitch(SwitchEntity):
    """Generic switch backed by a glossary bool field."""

    _attr_has_entity_name = True
    should_poll = False

    def __init__(
        self,
        coordinator: BlaueisMideaCoordinator,
        entry: BlaueisMideaConfigEntry,
        desc: dict,
    ) -> None:
        self._coord = coordinator
        self._entry = entry
        self._field_name = desc["field_name"]
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_{self._field_name}"
        )
        self._attr_name = self._field_name.replace("_", " ").title()

        gdef = coordinator.device.field_gdef(self._field_name) or {}
        ha_meta = gdef.get("ha") or {}
        if ha_meta.get("enabled_default") is False:
            self._attr_entity_registry_enabled_default = False

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
        power = self._coord.device.read("power")
        return bool(power)

    @property
    def is_on(self) -> bool | None:
        return self._coord.device.read(self._field_name)

    async def async_turn_on(self, **kwargs: Any) -> None:
        result = await self._coord.device.set(**{self._field_name: True})
        check_set_result(result, primary_fields={self._field_name})

    async def async_turn_off(self, **kwargs: Any) -> None:
        result = await self._coord.device.set(**{self._field_name: False})
        check_set_result(result, primary_fields={self._field_name})


class BlauiesFollowMeSwitch(SwitchEntity):
    """Engage/disengage switch for the Follow Me Function.

    Always registered (so the entity_id stays stable across master-flag
    flips). Visibility on the device card is controlled separately via
    ``entity_registry.hidden_by`` — see ``_sync_fm_switch_visibility``
    in ``__init__.py`` — which the integration sets/clears whenever the
    Configured master flag changes.

    The switch's ``is_on`` reads ``CONF_FMF_ENABLED`` from the config
    entry options, and toggling writes the same option. That option is
    also the second checkbox in the Configure menu, so the device-card
    switch and the menu's "Enabled" toggle are the same persistent
    flag — change either, the other reflects it.
    """

    _attr_has_entity_name = True
    _attr_name = "Follow Me Function"
    should_poll = False

    def __init__(
        self,
        coordinator: BlaueisMideaCoordinator,
        entry: BlaueisMideaConfigEntry,
    ) -> None:
        self._coord = coordinator
        self._entry = entry
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_blaueis_follow_me"
        )

    async def async_added_to_hass(self) -> None:
        self._coord.register_entity_callback(
            "follow_me", self.async_write_ha_state
        )
        self._coord.register_entity_callback(
            "power", self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        fm = self._coord.blaueis_follow_me
        if fm.active or fm._stopping:
            await fm.async_stop()
        self._coord.unregister_entity_callback(
            "follow_me", self.async_write_ha_state
        )
        self._coord.unregister_entity_callback(
            "power", self.async_write_ha_state
        )

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    @property
    def available(self) -> bool:
        # Configured gates *visibility* (via hidden_by); availability
        # gates whether the user can actually toggle. Belt-and-braces:
        # if for any reason the entity were exposed while Configured is
        # off, refuse to act anyway.
        if not self._entry.options.get(CONF_FMF_CONFIGURED, False):
            return False
        if not self._coord.connected:
            return False
        if not self._coord.device.read("power"):
            return False
        if not self._entry.options.get(CONF_FMF_SENSOR):
            return False
        return True

    @property
    def is_on(self) -> bool:
        return bool(self._entry.options.get(CONF_FMF_ENABLED, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        source = self._entry.options.get(CONF_FMF_SENSOR)
        if not source:
            _LOGGER.warning(
                "Cannot start Follow Me Function: no source sensor configured"
            )
            return
        await self._coord.blaueis_follow_me.async_start(source)
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_FMF_ENABLED: True},
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coord.blaueis_follow_me.async_stop()
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_FMF_ENABLED: False},
        )
        self.async_write_ha_state()
