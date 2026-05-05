"""Select entities.

Two classes:

- `BlaueisMideaSelect` — auto-mapped from glossary stateful_enum (writable).
  Options are the glossary's value *names* (e.g. "center", "left_mid", "low"),
  not the raw integers. Snaps to nearest user-selectable raw on read-only
  off-grid values so the dropdown always shows a valid option.

- `BlaueisMideaDisplayBuzzerModeSelect` — integration-level setting
  (NOT backed by a glossary field). Owns the lifecycle of a
  `DisplayBuzzerEnforcer` that maintains the AC's display-LED latch in
  the user-selected state. See ``display_buzzer_enforcer.py`` and
  ``PLAN_display_buzzer_enforcer.md`` for the protocol background.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from ._i18n import glossary_label_for_lang
from ._preflight import validate_or_raise
from ._set_result import check_set_result
from ._ux_mixin import field_ux_available, field_writable_in_current_mode
from .const import (
    CONF_DISPLAY_BUZZER_MODE,
    DISPLAY_BUZZER_MODE_DEFAULT,
    DISPLAY_BUZZER_OPTION_FORCED_OFF,
    DISPLAY_BUZZER_OPTION_FORCED_ON,
    DISPLAY_BUZZER_OPTION_OFF,
    DISPLAY_BUZZER_OPTION_ON,
    DISPLAY_BUZZER_OPTIONS,
    DISPLAY_BUZZER_POLICIES,
    DISPLAY_BUZZER_POLICY_FORCED_OFF,
    DISPLAY_BUZZER_POLICY_FORCED_ON,
    DISPLAY_BUZZER_POLICY_NON_ENFORCED,
)
from .coordinator import BlaueisMideaCoordinator
from .display_buzzer_enforcer import (
    DISPLAY_STATE_OFF,
    DISPLAY_STATE_ON,
    DisplayBuzzerEnforcer,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    for desc in coordinator.get_entities_for_platform("select"):
        entities.append(BlaueisMideaSelect(coordinator, desc))

    # Cap-gate the Display & Buzzer mode select: only expose it on devices
    # that advertise the screen_display cap (B5 `0x24/extended` ↔ cap_id_16
    # `0x0224`). `available_fields` is the live resolution of that gate —
    # it only contains the field when the advertisement's value resolved
    # to an enabled `feature_available`. Matches the cap-gating applied
    # to `switch.screen_display` by the generic platform dispatch, so on
    # an unsupported device the whole feature-surface disappears together.
    if _screen_display_cap_advertised(coordinator):
        entities.append(BlaueisMideaDisplayBuzzerModeSelect(hass, entry, coordinator))

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
        self._attr_name = glossary_label_for_lang(
            gdef,
            self._field_name,
            getattr(coordinator.hass.config, "language", None),
        )

        ha_meta = gdef.get("ha") or {}
        if gdef.get("feature_available", "").endswith("-opt"):
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
        if not field_writable_in_current_mode(self._coord, self._field_name):
            return False
        power = self._coord.device.read("power")
        return bool(power)

    @property
    def options(self) -> list[str]:
        """Dropdown options, dynamically expanded.

        Base options are the user-selectable labels resolved at
        init-time from the glossary's ``values`` block. When the AC
        currently reports a raw whose label is *not* user-selectable
        (e.g. ``louver_swing_angle_lr_enum = 0`` "released" reported
        while swing mode is active), append that label so HA can render
        the truthful state instead of falling back to ``unknown``.
        Selecting a non-user-selectable option is a UI no-op — see
        :meth:`async_select_option`.
        """
        base = list(self._attr_options)
        val = self._coord.device.read(self._field_name)
        if val is not None and val in self._raw_to_name:
            label = self._raw_to_name[val]
            if label not in base:
                base.append(label)
        return base

    @property
    def current_option(self) -> str | None:
        """Translate the field's raw value → an option the user sees.

        1. Exact match in raw→name table → return that name (even for
           non-user-selectable ones — :meth:`options` adds them
           dynamically so HA accepts the state).
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
        # Non-user-selectable options (e.g. "released" / "-- (0)") are
        # surfaced by `options` so HA can render the AC-controlled state
        # truthfully, but writing them is the AC's prerogative — picking
        # one in the UI is a no-op. Re-fire write_ha_state so any
        # optimistic frontend selection snaps back to the actual
        # ``current_option`` (still the AC-reported value).
        if (
            isinstance(value, int)
            and self._user_selectable_raws
            and value not in self._user_selectable_raws
        ):
            self.async_write_ha_state()
            return
        validate_or_raise(self._coord, self._field_name, value)
        result = await self._coord.device.set(**{self._field_name: value})
        check_set_result(result, primary_fields={self._field_name})


# ── Display & Buzzer mode select ─────────────────────────────────────


