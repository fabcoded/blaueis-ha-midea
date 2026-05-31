"""Button platform — one-tap glossary ``trigger`` fields.

A glossary field with ``field_class: trigger`` is a momentary, write-only
command with no persistent state (e.g. ``filter_clean_reset``). It maps to
a Button via ``FIELD_CLASS_MAP``; pressing it issues a single ``device.set``
with the field True, which the codec encodes into one command frame.

Buttons are built from ``available_fields``, so they are capability-gated:
a trigger whose B5 capability is not advertised on the unit never appears
(e.g. ``filter_clean_reset`` is absent on a unit without ``FILTER_REMIND``).

The former 'Run field inventory scan' button moved into the Configure form
(a 'Run new scan on submit' checkbox), so it is not re-added here.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BlaueisMideaConfigEntry
from ._i18n import glossary_label_for_lang
from ._set_result import check_set_result
from ._ux_mixin import field_ux_available
from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlaueisMideaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BlaueisMideaCoordinator = entry.runtime_data
    entities: list[ButtonEntity] = [
        BlaueisMideaTriggerButton(coordinator, desc)
        for desc in coordinator.get_entities_for_platform("button")
    ]
    _LOGGER.debug("button platform: %d glossary trigger button(s)", len(entities))
    if entities:
        async_add_entities(entities)


class BlaueisMideaTriggerButton(ButtonEntity):
    """Momentary one-tap button backed by a glossary ``trigger`` field."""

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

    @property
    def device_info(self) -> DeviceInfo:
        return self._coord.device_info

    @property
    def available(self) -> bool:
        if not field_ux_available(self._coord, self._field_name):
            return False
        return bool(self._coord.device.read("power"))

    async def async_press(self) -> None:
        """Fire the trigger once. The codec builds a single command frame
        with this field set; for SET-frame triggers the builder seeds the
        byte's siblings from current status and the preflight guards stale
        siblings, so the momentary write does not clobber co-resident
        controls."""
        result = await self._coord.device.set(**{self._field_name: True})
        check_set_result(result, primary_fields={self._field_name})
