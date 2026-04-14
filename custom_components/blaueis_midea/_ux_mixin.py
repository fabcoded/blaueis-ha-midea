"""Shared UX-mask evaluator for Blaueis entities.

Exposes one helper: ``field_ux_available(coordinator, field_name)`` returns
True/False based on ``ux.visible_in_modes`` and ``ux.hardware_flag`` in the
glossary. Used by the ``available`` property of every per-field entity
class. Keeps the pattern out of each class body so adding a new platform
(e.g. ``number.py``) doesn't accidentally skip the gate.
"""
from __future__ import annotations

from blaueis.core.ux_gating import is_field_visible


def field_ux_available(coordinator, field_name: str) -> bool:
    """Evaluate the glossary ``ux`` block for `field_name` against current state.

    Returns True (visible) when:
      - the coordinator is connected AND
      - the field has no ``ux`` block (permissive default) OR
      - the current mode is in ``ux.visible_in_modes`` (when that key exists) AND
      - any ``ux.hardware_flag`` resolves truthy via the device's caps bitmap.
    """
    if not coordinator.connected:
        return False
    gdef = coordinator.device.field_gdef(field_name)
    return is_field_visible(
        gdef,
        current_mode=coordinator.device.read("operating_mode"),
        caps=coordinator.device.caps_bitmap(),
    )
