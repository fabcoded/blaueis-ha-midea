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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from blaueis.core.codec import walk_fields
from blaueis.core.ux_gating import is_field_visible

from . import BlaueisMideaConfigEntry
from ._preflight import validate_or_raise
from ._set_result import check_set_result
from .const import (
    CLIMATE_PRESET_FIELDS,
    FAN_PRESET_TO_SPEED,
    FAN_SPEED_TO_PRESET,
    MODE_HA_TO_MIDEA,
    MODE_MIDEA_TO_HA,
    PRESET_NAME_TO_FIELD,
    SWING_AXES,
)
from ._swing import axis_mode, axis_options, axis_set_changes
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
    # Entity translation_key — maps the climate state-attribute option slugs
    # (swing_mode / swing_horizontal_mode) to labels in translations/<lang>.json
    # under entity.climate.blaueis_ac.state_attributes.*. Without it the custom
    # swing/vane slugs render raw (e.g. "upper_middle"). No top-level `name`
    # entry is provided, so this stays the device's main (device-named) entity.
    _attr_translation_key = "blaueis_ac"
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

        # Swing & vane-position — per axis (vertical → swing_mode,
        # horizontal → swing_horizontal_mode). Options are built from caps in
        # _axis_options(); an axis with neither swing nor positions is dropped.
        # Feature presence is decided once at setup (an axis with neither a
        # swing nor an angle field at boot has no control). The OPTION LISTS are
        # computed LIVE (swing_modes / swing_horizontal_modes properties below)
        # from available_fields, so a cap change can never leave the dropdown
        # offering a vane position that the set path then silently rejects.
        if any(SWING_AXES["vertical"][k] in avail for k in ("swing", "angle")):
            features |= ClimateEntityFeature.SWING_MODE
        if any(SWING_AXES["horizontal"][k] in avail for k in ("swing", "angle")):
            features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE

        # ── Presets (B5-gated) ─────────────────────────────
        self._available_presets: dict[str, str] = {}  # field_name → preset_name
        for field_name, preset_name in CLIMATE_PRESET_FIELDS.items():
            if field_name in avail:
                self._available_presets[field_name] = preset_name

        # The preset list is computed LIVE (preset_modes property) so only
        # presets valid in the current operating mode are offered — e.g.
        # Frost Protection (heat-only) is hidden in cool, instead of being
        # offered and then rejected by the device with a stale selection left
        # showing. _preset_gdefs caches each preset field's glossary def for the
        # visibility check.
        self._preset_gdefs: dict[str, dict] = {}
        if self._available_presets:
            features |= ClimateEntityFeature.PRESET_MODE
            all_fields = walk_fields(self._device.glossary)
            self._preset_gdefs = {
                f: all_fields.get(f, {}) for f in self._available_presets
            }

        self._attr_supported_features = features

        # ── HVAC modes (B5-gated) ──────────────────────────
        self._attr_hvac_modes = self._determine_hvac_modes()

        # ── Fan modes (derived from active cap 0x10) ──────
        fan_meta = avail.get("fan_speed", {})
        fan_ac = fan_meta.get("active_constraints") or {}
        cap_values = fan_ac.get("values") or {}
        self._fan_name_to_raw: dict[str, int] = {}
        self._fan_raw_to_name: dict[int, str] = {}
        for key, vdef in cap_values.items():
            raw = vdef.get("raw") if isinstance(vdef, dict) else None
            if raw is None:
                continue
            display = vdef.get("label", key) if isinstance(vdef, dict) else key
            self._fan_name_to_raw[display] = raw
            self._fan_raw_to_name.setdefault(raw, display)
        if self._fan_name_to_raw:
            # Option A: an off-grid fan_speed (no named preset for that raw)
            # surfaces as a blank fan tile (fan_mode -> None), not a synthetic
            # "Custom" option — the dropdown lists only the real named presets.
            self._attr_fan_modes = list(self._fan_name_to_raw.keys())
        else:
            # Pre-B5 fallback
            self._attr_fan_modes = list(FAN_PRESET_TO_SPEED.keys())
            self._fan_name_to_raw = dict(FAN_PRESET_TO_SPEED)
            self._fan_raw_to_name = dict(FAN_SPEED_TO_PRESET)

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
            modes.extend(
                [
                    HVACMode.AUTO,
                    HVACMode.COOL,
                    HVACMode.HEAT,
                    HVACMode.DRY,
                    HVACMode.FAN_ONLY,
                ]
            )

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
        return self._coord.connected and self._coord.device_fresh

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
        # Option A: an off-grid raw (no named preset) blanks the tile (None).
        return self._fan_raw_to_name.get(speed)

    # ── Swing / vane-position helpers (per axis) ───────────
    # Mapping logic lives in the HA-free _swing module (unit-tested directly);
    # these thin wrappers bind it to the live device.
    def _axis_options(self, axis: str) -> list[str]:
        """Option list for an axis, from its caps (['off'] + swing + positions)."""
        return axis_options(axis, self._device.available_fields)

    def _axis_mode(self, axis: str) -> str:
        """Current option for an axis: swing wins, else a position, else off."""
        return axis_mode(axis, self._device.available_fields, self._device.read)

    async def _set_axis(self, axis: str, option: str) -> None:
        """Set one axis with a SINGLE field write; the firmware enforces the
        exclusion and clears the mutually-exclusive sibling."""
        changes = axis_set_changes(
            axis, option, self._device.available_fields, self._device.read
        )
        if changes is None:
            _LOGGER.warning("blaueis: ignoring unsupported %s swing option %r", axis, option)
            return
        result = await self._device.set(**changes)
        check_set_result(result, primary_fields=set(changes))

    @property
    def swing_modes(self) -> list[str] | None:
        """Vertical-axis option list, computed live from caps on every read
        (plain property, not a cached __init__ snapshot — so the offered
        options always match what the set path will accept)."""
        if not (self._attr_supported_features & ClimateEntityFeature.SWING_MODE):
            return None
        return self._axis_options("vertical")

    @property
    def swing_horizontal_modes(self) -> list[str] | None:
        """Horizontal-axis option list, computed live (see ``swing_modes``)."""
        if not (self._attr_supported_features & ClimateEntityFeature.SWING_HORIZONTAL_MODE):
            return None
        return self._axis_options("horizontal")

    @property
    def swing_mode(self) -> str | None:
        if not (self._attr_supported_features & ClimateEntityFeature.SWING_MODE):
            return None
        return self._axis_mode("vertical")

    @property
    def swing_horizontal_mode(self) -> str | None:
        if not (self._attr_supported_features & ClimateEntityFeature.SWING_HORIZONTAL_MODE):
            return None
        return self._axis_mode("horizontal")

    def _preset_visible(self, field_name: str) -> bool:
        """Whether a preset is selectable in the current operating mode
        (heat-only Frost Protection is hidden in cool, etc.)."""
        return is_field_visible(
            self._preset_gdefs.get(field_name, {}),
            current_mode=self._device.read("operating_mode"),
        )

    @property
    def preset_modes(self) -> list[str] | None:
        """Live preset list: 'none' plus only the presets selectable right now.
        Computed each read (not a cached __init__ snapshot), so the card never
        offers — and the base class never accepts — a preset the device would
        reject. Presets only engage while running, so while powered off nothing
        but 'none' is offered; otherwise only the mutually-exclusive presets
        valid in the current mode (e.g. Frost Protection is hidden in cool)."""
        if not self._available_presets:
            return None
        if not self._device.read("power"):
            return [PRESET_NONE]
        return [
            PRESET_NONE,
            *(
                name
                for field, name in self._available_presets.items()
                if self._preset_visible(field)
            ),
        ]

    @property
    def preset_mode(self) -> str | None:
        """The active preset, or 'none'. Only a preset that is active AND
        currently selectable (powered on, valid in the current mode) is
        reported, so the displayed selection always matches an offered option."""
        if not self._available_presets:
            return None
        if not self._device.read("power"):
            return PRESET_NONE
        for field_name, preset_name in self._available_presets.items():
            if self._device.read(field_name) and self._preset_visible(field_name):
                return preset_name
        return PRESET_NONE

    # ── Commands ────────────────────────────────────────────
    # Disconnect handling: rely on the device.set() layer to reject when
    # the gateway is down — same as switch/select/number platforms. No
    # explicit pre-flight check here so the UX stays uniform across
    # platforms (silent unavailability via state, not a raised error).

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            result = await self._device.set(power=False)
            check_set_result(result, primary_fields={"power"})
        else:
            midea_mode = MODE_HA_TO_MIDEA.get(hvac_mode.value)
            if midea_mode is not None:
                validate_or_raise(self._coord, "operating_mode", midea_mode)
                result = await self._device.set(power=True, operating_mode=midea_mode)
                check_set_result(result, primary_fields={"power", "operating_mode"})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            validate_or_raise(self._coord, "target_temperature", temp)
            result = await self._device.set(target_temperature=temp)
            check_set_result(result, primary_fields={"target_temperature"})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed = self._fan_name_to_raw.get(fan_mode)
        if speed is not None:
            validate_or_raise(self._coord, "fan_speed", speed)
            result = await self._device.set(fan_speed=speed)
            check_set_result(result, primary_fields={"fan_speed"})

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._set_axis("vertical", swing_mode)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        await self._set_axis("horizontal", swing_horizontal_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset — clears the other presets first (mutually exclusive,
        so only one is ever active)."""
        changes = {}
        primary: set[str] = set()
        # Only clear presets that are valid in the current mode: a mode-invalid
        # one can't be active anyway, and sending it (even =off) just trips the
        # mode gate and logs a spurious rejection.
        for field_name in self._available_presets:
            if self._preset_visible(field_name):
                changes[field_name] = False
        if preset_mode != PRESET_NONE:
            target_field = PRESET_NAME_TO_FIELD.get(preset_mode)
            if target_field and target_field in self._available_presets:
                changes[target_field] = True
                primary.add(target_field)
        if changes:
            result = await self._device.set(**changes)
            try:
                check_set_result(result, primary_fields=primary)
            finally:
                # Re-push the real state so a rejected / unapplied preset
                # reverts in the card to the actually-active one instead of
                # leaving the attempted selection shown.
                self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        result = await self._device.set(power=True)
        check_set_result(result, primary_fields={"power"})

    async def async_turn_off(self) -> None:
        result = await self._device.set(power=False)
        check_set_result(result, primary_fields={"power"})
