"""Coordinator for Blaueis Midea AC integration.

Wraps the Device class, translates state changes to HA entity updates,
and manages the entity registry based on B5-confirmed capabilities.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from blaueis.client.device import Device

from ._ingress_hook import IngressHook
from .const import (
    CLIMATE_CALLBACK_FIELDS,
    CLIMATE_EXCLUSIVE_FIELDS,
    DOMAIN,
    FIELD_CLASS_MAP,
)
from .follow_me import BlauiesFollowMeManager

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
        glossary_overrides: dict | None = None,
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self._psk = psk
        self.debug_ring = debug_ring

        self.device = Device(
            host, port, psk=psk,
            glossary_overrides=glossary_overrides,
        )
        self._entity_callbacks: dict[str, set] = {}  # field_name → {callback, ...}
        # Ingress hooks — subscribers called on every device-state update.
        # See _ingress_hook.py for the protocol. Registration typically
        # happens in the owning entity's async_added_to_hass.
        self._ingress_hooks: list[IngressHook] = []
        self._connected = False
        self.blaueis_follow_me = BlauiesFollowMeManager(hass, self)

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
        """Stop the Device and Follow Me manager."""
        if self.blaueis_follow_me.active or self.blaueis_follow_me._stopping:
            await self.blaueis_follow_me.async_stop()
        await self.device.stop()
        self._connected = False

    # ── Write serializer (proxy to Device.write_lock) ───────

    @property
    def write_lock(self) -> asyncio.Lock:
        """Per-device write serializer, proxied from the Device.

        Exposed for callers that need to bundle a multi-frame sequence
        atomically against other integration-originated writes (user
        actions from HA entities, Follow Me, ingress-hook enforcers).
        Individual ``device.set`` / ``device.toggle_display`` calls
        take the same lock internally, so callers that just invoke one
        of those methods do not need to take this lock manually.
        """
        return self.device.write_lock

    # ── Ingress-hook registration ──────────────────────────

    def register_ingress_hook(self, hook: IngressHook) -> None:
        """Register a hook for device-state updates.

        The hook's ``on_ingress(coord)`` method will be called after
        every Device-originated state change (any ``rsp_*`` update).
        Registration is idempotent — the same hook instance is only
        registered once. See ``_ingress_hook.py`` for the protocol
        contract.
        """
        if hook not in self._ingress_hooks:
            self._ingress_hooks.append(hook)

    def unregister_ingress_hook(self, hook: IngressHook) -> None:
        """Unregister an ingress hook. Safe to call if not registered."""
        try:
            self._ingress_hooks.remove(hook)
        except ValueError:
            pass

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

    def fire_entity_callbacks(self, field_name: str) -> None:
        """Manually fire all callbacks registered for a field."""
        for cb in self._entity_callbacks.get(field_name, set()):
            try:
                cb()
            except Exception:
                _LOGGER.exception("Entity callback error for %s", field_name)

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

        # Fire ingress hooks (active-driving enforcers). Scheduled as a
        # task so this synchronous callback returns quickly — hooks run
        # concurrently on the event loop.
        if self._ingress_hooks:
            try:
                self.hass.loop.create_task(self._run_ingress_hooks())
            except Exception:
                _LOGGER.exception("Failed to schedule ingress hooks")

    async def _run_ingress_hooks(self) -> None:
        """Invoke every registered ingress hook concurrently.

        Hooks' exceptions are caught per-hook and logged; one hook's
        failure does not affect the others.
        """
        hooks = list(self._ingress_hooks)  # snapshot — tolerate concurrent (un)register
        if not hooks:
            return
        results = await asyncio.gather(
            *(h.on_ingress(self) for h in hooks),
            return_exceptions=True,
        )
        for hook, result in zip(hooks, results):
            if isinstance(result, Exception):
                _LOGGER.exception(
                    "Ingress hook %r raised: %s", hook, result,
                )

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

        Filters out CLIMATE_EXCLUSIVE_FIELDS (handled by climate.py) and
        ``screen_display`` (handled by the Display & Buzzer mode select —
        see select.py). Maps field_class → platform via FIELD_CLASS_MAP.
        """
        result = []
        for fname, fmeta in self.device.available_fields.items():
            if fname in CLIMATE_EXCLUSIVE_FIELDS:
                continue
            # power is handled by climate on/off — no standalone switch
            if fname == "power":
                continue
            # screen_display is absorbed into the quad-option Display &
            # Buzzer mode select. No separate switch.
            if fname == "screen_display":
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
