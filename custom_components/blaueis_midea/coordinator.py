"""Coordinator for Blaueis Midea AC integration.

Wraps the Device class, translates state changes to HA entity updates,
and manages the entity registry based on B5-confirmed capabilities.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo

from blaueis.client.device import Device

from .const import CLIMATE_FIELDS, DOMAIN, FIELD_CLASS_MAP

_LOGGER = logging.getLogger(__name__)


class BlaueisMideaCoordinator:
    """Manages one Device instance and notifies HA entities of changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        psk: str,
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self._psk = psk

        self.device = Device(host, port, psk=psk)
        self._entity_callbacks: dict[str, set] = {}  # field_name → {callback, ...}
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def device_info(self) -> DeviceInfo:
        """Device info shared by all entities of this gateway."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}:{self.port}")},
            name=f"Blaueis AC ({self.host})",
            manufacturer="Midea",
            model="HVAC",
            sw_version=self.device.read("gateway_version") or "unknown",
            configuration_url=f"ws://{self.host}:{self.port}",
        )

    async def async_start(self) -> None:
        """Start the Device and wire up callbacks."""
        self.device.on_state_change = self._on_device_state_change
        self.device.on_connected = self._on_connected
        self.device.on_disconnected = self._on_disconnected
        await self.device.start()
        self._connected = True

        # Register all available non-climate fields for polling
        avail = self.device.available_fields
        all_field_names = set(avail.keys())
        self.device.register_fields(all_field_names)

        _LOGGER.info(
            "Blaueis coordinator started: %d available fields, queries=%s",
            len(all_field_names),
            self.device.required_queries,
        )

    async def async_stop(self) -> None:
        """Stop the Device."""
        await self.device.stop()
        self._connected = False

    # ── Entity callback registration ────────────────────────

    def register_entity_callback(
        self, field_name: str, callback_fn
    ) -> None:
        """Register an entity's update callback for a field."""
        self._entity_callbacks.setdefault(field_name, set()).add(callback_fn)

    def unregister_entity_callback(
        self, field_name: str, callback_fn
    ) -> None:
        """Unregister an entity's update callback."""
        cbs = self._entity_callbacks.get(field_name)
        if cbs:
            cbs.discard(callback_fn)

    # ── Device callbacks ────────────────────────────────────

    def _on_device_state_change(
        self, field_name: str, new_value: Any, old_value: Any
    ) -> None:
        """Called by Device when a field value changes."""
        cbs = self._entity_callbacks.get(field_name, set())
        for cb in cbs:
            try:
                cb()
            except Exception:
                _LOGGER.exception("Entity callback error for %s", field_name)

        # Climate entity needs to know about changes to its sub-fields
        if field_name in CLIMATE_FIELDS:
            for cb in self._entity_callbacks.get("_climate", set()):
                try:
                    cb()
                except Exception:
                    _LOGGER.exception("Climate callback error for %s", field_name)

    def _on_connected(self) -> None:
        self._connected = True
        _LOGGER.info("Gateway connected: %s:%d", self.host, self.port)

    def _on_disconnected(self) -> None:
        self._connected = False
        _LOGGER.warning("Gateway disconnected: %s:%d", self.host, self.port)

    # ── Entity discovery ────────────────────────────────────

    def get_entities_for_platform(self, platform: str) -> list[dict]:
        """Return list of entity descriptors for a given HA platform.

        Each descriptor: {field_name, field_class, data_type, writable, ...}

        Filters out CLIMATE_FIELDS (handled by climate.py directly) and
        maps field_class → platform via FIELD_CLASS_MAP.
        """
        result = []
        for fname, fmeta in self.device.available_fields.items():
            if fname in CLIMATE_FIELDS:
                continue

            field_class = fmeta.get("field_class", "")
            writable = fmeta.get("writable", False)
            mapping = FIELD_CLASS_MAP.get(field_class)
            if not mapping:
                continue

            target_platform = mapping[0] if writable else mapping[1]
            if target_platform == platform:
                result.append({"field_name": fname, **fmeta})

        return result
