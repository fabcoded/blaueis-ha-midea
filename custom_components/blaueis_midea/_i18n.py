"""Glossary-driven i18n resolution for entity names and placeholders.

Per the architecture decision: per-field strings (label, description,
state-enum labels) live in the glossary as ``label_i18n: {<lang>:
<string>}`` / ``description_i18n: ...`` / per-state ``label_i18n``;
field-agnostic chrome (config-flow titles, exception templates) stays
in ``translations/<lang>.json``. The integration resolves field-level
strings at the consumer site rather than mutating HA's translation
table.

This helper handles the resolution chain for entity names and for
placeholders fed into ``ServiceValidationError(translation_placeholders=)``.

Resolution chain — ``label_i18n`` example:

1. ``glossary[field].label_i18n[<lang>]`` (exact language match).
2. ``glossary[field].label_i18n.en`` (declared English fallback).
3. ``glossary[field].label`` (legacy field-level English).
4. Auto-derived title-case of the field key.

Same shape for ``description_i18n`` / ``description``.
"""

from __future__ import annotations


def glossary_label_for_lang(
    field_def: dict | None, field_name: str, lang: str | None
) -> str:
    """Return the user-facing label for ``field_name`` in ``lang``.

    Walks the four-step fallback chain documented at module level.
    Always returns a non-empty string — auto-derived title-case is the
    final guaranteed fallback. Pass ``field_def=None`` (or an empty
    dict) when the field has no glossary entry; the helper falls
    straight to the title-case derivation.
    """
    if isinstance(field_def, dict):
        i18n = field_def.get("label_i18n") or {}
        if isinstance(i18n, dict):
            if lang and isinstance(i18n.get(lang), str) and i18n[lang]:
                return i18n[lang]
            if isinstance(i18n.get("en"), str) and i18n["en"]:
                return i18n["en"]
        legacy = field_def.get("label")
        if isinstance(legacy, str) and legacy:
            return legacy
    return field_name.replace("_", " ").title()


def glossary_description_for_lang(
    field_def: dict | None, field_name: str, lang: str | None
) -> str | None:
    """Return the field's description in ``lang``, or None when no
    description is declared. Mirrors ``glossary_label_for_lang`` shape
    but returns ``None`` instead of synthesising a fallback — entities
    don't auto-generate descriptions.
    """
    if not isinstance(field_def, dict):
        return None
    i18n = field_def.get("description_i18n") or {}
    if isinstance(i18n, dict):
        if lang and isinstance(i18n.get(lang), str) and i18n[lang]:
            return i18n[lang]
        if isinstance(i18n.get("en"), str) and i18n["en"]:
            return i18n["en"]
    legacy = field_def.get("description")
    if isinstance(legacy, str) and legacy:
        return legacy
    return None
