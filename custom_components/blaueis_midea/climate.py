"""Climate entity for Blaueis Midea AC.

Folds operating_mode, target_temperature, and fan_speed into a single
HA climate entity. Capabilities (available modes, temp ranges, fan presets)
are derived from B5 capability responses.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from .const import (
    DOMAIN,
    FAN_PRESET_TO_SPEED,
    FAN_SPEED_TO_PRESET,
    MODE_HA_TO_MIDEA,
    MODE_MIDEA_TO_HA,
)
from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate entity."""
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    async_add_entities([BlaueisMideaClimate(coordinator)])


class BlaueisMideaClimate(ClimateEntity):
    """Climate entity backed by the Blaueis Device."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _enable_turn_on_off_backwards_compat = False
    should_poll = False

    def __init__(self, coordinator: BlaueisMideaCoordinator) -> None:
        self._coord = coordinator
        self._device = coordinator.device

        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_climate"

        # Determine supported features from B5 capabilities
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        avail = self._device.available_fields
        if "swing_vertical" in avail:
            features |= ClimateEntityFeature.SWING_MODE

        self._attr_supported_features = features

        # Available HVAC modes from B5 constraints
        self._attr_hvac_modes = self._determine_hvac_modes()
        self._attr_fan_modes = list(FAN_PRESET_TO_SPEED.keys())

        # Temperature range from B5 constraints
        temp_meta = avail.get("target_temperature", {})
        constraints = temp_meta.get("active_constraints") or {}
        valid_range = constraints.get("valid_range")
        if valid_range and len(valid_range) == 2:
            self._attr_min_temp = valid_range[0]
            self._attr_max_temp = valid_range[1]
        else:
            self._attr_min_temp = 16.0
            self._attr_max_temp = 30.0

        step = constraints.get("step")
        self._attr_target_temperature_step = step if step else 1.0

        # Swing modes
        if features & ClimateEntityFeature.SWING_MODE:
            self._attr_swing_modes = ["off", "vertical"]
            if "swing_horizontal" in avail:
                self._attr_swing_modes.append("horizontal")
                self._attr_swing_modes.append("both")

    def _determine_hvac_modes(self) -> list[HVACMode]:
        """Determine available HVAC modes from B5 capabilities."""
        modes = [HVACMode.OFF]
        mode_meta = self._device.available_fields.get("operating_mode", {})
        constraints = mode_meta.get("active_constraints") or {}
        valid_set = constraints.get("valid_set")

        if valid_set:
            for midea_val in valid_set:
                ha_mode = MODE_MIDEA_TO_HA.get(midea_val)
                if ha_mode:
                    modes.append(HVACMode(ha_mode))
        else:
            # Fallback: assume common modes
            modes.extend([
                HVACMode.AUTO,
                HVACMode.COOL,
                HVACMode.HEAT,
                HVACMode.DRY,
                HVACMode.FAN_ONLY,
            ])

        return modes

    # ── HA lifecycle ────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Register for state change callbacks."""
        self._coord.register_entity_callback("_climate", self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        self._coord.unregister_entity_callback("_climate", self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    @property
    def available(self) -> bool:
        return self._coord.connected

    # ── State properties ────────────────────────────────────

    @property
    def hvac_mode(self) -> HVACMode:
        power = self._device.read("power")
        if not power:
            return HVACMode.OFF
        mode_val = self._device.read("operating_mode")
        ha_mode = MODE_MIDEA_TO_HA.get(mode_val)
        return HVACMode(ha_mode) if ha_mode else HVACMode.OFF

    @property
    def target_temperature(self) -> float | None:
        return self._device.read("target_temperature")

    @property
    def current_temperature(self) -> float | None:
        return self._device.read("indoor_temperature")

    @property
    def fan_mode(self) -> str | None:
        speed = self._device.read("fan_speed")
        if speed is None:
            return None
        return FAN_SPEED_TO_PRESET.get(speed, f"speed_{speed}")

    @property
    def swing_mode(self) -> str | None:
        v = self._device.read("swing_vertical")
        h = self._device.read("swing_horizontal")
        v_on = v not in (None, 0, False)
        h_on = h not in (None, 0, False)
        if v_on and h_on:
            return "both"
        if v_on:
            return "vertical"
        if h_on:
            return "horizontal"
        return "off"

    # ── Commands ────────────────────────────────────────────

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._device.set(power=False)
        else:
            midea_mode = MODE_HA_TO_MIDEA.get(hvac_mode.value)
            if midea_mode is not None:
                await self._device.set(power=True, operating_mode=midea_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self._device.set(target_temperature=temp)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed = FAN_PRESET_TO_SPEED.get(fan_mode)
        if speed is not None:
            await self._device.set(fan_speed=speed)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        v = swing_mode in ("vertical", "both")
        h = swing_mode in ("horizontal", "both")
        changes = {}
        if "swing_vertical" in self._device.available_fields:
            changes["swing_vertical"] = 0xC if v else 0
        if "swing_horizontal" in self._device.available_fields:
            changes["swing_horizontal"] = 0xC if h else 0
        if changes:
            await self._device.set(**changes)

    async def async_turn_on(self) -> None:
        await self._device.set(power=True)

    async def async_turn_off(self) -> None:
        await self._device.set(power=False)
