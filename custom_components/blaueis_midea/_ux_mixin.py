"""Shared UX-mask evaluator for Blaueis entities.

Two helpers:

- ``field_ux_available(coordinator, field_name)`` — evaluates
  ``ux.visible_in_modes`` and ``ux.hardware_flag`` in the glossary
  (UI-visibility rules).

- ``field_writable_in_current_mode(coordinator, field_name)`` —
  evaluates the field-root ``valid_modes:`` gate against the current
  ``operating_mode``. This is the same gate the pre-flight validator
  would fail on a write attempt; surfacing it via ``available`` keeps
  the user from seeing a control that cannot be set right now.

Used by the ``available`` property of every per-field entity class.
Keeps the pattern out of each class body so adding a new platform
(e.g. ``number.py``) doesn't accidentally skip the gate.
"""

from __future__ import annotations

from blaueis.core.ux_gating import is_field_visible


def field_ux_available(coordinator, field_name: str) -> bool:
    """Evaluate the glossary ``ux`` block for `field_name` against current state.

    Returns True (visible) when:
      - the coordinator is connected AND
      - the device is fresh (recent successful ingest) AND
      - the field has no ``ux`` block (permissive default) OR
      - the current mode is in ``ux.visible_in_modes`` (when that key exists) AND
      - any ``ux.hardware_flag`` resolves truthy via the device's caps bitmap.

    The ``device_fresh`` gate fades every UI-visible entity together
    when the AC stops responding (powered off at breaker, firmware
    crash, comms partition) without each platform needing its own
    staleness check.
    """
    if not coordinator.connected:
        return False
    if not coordinator.device_fresh:
        return False
    gdef = coordinator.device.field_gdef(field_name)
    return is_field_visible(
        gdef,
        current_mode=coordinator.device.read("operating_mode"),
        caps=coordinator.device.caps_bitmap(),
    )


def field_writable_in_current_mode(coordinator, field_name: str) -> bool:
    """Return True unless ``valid_modes:`` is declared and current mode is excluded.

    Resolution chain:

    1. Field has no glossary entry, or no ``valid_modes:`` key →
       writable (permissive default — no opt-in declared).
    2. Operating mode unknown (status not yet populated, or raw byte
       not in the glossary's operating_mode values block) → fail open;
       the validator can't disagree with what it can't see, and a
       transient pre-poll state shouldn't grey out the entity.
    3. Operating-mode token is in ``valid_modes`` → writable.
    4. Otherwise → not writable.

    Mirrors :func:`blaueis.core.validation.validate_set`'s mode gate so
    that ``available`` and ``ServiceValidationError`` agree about what
    can/cannot be set right now.
    """
    gdef = coordinator.device.field_gdef(field_name)
    if not isinstance(gdef, dict):
        return True
    valid_modes = gdef.get("valid_modes")
    if not valid_modes or not isinstance(valid_modes, list):
        return True

    raw = coordinator.device.read("operating_mode")
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw in valid_modes

    op_def = coordinator.device.field_gdef("operating_mode") or {}
    values_block = op_def.get("values") or {}
    token: str | None = None
    for tok, vdef in values_block.items():
        if isinstance(vdef, dict) and vdef.get("raw") == raw:
            token = tok
            break
    if token is None:
        return True
    return token in valid_modes
