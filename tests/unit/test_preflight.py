"""Tests for _preflight.validate_or_raise — translation_key/placeholder
shape + i18n field-label resolution + mode-token rendering.

The validator itself is exercised in libmidea/test_validation.py; here
we only verify the HA-side mapping from outcome → ServiceValidationError.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.blaueis_midea._preflight import validate_or_raise
from custom_components.blaueis_midea.const import DOMAIN


# ── Helpers ─────────────────────────────────────────────────────────


def _make_coord(
    *,
    glossary: dict,
    status: dict | None = None,
    lang: str = "en",
):
    """Build a coordinator stub the helper accepts.

    `glossary` is a flat ``{field_name: gdef}`` map; the helper consults
    `device.glossary` (the full structure with `fields.control`) AND
    `device.field_gdef(name)` (the per-field accessor). Both are stubbed.
    """
    coord = MagicMock()
    coord.hass.config.language = lang

    full_glossary = {"fields": {"control": dict(glossary)}}
    coord.device.glossary = full_glossary
    coord.device.status = status or {"fields": {}}

    def field_gdef(name: str):
        return glossary.get(name)

    coord.device.field_gdef.side_effect = field_gdef
    coord.device.set = MagicMock()
    return coord


# ── Ok pass-through ─────────────────────────────────────────────────


def test_ok_returns_silently():
    g = {"target_temperature": {
        "description": "x", "data_type": "float", "range": [16.0, 30.5],
    }}
    coord = _make_coord(glossary=g)
    # Does not raise
    validate_or_raise(coord, "target_temperature", 22.0)


def test_field_unknown_silently_passes_through():
    """FieldUnknown isn't user error — entity wiring bug. Helper lets
    the wire write proceed; the wire write will fail loudly."""
    g = {}
    coord = _make_coord(glossary=g)
    validate_or_raise(coord, "totally_unknown", 42)


# ── OutOfRange ──────────────────────────────────────────────────────


def test_out_of_range_raises_with_translation_keys():
    g = {"target_temperature": {
        "description": "x", "data_type": "float", "range": [16.0, 30.5],
        "label": "Target temperature",
    }}
    coord = _make_coord(glossary=g)
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "target_temperature", 99.0)
    assert exc.value.translation_domain == DOMAIN
    assert exc.value.translation_key == "value_out_of_range"
    p = exc.value.translation_placeholders
    assert p["got"] == "99.0"
    assert p["min"] == "16.0"
    assert p["max"] == "30.5"
    assert p["field"] == "Target temperature"


def test_out_of_range_uses_localised_label_when_present():
    g = {"target_temperature": {
        "description": "x", "data_type": "float", "range": [16.0, 30.5],
        "label": "Target temperature",
        "label_i18n": {"de": "Zieltemperatur", "en": "Target temperature"},
    }}
    coord = _make_coord(glossary=g, lang="de")
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "target_temperature", 99.0)
    assert exc.value.translation_placeholders["field"] == "Zieltemperatur"


def test_out_of_range_falls_back_to_title_case_when_no_label():
    g = {"target_temperature": {
        "description": "x", "data_type": "float", "range": [16.0, 30.5],
    }}
    coord = _make_coord(glossary=g)
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "target_temperature", 99.0)
    assert exc.value.translation_placeholders["field"] == "Target Temperature"


# ── NotInEnum ───────────────────────────────────────────────────────


def test_not_in_enum_raises_with_allowed_list():
    g = {"operating_mode": {
        "description": "x", "data_type": "uint8",
        "label": "Mode",
        "values": {
            "cool": {"raw": 0x40},
            "heat": {"raw": 0x80},
        },
    }}
    coord = _make_coord(glossary=g)
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "operating_mode", 0x99)
    assert exc.value.translation_key == "value_not_in_enum"
    p = exc.value.translation_placeholders
    assert p["got"] == "153"
    # Allowed list rendered as comma-separated string
    assert "64" in p["allowed"] and "128" in p["allowed"]
    assert p["field"] == "Mode"


# ── ModeDisallowed ──────────────────────────────────────────────────


def _glossary_with_operating_mode() -> dict:
    """Helper — minimal operating_mode definition so token rendering works."""
    return {
        "operating_mode": {
            "description": "x", "data_type": "uint8",
            "values": {
                "cool": {"raw": 0x40, "label": "Cool"},
                "heat": {
                    "raw": 0x80,
                    "label": "Heat",
                    "label_i18n": {"de": "Heizen", "en": "Heat"},
                },
            },
        },
    }


def _status_with_mode(raw: int) -> dict:
    return {
        "fields": {
            "operating_mode": {
                "sources": {
                    "rsp_0xc0": {"value": raw, "ts": "t0", "generation": "legacy"}
                }
            }
        }
    }


def test_mode_disallowed_raises_with_field_and_mode():
    g = _glossary_with_operating_mode()
    g["eco_mode"] = {
        "description": "x", "data_type": "bool",
        "label": "Eco",
        "valid_modes": ["cool"],
    }
    coord = _make_coord(glossary=g, status=_status_with_mode(0x80))
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "eco_mode", True)
    assert exc.value.translation_key == "field_inactive_in_mode"
    p = exc.value.translation_placeholders
    assert p["field"] == "Eco"
    assert p["mode"] == "Heat"


def test_mode_disallowed_renders_localised_mode_label():
    g = _glossary_with_operating_mode()
    g["eco_mode"] = {
        "description": "x", "data_type": "bool",
        "label": "Eco",
        "valid_modes": ["cool"],
    }
    coord = _make_coord(glossary=g, status=_status_with_mode(0x80), lang="de")
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "eco_mode", True)
    assert exc.value.translation_placeholders["mode"] == "Heizen"


def test_mode_disallowed_unknown_token_falls_back_to_title_case():
    """If the validator hands back a token the operating_mode block
    doesn't define (defensive — shouldn't happen in practice), the
    helper must still produce a non-empty placeholder."""
    g = _glossary_with_operating_mode()
    # Add an extra raw with a token that has no label
    g["operating_mode"]["values"]["weird_mode"] = {"raw": 0x99}
    g["eco_mode"] = {
        "description": "x", "data_type": "bool",
        "label": "Eco",
        "valid_modes": ["cool"],
    }
    coord = _make_coord(glossary=g, status=_status_with_mode(0x99))
    with pytest.raises(ServiceValidationError) as exc:
        validate_or_raise(coord, "eco_mode", True)
    assert exc.value.translation_placeholders["mode"] == "Weird Mode"
