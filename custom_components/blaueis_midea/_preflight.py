"""Pre-flight validation for HA service calls.

Wraps :func:`blaueis.core.validation.validate_set` and translates a
non-Ok outcome into a :class:`ServiceValidationError` whose
``translation_domain``/``translation_key`` resolves through the
integration's ``translations/<lang>.json`` ``exceptions`` block.

Per-field labels and (where present) operating-mode tokens are routed
through :mod:`._i18n` so the user sees the same string the entity carries,
not the raw glossary key.
"""

from __future__ import annotations

from typing import Any

from blaueis.core.validation import (
    ModeDisallowed,
    NotInEnum,
    Ok,
    OutOfRange,
    validate_set,
)
from homeassistant.exceptions import ServiceValidationError

from ._i18n import glossary_label_for_lang
from .const import DOMAIN
from .coordinator import BlaueisMideaCoordinator


def _field_label(coord: BlaueisMideaCoordinator, field_name: str) -> str:
    """Return the user-facing label for ``field_name`` in HA's language."""
    gdef = coord.device.field_gdef(field_name)
    lang = getattr(coord.hass.config, "language", None)
    return glossary_label_for_lang(gdef, field_name, lang)


def _mode_label(coord: BlaueisMideaCoordinator, token: str | None) -> str:
    """Render an operating_mode token (``cool``, ``heat``, ...) into a label.

    Falls through the same i18n chain as field labels by treating each
    token as the leaf of the ``operating_mode.values`` block. Returns
    ``"unknown"`` on a missing/empty token (the validator skips the gate
    in that case, but defensive rendering keeps the placeholder string
    non-empty).
    """
    if not token:
        return "unknown"
    op_def = coord.device.field_gdef("operating_mode") or {}
    values = op_def.get("values") or {}
    vdef = values.get(token) if isinstance(values, dict) else None
    if isinstance(vdef, dict):
        lang = getattr(coord.hass.config, "language", None)
        i18n = vdef.get("label_i18n") or {}
        if isinstance(i18n, dict):
            if lang and isinstance(i18n.get(lang), str) and i18n[lang]:
                return i18n[lang]
            if isinstance(i18n.get("en"), str) and i18n["en"]:
                return i18n["en"]
        legacy = vdef.get("label")
        if isinstance(legacy, str) and legacy:
            return legacy
    return token.replace("_", " ").title()


def _current_mode_label(coord: BlaueisMideaCoordinator) -> str:
    """Label for the device's current operating mode (raw byte → token → label)."""
    raw = coord.device.read("operating_mode")
    if raw is None:
        return "unknown"
    if isinstance(raw, str):
        return _mode_label(coord, raw)
    op_def = coord.device.field_gdef("operating_mode") or {}
    for token, vdef in (op_def.get("values") or {}).items():
        if isinstance(vdef, dict) and vdef.get("raw") == raw:
            return _mode_label(coord, token)
    return str(raw)


def _raise_gate_block(coord: BlaueisMideaCoordinator, field_name: str, blocked_by: list[str]) -> None:
    """Translate an offer-gate ``blocked_by`` into a ServiceValidationError.

    Mode / capability-mode blocks read as "not active in this mode"; an interlock
    block names the conflicting feature. Same predicate as entity availability
    (``field_gate_verdict``), so the error a write raises matches the greying.
    """
    label = _field_label(coord, field_name)
    interlock = next((b for b in blocked_by if b.startswith("interlock:")), None)
    mode_blocked = any(b == "mode" or b.startswith("cap_mode:") for b in blocked_by)

    if interlock and not mode_blocked:
        blocker_field = interlock.split(":", 1)[1]
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="field_blocked_by_feature",
            translation_placeholders={
                "field": label,
                "blocker": _field_label(coord, blocker_field),
            },
        )
    # mode / cap_mode (or any other axis) → wrong operating mode
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="field_inactive_in_mode",
        translation_placeholders={
            "field": label,
            "mode": _current_mode_label(coord),
        },
    )


def validate_or_raise(
    coord: BlaueisMideaCoordinator,
    field_name: str,
    value: Any,
) -> None:
    """Run the validator; raise ``ServiceValidationError`` on non-Ok.

    Two layers, both raising ``ServiceValidationError`` with a translation key:

    1. **Offer gate** (``field_gate_verdict`` — the same predicate that drives
       entity availability): blocks a write the field isn't offered for right now.
       - mode / capability-mode → ``field_inactive_in_mode``
       - runtime interlock      → ``field_blocked_by_feature``
       Running this first means the *write rejection* a user gets always matches
       the *greying* they see, and a service call / automation can't slip a write
       past an interlock or capability-mode restriction (which the lib mode-fence
       alone would not catch).
    2. **Value validator** (``validate_set``):
       - :class:`OutOfRange`    → ``value_out_of_range``
       - :class:`NotInEnum`     → ``value_not_in_enum``
       - :class:`ModeDisallowed`→ ``field_inactive_in_mode``

    :class:`FieldUnknown` is silently passed through — service handlers
    only call this for fields they own (entity → field_name binding is
    set up at platform setup), so a FieldUnknown there means a glossary
    bug, not a user error. The downstream wire write will fail loudly.

    Booleans are not range-checked (handled inside the validator).
    """
    # Lazy import: _ux_mixin pulls the vendored gate evaluator; importing it at
    # module level here loads that chain too early during test collection and trips
    # the select.py / stdlib-select shadow. At call time everything is loaded.
    from ._ux_mixin import field_gate_verdict

    verdict = field_gate_verdict(coord, field_name)
    if not verdict.offered:
        _raise_gate_block(coord, field_name, verdict.blocked_by)

    outcome = validate_set(field_name, value, coord.device.status, coord.device.glossary)
    if isinstance(outcome, Ok):
        return

    label = _field_label(coord, field_name)

    if isinstance(outcome, OutOfRange):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="value_out_of_range",
            translation_placeholders={
                "got": str(outcome.value),
                "min": str(outcome.min_value),
                "max": str(outcome.max_value),
                "field": label,
            },
        )
    if isinstance(outcome, NotInEnum):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="value_not_in_enum",
            translation_placeholders={
                "got": str(outcome.value),
                "allowed": ", ".join(str(a) for a in outcome.allowed),
                "field": label,
            },
        )
    if isinstance(outcome, ModeDisallowed):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="field_inactive_in_mode",
            translation_placeholders={
                "field": label,
                "mode": _mode_label(coord, outcome.current_mode),
            },
        )
    # FieldUnknown / future outcomes — let the wire write decide.
