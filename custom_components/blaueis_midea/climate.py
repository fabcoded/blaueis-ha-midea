"""Climate entity for Blaueis Midea AC.

Folds operating_mode, target_temperature, fan_speed, and mutually
exclusive presets (turbo/eco/sleep/frost) into a single HA climate
entity. All features are B5-gated — only confirmed capabilities appear.
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
    CLIMATE_PRESET_FIELDS,
    DOMAIN,
    FAN_PRESET_TO_SPEED,
    FAN_SPEED_TO_PRESET,
    MODE_HA_TO_MIDEA,
    MODE_MIDEA_TO_HA,
    PRESET_NAME_TO_FIELD,
)
from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)

PRESET_NONE = "none"


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

        avail = self._device.available_fields

        # ── Supported features (B5-gated) ──────────────────
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        if "swing_vertical" in avail:
            features |= ClimateEntityFeature.SWING_MODE

        # ── Presets (B5-gated) ─────────────────────────────
        self._available_presets: dict[str, str] = {}  # field_name → preset_name
        for field_name, preset_name in CLIMATE_PRESET_FIELDS.items():
            if field_name in avail:
                self._available_presets[field_name] = preset_name

        if self._available_presets:
            features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = [
                PRESET_NONE,
                *self._available_presets.values(),
            ]

        self._attr_supported_features = features

        # ── HVAC modes (B5-gated) ──────────────────────────
        self._attr_hvac_modes = self._determine_hvac_modes()
        self._attr_fan_modes = list(FAN_PRESET_TO_SPEED.keys())

        # ── Temperature range (B5 constraints) ─────────────
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

        # ── Swing modes ────────────────────────────────────
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
        self._coord.register_entity_callback("_climate", self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
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
        preset = FAN_SPEED_TO_PRESET.get(speed)
        if preset:
            return preset
        if speed >= 80:
            return "high"
        if speed >= 60:
            return "medium"
        return "low"

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

    @property
    def preset_mode(self) -> str | None:
        """Return the active preset, or 'none'."""
        if not self._available_presets:
            return None
        for field_name, preset_name in self._available_presets.items():
            if self._device.read(field_name):
                return preset_name
        return PRESET_NONE

    # ── Commands ────────────────────────────────────────────

    def _check_connected(self) -> None:
        """Raise if gateway is not connected."""
        if not self._coord.connected:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError("Gateway not connected")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._check_connected()
        if hvac_mode == HVACMode.OFF:
            await self._device.set(power=False)
        else:
            midea_mode = MODE_HA_TO_MIDEA.get(hvac_mode.value)
            if midea_mode is not None:
                await self._device.set(power=True, operating_mode=midea_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        self._check_connected()
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self._device.set(target_temperature=temp)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._check_connected()
        speed = FAN_PRESET_TO_SPEED.get(fan_mode)
        if speed is not None:
            await self._device.set(fan_speed=speed)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        # Glossary raw values — codec masks to field bit width before placing
        # in the byte. Previous 0xC was the already-shifted in-byte pattern,
        # which the codec then re-masked down to 0 (= OFF). Confirmed on the
        # wire: raw 3 puts 0b11 into bits[3:2] of body[7] → 0x0C → ON.
        self._check_connected()
        v = swing_mode in ("vertical", "both")
        h = swing_mode in ("horizontal", "both")
        changes = {}
        if "swing_vertical" in self._device.available_fields:
            changes["swing_vertical"] = 3 if v else 0
        if "swing_horizontal" in self._device.available_fields:
            changes["swing_horizontal"] = 3 if h else 0
        if changes:
            await self._device.set(**changes)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset — clears all other presets first."""
        self._check_connected()
        changes = {}
        for field_name in self._available_presets:
            changes[field_name] = False
        if preset_mode != PRESET_NONE:
            target_field = PRESET_NAME_TO_FIELD.get(preset_mode)
            if target_field and target_field in self._available_presets:
                changes[target_field] = True
        if changes:
            await self._device.set(**changes)

    async def async_turn_on(self) -> None:
        self._check_connected()
        await self._device.set(power=True)

    async def async_turn_off(self) -> None:
        self._check_connected()
        await self._device.set(power=False)
