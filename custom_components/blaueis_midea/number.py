"""Number entities — the "secondary" slider for fields whose active cap
carries a `slider:` block in `active_constraints`. On your stepless fan unit
this is the free 1-100 slider; on discrete caps it snaps to the nearest
permitted raw within the slider range.

The slider is ALWAYS the secondary control — the primary is the enum
(handled elsewhere: climate.fan_mode or a select entity). The auto/escape
value (fan_speed=102) lives outside the slider range by design, so the
slider reports `unavailable` whenever the AC's raw is outside [range_min,
range_max].

**Two entities for one field is intentional.** A ``stateful_enum``
field whose cap declares both ``values`` *and* a ``slider`` block
(e.g. ``louver_swing_angle_lr_enum`` — five labelled positions plus
a 1-100 continuous slider in the cap) registers both a
``BlaueisMideaSelect`` (dropdown of the labelled positions) AND a
``BlaueisMideaSlider`` (free range). Different interaction modes
serve different intents:

- The dropdown is the "I want one of the standard positions" path —
  five labelled buttons, easy on the device card.
- The slider is the "I want a specific raw" path — useful when an
  external controller has parked the vane off-grid, when the user
  wants to script a position outside the dropdown set, or when
  fine-grained control matters more than label-readability.

Both write to the same wire field; the AC's snap behaviour decides
where the vane physically lands. Hiding either would lose a
legitimate interaction surface.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from ._set_result import check_set_result
from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a number entity for every field whose active cap advertises a
    slider block in its active_constraints."""
    coordinator: BlaueisMideaCoordinator = entry.runtime_data

    entities: list[NumberEntity] = []
    candidates = 0
    for fname, fmeta in coordinator.device.available_fields.items():
        ac = fmeta.get("active_constraints") or {}
        slider = ac.get("slider")
        if not isinstance(slider, dict):
            continue
        candidates += 1
        entities.append(BlaueisMideaSlider(coordinator, fname, fmeta))
    _LOGGER.debug(
        "number platform: %d candidates with slider, %d entities built",
        candidates,
        len(entities),
    )
    if entities:
        async_add_entities(entities)


class BlaueisMideaSlider(NumberEntity):
    """Secondary slider. Range and snap mode come from active_constraints.slider."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    should_poll = False

    def __init__(
        self,
        coordinator: BlaueisMideaCoordinator,
        field_name: str,
        fmeta: dict,
    ) -> None:
        self._coord = coordinator
        self._device = coordinator.device
        self._field_name = field_name

        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_{field_name}_slider"
        )
        ac = fmeta.get("active_constraints") or {}
        slider = ac.get("slider") or {}
        self._attr_name = (
            slider.get("name") or f"{field_name.replace('_', ' ').title()}"
        )

        r = slider.get("range") or [0, 100]
        self._attr_native_min_value = float(r[0])
        self._attr_native_max_value = float(r[1])
        self._attr_native_step = float(slider.get("step", 1))
        self._mode = slider.get("mode", "clamp")  # clamp | snap_nearest | reject

        # Snap target set: cap's valid_set (if any) filtered to slider range.
        self._snap_set: list[int] = []
        valid_set = ac.get("valid_set") or []
        for v in valid_set:
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if self._attr_native_min_value <= n <= self._attr_native_max_value:
                self._snap_set.append(n)
        self._snap_set.sort()

        # Non-user-selectable raws — values the AC reports for system-only
        # states (e.g. ``louver_swing_angle_lr_enum = 0`` "released" while
        # swing mode is active). Read straight from the field's glossary
        # ``values`` block; entries with ``user_selectable: false`` go in.
        # The slider's ``native_value`` returns None for those so HA
        # renders unknown instead of clamping the raw up to ``min`` and
        # showing a phantom position.
        self._non_user_selectable_raws: set[int] = set()
        gdef = coordinator.device.field_gdef(field_name) or {}
        for vdef in (gdef.get("values") or {}).values():
            if not isinstance(vdef, dict):
                continue
            raw = vdef.get("raw")
            if raw is None:
                continue
            if not vdef.get("user_selectable", True):
                self._non_user_selectable_raws.add(raw)

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    async def async_added_to_hass(self) -> None:
        self._coord.register_entity_callback(
            self._field_name, self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        self._coord.unregister_entity_callback(
            self._field_name, self.async_write_ha_state
        )

    @property
    def available(self) -> bool:
        if not self._coord.connected:
            return False
        if not self._coord.device_fresh:
            return False
        power = self._coord.device.read("power")
        return bool(power)

    @property
    def native_value(self) -> float | None:
        raw = self._device.read(self._field_name)
        if raw is None:
            return None
        if raw in self._non_user_selectable_raws:
            # AC reports a system-only raw (e.g. "released" while swing
            # mode is active). The slider can't depict it without lying;
            # return None so HA renders unknown. Slider stays available
            # so the user can still drag to set a new position, which
            # the AC accepts and snaps the slot back into the
            # user-selectable space.
            return None
        return float(
            max(self._attr_native_min_value, min(raw, self._attr_native_max_value))
        )

    async def async_set_native_value(self, value: float) -> None:
        n = int(round(value))
        lo = int(self._attr_native_min_value)
        hi = int(self._attr_native_max_value)
        n = max(lo, min(hi, n))  # clamp to slider range first

        if self._mode == "snap_nearest" and self._snap_set:
            n = min(self._snap_set, key=lambda x: abs(x - n))
        # "clamp" already covered above; "reject" not applied at slider level
        # (the slider UI doesn't present out-of-range values, so we don't raise)

        result = await self._device.set(**{self._field_name: n})
        check_set_result(result, primary_fields={self._field_name})