def _screen_display_cap_advertised(coord: BlaueisMideaCoordinator) -> bool:
    """Does the device's B5 advertisement include the screen_display cap?

    We check via ``available_fields`` — a field whose capability was
    advertised has its ``feature_available`` lifted out of the gated-off
    state, so it shows up here. If it's not in ``available_fields`` we
    treat it as not advertised (can't enforce).
    """
    return "screen_display" in coord.device.available_fields


def _read_observed_display_bits(coord: BlaueisMideaCoordinator) -> int | None:
    """Translate the decoded screen_display(_now) state back to the 3-bit
    value the enforcer compares against.

    The Lua plugin decodes ``rsp_0xC0 body[14]`` bits[6:4] into a string
    ``"on"``/``"off"`` (see Finding 07 §2.A read path). We invert that
    mapping to the integer the enforcer's state machine expects:

      - ``"off"`` → ``DISPLAY_STATE_OFF`` (7)
      - ``"on"``  → ``DISPLAY_STATE_ON`` (0)
      - anything else, or ``None`` → ``None`` (unknown)
    """
    val = coord.device.read("screen_display_now")
    if val is None:
        val = coord.device.read("screen_display")
    if val is None:
        return None
    if isinstance(val, bool):
        return DISPLAY_STATE_ON if val else DISPLAY_STATE_OFF
    if isinstance(val, str):
        lowered = val.lower()
        if lowered == "on":
            return DISPLAY_STATE_ON
        if lowered == "off":
            return DISPLAY_STATE_OFF
    if isinstance(val, int) and 0 <= val <= 7:
        return val
    return None


