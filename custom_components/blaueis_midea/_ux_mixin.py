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

from blaueis.core.gate_eval import GateVerdict, evaluate_offered


def interlock_states(device, gdef) -> dict | None:
    """Build the {field: value} map a gate's interlocks depend on, or None.

    Reads only the fields this gate's ``interlocks`` reference (usually 0), so the
    cost is bounded per availability check. Values come from ``device.read`` (the
    retained decoded value — hidden/excluded deps still resolve post-decode-retention)."""
    deps = [il.get("field") for il in ((gdef or {}).get("gate") or {}).get("interlocks") or [] if il.get("field")]
    return {d: device.read(d) for d in deps} if deps else None


def field_ux_available(coordinator, field_name: str) -> bool:
    """Evaluate the field's offer gate for `field_name` against current state.

    Returns True (visible) when:
      - the coordinator is connected AND
      - the device is fresh (recent successful ingest) AND
      - the gate evaluator offers the field: logical mode (``ux.visible_in_modes``
        / ``hardware_flag``) ∩ the capability-derived mode set (``gate.cap_mode``)
        ∩ any runtime interlocks. A field with no ``gate:`` block reduces to the
        prior ``is_field_visible`` behaviour.

    The ``device_fresh`` gate fades every UI-visible entity together
    when the AC stops responding (powered off at breaker, firmware
    crash, comms partition) without each platform needing its own
    staleness check.

    ``power_on=True`` is intentional: the power axis stays off at this site
    (power-state fading is the ``device_fresh`` guard above, unchanged), so this
    is parity with the prior mode-only gate plus the now-live capability axis.
    """
    if not coordinator.connected:
        return False
    if not coordinator.device_fresh:
        return False
    return field_gate_verdict(coordinator, field_name).offered


def field_gate_verdict(coordinator, field_name: str) -> GateVerdict:
    """Evaluate the full offer gate for `field_name` and return the verdict.

    Single source of the gate predicate — used both by ``field_ux_available``
    (which only needs ``.offered``) and by the write pre-flight
    (``_preflight.validate_or_raise``, which surfaces ``.blocked_by`` as a
    user-facing error). Keeping one call site guarantees the *availability* the
    user sees and the *write rejection* they'd get can never disagree.

    ``power_on=True`` keeps the power axis inert here, matching the offering
    sites (power-state fading is handled by ``device_fresh`` / preset gating).
    """
    dev = coordinator.device
    gdef = dev.field_gdef(field_name)
    return evaluate_offered(
        gdef,
        mode=dev.read("operating_mode"),
        power_on=True,
        active_constraints=dev.active_constraints(field_name),
        caps=dev.caps_bitmap(),
        cap_values=dev.cap_values(),
        field_states=interlock_states(dev, gdef),
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
