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

from .const import (
    CLIMATE_CALLBACK_FIELDS,
    CLIMATE_EXCLUSIVE_FIELDS,
    DOMAIN,
    FIELD_CLASS_MAP,
)

_LOGGER = logging.getLogger(__name__)


class BlaueisMideaCoordinator:
    """Manages one Device instance and notifies HA entities of changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        psk: str,
        debug_ring=None,
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self._psk = psk
        self.debug_ring = debug_ring

        self.device = Device(host, port, psk=psk)
        self._entity_callbacks: dict[str, set] = {}  # field_name → {callback, ...}
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def device_name(self) -> str:
        """AC device name from gateway config."""
        return self.device.gateway_info.get("device_name", "Midea AC")

    @property
    def device_info(self) -> DeviceInfo:
        """Device info for the AC unit (all AC entities link here)."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}:{self.port}_ac")},
            name=self.device_name,
            manufacturer="Midea",
            model="HVAC",
            sw_version=self.device.gateway_info.get("version", "unknown"),
        )

    @property
    def gateway_device_info(self) -> DeviceInfo:
        """Device info for the gateway Pi (separate device, readonly sensors)."""
        instance = self.device.gateway_info.get("instance", "")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}:{self.port}_gw")},
            name=f"Blaueis Gateway ({instance or self.host})",
            manufacturer="Blaueis",
            model="Pi Gateway",
            sw_version=self.device.gateway_info.get("version", "unknown"),
            configuration_url=f"http://{self.host}:{self.port}",
        )

    async def async_start(self) -> None:
        """Start the Device and wire up callbacks."""
        self.device.on_state_change = self._on_device_state_change
        self.device.on_connected = self._on_connected
        self.device.on_disconnected = self._on_disconnected
        self.device.on_gateway_stats = self._on_gateway_stats
        await self.device.start()
        self._connected = True

        _LOGGER.info(
            "Blaueis coordinator started: %d available fields, queries=%s",
            len(self.device.available_fields),
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
        # Notify standalone entity callbacks (switch, sensor, etc.)
        cbs = self._entity_callbacks.get(field_name, set())
        for cb in cbs:
            try:
                cb()
            except Exception:
                _LOGGER.exception("Entity callback error for %s", field_name)

        # Climate entity needs to know about changes to its sub-fields
        if field_name in CLIMATE_CALLBACK_FIELDS:
            for cb in self._entity_callbacks.get("_climate", set()):
                try:
                    cb()
                except Exception:
                    _LOGGER.exception("Climate callback error for %s", field_name)

    def _on_gateway_stats(self, stats: dict) -> None:
        """Called by Device when pi_status arrives."""
        for cb in self._entity_callbacks.get("_gateway", set()):
            try:
                cb()
            except Exception:
                _LOGGER.exception("Gateway sensor callback error")

    def _on_connected(self) -> None:
        self._connected = True
        _LOGGER.info("Gateway connected: %s:%d", self.host, self.port)

    def _on_disconnected(self) -> None:
        self._connected = False
        _LOGGER.warning("Gateway disconnected: %s:%d", self.host, self.port)

    # ── Entity discovery ────────────────────────────────────

    def get_entities_for_platform(self, platform: str) -> list[dict]:
        """Return list of entity descriptors for a given HA platform.

        Filters out CLIMATE_EXCLUSIVE_FIELDS (handled by climate.py)
        and maps field_class → platform via FIELD_CLASS_MAP.
        """
        result = []
        for fname, fmeta in self.device.available_fields.items():
            if fname in CLIMATE_EXCLUSIVE_FIELDS:
                continue
            # power is handled by climate on/off — no standalone switch
            if fname == "power":
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
