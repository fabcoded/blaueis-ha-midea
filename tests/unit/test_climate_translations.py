"""Consistency tests for the climate swing/vane translations.

The custom swing_mode / swing_horizontal_mode option slugs only render with
nice labels if (a) the entity sets a translation_key and (b) translations
carry a label for every slug under
entity.climate.<key>.state_attributes.<attr>.state.<slug>.

These tests pin the translation files against the slug source (``_swing`` /
``const``) and the glossary display labels, so adding/renaming a vane position
without updating the translation fails loudly instead of shipping a raw slug.
"""

import json
import pathlib

import pytest

from custom_components.blaueis_midea._swing import axis_options
from custom_components.blaueis_midea.const import (
    POS_LABELS,
    SWING_AXES,
    SWING_OFF,
    SWING_ON,
)

COMPONENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "custom_components"
    / "blaueis_midea"
)
TRANSLATION_KEY = "blaueis_ac"
AXIS_ATTR = {"vertical": "swing_mode", "horizontal": "swing_horizontal_mode"}
TRANSLATION_FILES = ["strings.json", "translations/en.json"]
AXES = ["vertical", "horizontal"]


def _load(name):
    return json.loads((COMPONENT / name).read_text())


def _attr_block(doc, axis):
    return doc["entity"]["climate"][TRANSLATION_KEY]["state_attributes"][AXIS_ATTR[axis]]


def _full_avail(axis):
    f = SWING_AXES[axis]
    return {f["swing"]: {}, f["angle"]: {}}


def _glossary_field(name):
    from blaueis.core.codec import load_glossary

    for fields in load_glossary()["fields"].values():
        if isinstance(fields, dict) and name in fields:
            return fields[name]
    raise AssertionError(f"{name} not in glossary")


def test_translation_key_matches_code():
    src = (COMPONENT / "climate.py").read_text()
    assert f'_attr_translation_key = "{TRANSLATION_KEY}"' in src
    for fname in TRANSLATION_FILES:
        assert TRANSLATION_KEY in _load(fname)["entity"]["climate"]


def test_strings_and_en_climate_blocks_identical():
    # strings.json is the source template; translations/en.json is what HA
    # actually loads. They must carry the same climate block.
    assert _load("strings.json")["entity"]["climate"] == (
        _load("translations/en.json")["entity"]["climate"]
    )


@pytest.mark.parametrize("fname", TRANSLATION_FILES)
@pytest.mark.parametrize("axis", AXES)
def test_every_option_slug_has_a_label(fname, axis):
    states = _attr_block(_load(fname), axis)["state"]
    expected = set(axis_options(axis, _full_avail(axis)))  # off, swing, 5 positions
    assert set(states) == expected, f"{fname} {axis}: symdiff {set(states) ^ expected}"
    assert all(isinstance(v, str) and v for v in states.values())


@pytest.mark.parametrize("axis", AXES)
def test_position_labels_match_glossary(axis):
    states = _attr_block(_load("translations/en.json"), axis)["state"]
    gloss = _glossary_field(SWING_AXES[axis]["angle"])["values"]
    raw_to_label = {v["raw"]: v["label"] for v in gloss.values()}
    for raw, slug in POS_LABELS[axis].items():
        assert states[slug] == raw_to_label[raw], (
            f"{axis} {slug}: en.json {states[slug]!r} != glossary {raw_to_label[raw]!r}"
        )


def test_swing_option_label_plain():
    e = _load("translations/en.json")
    v = _attr_block(e, "vertical")["state"]
    h = _attr_block(e, "horizontal")["state"]
    assert v[SWING_OFF] == h[SWING_OFF] == "Off"
    # Plain "Swing" on both axes — the axis is conveyed by the position labels
    # (Upper/Lower vs Left/Right) and the control, not the option text.
    assert v[SWING_ON] == h[SWING_ON] == "Swing"


def test_no_control_name_override():
    # We intentionally do NOT override the swing control names; HA core supplies
    # them (e.g. "Swing mode" / "Oszillationsart"). We translate only the option
    # VALUES — that is what fixes the raw-slug rendering (e.g. "upper_middle").
    e = _load("translations/en.json")
    assert "name" not in _attr_block(e, "vertical")
    assert "name" not in _attr_block(e, "horizontal")
