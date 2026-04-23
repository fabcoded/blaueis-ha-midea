"""Button platform — one-tap trigger for ``run_field_inventory``.

Sits on the AC device in Home Assistant. Tap → calls the service with
a synthetic ``label="manual-<ISO timestamp>"`` and no compare. The
service handler does the actual scan asynchronously; the button just
fires-and-forgets.

Only one button today. Add more as other push-to-scan / push-to-action
features appear.
"""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from .const import DOMAIN
from .coordinator import BlaueisMideaCoordinator
from .field_inventory import SERVICE_RUN_FIELD_INVENTORY


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    async_add_entities([RunFieldInventoryButton(coordinator)])


class RunFieldInventoryButton(ButtonEntity):
    """Trigger a full field-inventory scan and prepare a download."""

    _attr_has_entity_name = True
    _attr_name = "Run field inventory scan"
    _attr_icon = "mdi:clipboard-list-outline"
    _attr_entity_category = None  # lives on the main device card, not diagnostic
    should_poll = False

    def __init__(self, coordinator: BlaueisMideaCoordinator) -> None:
        self._coord = coordinator
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_run_field_inventory"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    @property
    def available(self) -> bool:
        return self._coord.connected

    async def async_press(self) -> None:
        """Fire the field-inventory service. Returns immediately; the
        scan runs as a background task in the service handler."""
        label = f"manual-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_RUN_FIELD_INVENTORY,
            {"label": label},
            blocking=False,
        )