class BlaueisMideaDisplayBuzzerModeSelect(SelectEntity):
    """Quad-option display/buzzer selector.

    Stored policy (config entry) is one of three:
    ``non_enforced`` (default), ``forced_on``, ``forced_off`` — see
    ``const.DISPLAY_BUZZER_POLICIES``.

    The entity surfaces **four** options (``on``, ``off``, ``forced_on``,
    ``forced_off``). When the stored policy is ``non_enforced``,
    ``current_option`` mirrors the live display state (``on``/``off``);
    when forced, it returns the forced value directly. This collapses
    the old separate ``switch.screen_display`` and 3-state mode select
    into one widget — one control, one source of truth.

    User picks resolve to:

    - ``on``/``off`` → store policy ``non_enforced``; if the current live
      state ≠ picked value, fire one ``cmd_0x41 body[1]=0x61`` toggle
      (non-enforcing: fire-and-forget, no retries, no cooldown).
    - ``forced_on``/``forced_off`` → store matching policy; kick the
      enforcer so it evaluates and, if drifted, enters its normal
      cooldown-bounded correction loop.

    See ``PLAN_display_buzzer_enforcer.md`` (quad-state section) and
    ``display_buzzer_enforcer.py``.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "display_buzzer_mode"
    _attr_icon = "mdi:volume-source"
    _attr_options = list(DISPLAY_BUZZER_OPTIONS)
    should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BlaueisMideaConfigEntry,
        coordinator: BlaueisMideaCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coord = coordinator
        self._attr_unique_id = (
            f"{coordinator.host}_{coordinator.port}_display_buzzer_mode"
        )
        self._attr_name = "Display & Buzzer mode"
        self._enforcer: DisplayBuzzerEnforcer | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    @property
    def available(self) -> bool:
        # Require coordinator up AND the cap still advertised. Setup-time
        # gating in async_setup_entry only runs once; if the firmware
        # stops advertising screen_display mid-session (re-pair, firmware
        # update, glossary change) we mark the entity unavailable rather
        # than letting it silently no-op. The enforcer also stops issuing
        # toggles in this case (via its get_cap_available callback).
        if not self._coord.connected:
            return False
        return _screen_display_cap_advertised(self._coord)

    def _stored_policy(self) -> str:
        """Return the stored policy, normalising unknown values to
        non-enforced so the UI never shows an invalid option."""
        raw = self._entry.options.get(
            CONF_DISPLAY_BUZZER_MODE, DISPLAY_BUZZER_MODE_DEFAULT
        )
        if raw not in DISPLAY_BUZZER_POLICIES:
            return DISPLAY_BUZZER_POLICY_NON_ENFORCED
        return raw

    @property
    def current_option(self) -> str | None:
        """Resolve the entity-level option from stored policy + live state.

        - policy ``forced_on`` → ``forced_on``
        - policy ``forced_off`` → ``forced_off``
        - policy ``non_enforced`` → ``on``/``off`` from rsp_0xC0 readback,
          or ``None`` if the state has not been observed yet (first
          ingress hasn't arrived).
        """
        policy = self._stored_policy()
        if policy == DISPLAY_BUZZER_POLICY_FORCED_ON:
            return DISPLAY_BUZZER_OPTION_FORCED_ON
        if policy == DISPLAY_BUZZER_POLICY_FORCED_OFF:
            return DISPLAY_BUZZER_OPTION_FORCED_OFF
        # non-enforced — mirror live state.
        observed = _read_observed_display_bits(self._coord)
        if observed == DISPLAY_STATE_ON:
            return DISPLAY_BUZZER_OPTION_ON
        if observed == DISPLAY_STATE_OFF:
            return DISPLAY_BUZZER_OPTION_OFF
        return None

    async def async_added_to_hass(self) -> None:
        # Build the enforcer. Callbacks close over self/coord so they
        # always read fresh state — no stale snapshots.
        self._enforcer = DisplayBuzzerEnforcer(
            get_mode=self._stored_policy,
            get_observed=lambda: _read_observed_display_bits(self._coord),
            send_toggle=self._coord.device.toggle_display,
            send_silent_poll=self._coord.device.send_silent_poll,
            # Defensive runtime gate: if the cap disappears from
            # available_fields while we're alive (late B5 change, etc.)
            # the enforcer stops issuing toggles. Setup-time gating in
            # async_setup_entry normally prevents this callback from
            # ever returning False — this is belt-and-braces.
            get_cap_available=lambda: _screen_display_cap_advertised(self._coord),
            logger=_LOGGER,
        )
        self._coord.register_ingress_hook(self._enforcer)
        # Keep the entity's displayed option in sync with live state. In
        # non-enforced policy, current_option mirrors screen_display, so
        # any change to that field must write_ha_state. This also drives
        # availability updates on cap transitions (the field stops
        # updating when the cap vanishes).
        self._coord.register_entity_callback(
            "screen_display", self.async_write_ha_state
        )
        # Listen for the synthetic ``_display_buzzer_mode`` callback fired
        # by ``__init__._async_options_updated`` whenever the config-entry
        # option changes (e.g. user picked forced_on in the Configure
        # dialog). The handler refreshes the entity AND kicks the enforcer
        # so the new policy takes effect immediately, not on the next
        # rsp_* ingress.
        self._coord.register_entity_callback(
            "_display_buzzer_mode", self._on_mode_option_changed
        )
        # Kick an initial evaluate so the enforcer catches up with state
        # that arrived before this entity was added.
        self._hass.loop.create_task(self._enforcer.on_ingress())

    async def async_will_remove_from_hass(self) -> None:
        self._coord.unregister_entity_callback(
            "screen_display", self.async_write_ha_state
        )
        self._coord.unregister_entity_callback(
            "_display_buzzer_mode", self._on_mode_option_changed
        )
        if self._enforcer is not None:
            self._coord.unregister_ingress_hook(self._enforcer)
            await self._enforcer.close()
            self._enforcer = None

    def _on_mode_option_changed(self) -> None:
        """Fired when the config-entry's display_buzzer_mode option
        changes (typically via the Configure dialog). Refreshes the
        entity's current_option and kicks the enforcer so the new
        policy is asserted immediately."""
        self.async_write_ha_state()
        if self._enforcer is not None:
            self._hass.loop.create_task(self._enforcer.on_ingress())

    async def async_select_option(self, option: str) -> None:
        if option not in DISPLAY_BUZZER_OPTIONS:
            raise HomeAssistantError(f"Unknown display/buzzer option: {option!r}")

        # Resolve entity-option → stored policy. Only forced_* options
        # persist a non-default policy; on/off always resolve to
        # non_enforced.
        if option == DISPLAY_BUZZER_OPTION_FORCED_ON:
            new_policy = DISPLAY_BUZZER_POLICY_FORCED_ON
        elif option == DISPLAY_BUZZER_OPTION_FORCED_OFF:
            new_policy = DISPLAY_BUZZER_POLICY_FORCED_OFF
        else:  # on / off
            new_policy = DISPLAY_BUZZER_POLICY_NON_ENFORCED

        if self._stored_policy() != new_policy:
            new_options = {
                **self._entry.options,
                CONF_DISPLAY_BUZZER_MODE: new_policy,
            }
            self._hass.config_entries.async_update_entry(
                self._entry, options=new_options
            )

        # For non-enforced picks: fire one toggle if state doesn't
        # already match the picked option. Fire-and-forget — the
        # enforcer sits this one out because policy is non_enforced.
        # Reading state here (not inside the enforcer) keeps the one-shot
        # semantics decoupled from the cooldown-based enforcement loop.
        if option in (DISPLAY_BUZZER_OPTION_ON, DISPLAY_BUZZER_OPTION_OFF):
            target = (
                DISPLAY_STATE_ON
                if option == DISPLAY_BUZZER_OPTION_ON
                else DISPLAY_STATE_OFF
            )
            observed = _read_observed_display_bits(self._coord)
            if observed is not None and observed != target:
                try:
                    await self._coord.device.toggle_display()
                except Exception:
                    _LOGGER.exception("display toggle failed (non-enforced %s)", option)

        self.async_write_ha_state()

        # Kick the enforcer. In forced_* this starts the correction loop;
        # in non-enforced it cancels any pending enforcement timers.
        if self._enforcer is not None:
            self._hass.loop.create_task(self._enforcer.on_ingress())
