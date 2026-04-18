"""Select entities — auto-mapped from glossary stateful_enum (writable).

Options are the glossary's value *names* (e.g. "center", "left_mid", "low"),
not the raw integers. Name→raw and raw→name mappings are resolved from the
field's `values:` block. If the device echoes a raw value that isn't in the
exact name→raw table, the entity snaps to the nearest user-selectable raw on
display so the dropdown always shows a valid option — preserves the glossary's
"device is authority" principle while giving HA a clean state to render.

Per-value flag `user_selectable: false` hides a value from the user-facing
options list (while still mapping it on read). Used for e.g. vane-angle raw 0
("released"), which only the AC itself sets.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from ._set_result import check_set_result
from ._ux_mixin import field_ux_available
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
        gdef = coordinator.device.field_gdef(self._field_name) or {}
        self._attr_name = gdef.get("label") or self._field_name.replace("_", " ").title()

        ha_meta = gdef.get("ha") or {}
        if ha_meta.get("enabled_default") is False:
            self._attr_entity_registry_enabled_default = False

        # Build the label↔raw maps from the glossary `values:` block. Each
        # entry's `user_selectable: false` flag (default true) excludes it
        # from the HA options list but keeps the raw→label mapping for reads.
        # `label:` overrides the YAML key as the user-visible option string.
        values = gdef.get("values") or {}

        self._name_to_raw: dict[str, int] = {}
        self._raw_to_name: dict[int, str] = {}
        user_options: list[str] = []
        for key, vdef in values.items():
            if not isinstance(vdef, dict):
                continue
            raw = vdef.get("raw")
            if raw is None:
                continue
            display = vdef.get("label", key)
            self._name_to_raw[display] = raw
            # Earlier entries win on raw collisions — preserves declaration order
            self._raw_to_name.setdefault(raw, display)
            if vdef.get("user_selectable", True):
                user_options.append(display)

        # Legacy fallback: capability.default.valid_set as a list of raws
        constraints = desc.get("active_constraints") or {}
        valid_set = constraints.get("valid_set")
        if not user_options and valid_set:
            user_options = [str(v) for v in valid_set]
            for v in valid_set:
                try:
                    self._name_to_raw.setdefault(str(v), int(v))
                except (TypeError, ValueError):
                    pass

        self._attr_options = user_options
        self._user_selectable_raws = sorted(
            {self._name_to_raw[n] for n in user_options if n in self._name_to_raw}
        )

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
    def current_option(self) -> str | None:
        """Translate the field's raw value → an option the user sees.

        1. Exact match in raw→name table → return that name (even for
           non-user-selectable ones, so HA doesn't flag it as "unknown").
        2. No exact match → snap to the nearest user-selectable raw and
           return its name. Preserves the invariant that the dropdown
           always has a valid selected entry even when the AC reports
           an off-grid intermediate value (e.g. mid-motion, or an external
           controller set 23 instead of 25).
        3. No user-selectable raws at all → str(val) as a last-resort label.
        """
        val = self._coord.device.read(self._field_name)
        if val is None:
            return None
        if val in self._raw_to_name:
            return self._raw_to_name[val]
        if not self._user_selectable_raws:
            return str(val)
        try:
            nearest = min(self._user_selectable_raws, key=lambda r: abs(r - val))
        except TypeError:
            return str(val)
        return self._raw_to_name.get(nearest)

    async def async_select_option(self, option: str) -> None:
        # User picked an option name — translate to raw via the glossary map.
        # Only user-selectable options appear in the dropdown, so a non-
        # mapping option string is almost certainly a caller bug, but we
        # fall back to int-parse for backward compatibility with any
        # dashboard config that used raw values as the option string.
        if option in self._name_to_raw:
            value: int | str = self._name_to_raw[option]
        else:
            try:
                value = int(option)
            except ValueError:
                value = option
        result = await self._coord.device.set(**{self._field_name: value})
        check_set_result(result, primary_fields={self._field_name})
