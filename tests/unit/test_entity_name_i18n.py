"""Entity-name resolution from glossary i18n at platform construction.

Switch / select / sensor / binary_sensor each pull their display name
through ``glossary_label_for_lang`` so the user sees the localised
string without needing to populate `entity.<platform>.<field>.name`
in ``translations/<lang>.json``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.blaueis_midea.binary_sensor import BlaueisMideaBinarySensor
from custom_components.blaueis_midea.select import BlaueisMideaSelect
from custom_components.blaueis_midea.sensor import BlaueisMideaSensor
from custom_components.blaueis_midea.switch import BlaueisMideaSwitch


def _coord(gdef: dict, lang: str = "en") -> MagicMock:
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.hass.config.language = lang
    coord.device.field_gdef.return_value = gdef
    return coord


# ── label_i18n[lang] wins ────────────────────────────────────────────


def test_switch_uses_german_label_when_lang_is_de():
    gdef = {
        "label": "Eco mode",
        "label_i18n": {"de": "Eco-Modus", "en": "Eco mode"},
    }
    entry = MagicMock()
    sw = BlaueisMideaSwitch(_coord(gdef, "de"), entry, {"field_name": "eco_mode"})
    assert sw._attr_name == "Eco-Modus"


def test_select_uses_english_i18n_when_lang_missing():
    """Lang has no entry → fall through to label_i18n.en."""
    gdef = {
        "label": "Vane position",
        "label_i18n": {"en": "Vane position", "de": "Lamellenposition"},
    }
    sel = BlaueisMideaSelect(_coord(gdef, "fr"), {"field_name": "vane_position"})
    assert sel._attr_name == "Vane position"


def test_sensor_falls_back_to_legacy_label_without_i18n():
    gdef = {"label": "Indoor temperature"}
    sn = BlaueisMideaSensor(_coord(gdef), {"field_name": "indoor_temperature"})
    assert sn._attr_name == "Indoor temperature"


def test_binary_sensor_title_cases_field_name_when_no_label():
    gdef = {}
    bn = BlaueisMideaBinarySensor(_coord(gdef), {"field_name": "filter_warning"})
    assert bn._attr_name == "Filter Warning"


# ── Defensive: missing hass.config.language ──────────────────────────


def test_switch_handles_missing_language_attr():
    """Pre-test environments / older HA stubs may not expose
    `hass.config.language` — the helper should still return a sensible
    name without crashing."""
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    # Force AttributeError on language access by deleting the attribute.
    type(coord.hass.config).language = property(
        fget=lambda self: (_ for _ in ()).throw(AttributeError("language"))
    )
    coord.device.field_gdef.return_value = {
        "label_i18n": {"en": "Eco mode"},
    }
    entry = MagicMock()
    sw = BlaueisMideaSwitch(coord, entry, {"field_name": "eco_mode"})
    assert sw._attr_name == "Eco mode"
