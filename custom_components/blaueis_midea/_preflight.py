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

from homeassistant.exceptions import ServiceValidationError

from blaueis.core.validation import (
    ModeDisallowed,
    NotInEnum,
    Ok,
    OutOfRange,
    validate_set,
)

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


def validate_or_raise(
    coord: BlaueisMideaCoordinator,
    field_name: str,
    value: Any,
) -> None:
    """Run the validator; raise ``ServiceValidationError`` on non-Ok.

    The validator's outcome shape maps onto translation keys declared in
    ``translations/<lang>.json``:

    - :class:`OutOfRange`    → ``value_out_of_range``
    - :class:`NotInEnum`     → ``value_not_in_enum``
    - :class:`ModeDisallowed`→ ``field_inactive_in_mode``

    :class:`FieldUnknown` is silently passed through — service handlers
    only call this for fields they own (entity → field_name binding is
    set up at platform setup), so a FieldUnknown there means a glossary
    bug, not a user error. The downstream wire write will fail loudly.

    Booleans are not range-checked (handled inside the validator).
    """
    outcome = validate_set(
        field_name, value, coord.device.status, coord.device.glossary
    )
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
