"""Tests for _ux_mixin.field_writable_in_current_mode — the entity-level
companion to the pre-flight validator's mode gate.

Same gate semantics as ``validate_set``'s ``valid_modes:`` check, but
returns a boolean for the ``available`` property to consume.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.blaueis_midea._ux_mixin import (
    field_writable_in_current_mode,
)


def _coord(
    *,
    field_name: str,
    field_def: dict,
    operating_mode_raw: int | str | None = None,
    operating_mode_def: dict | None = None,
) -> MagicMock:
    """Build a coordinator stub. ``operating_mode_def`` defaults to a
    minimal cool/heat values block so tokens resolve."""
    if operating_mode_def is None:
        operating_mode_def = {
            "data_type": "uint8",
            "values": {
                "cool": {"raw": 2},
                "heat": {"raw": 4},
            },
        }
    fields = {field_name: field_def, "operating_mode": operating_mode_def}

    coord = MagicMock()
    coord.device.field_gdef.side_effect = lambda name: fields.get(name)
    coord.device.read.side_effect = lambda name: (
        operating_mode_raw if name == "operating_mode" else None
    )
    return coord


# ── Permissive defaults ──────────────────────────────────────────────


def test_field_with_no_glossary_entry_is_writable():
    coord = MagicMock()
    coord.device.field_gdef.return_value = None
    assert field_writable_in_current_mode(coord, "anything") is True


def test_field_without_valid_modes_is_writable():
    coord = _coord(
        field_name="x",
        field_def={"data_type": "bool"},
        operating_mode_raw=4,  # heat
    )
    assert field_writable_in_current_mode(coord, "x") is True


def test_unknown_operating_mode_fails_open():
    """No reading yet — entity stays writable; the validator will
    catch the actual write if mode is later resolved."""
    coord = _coord(
        field_name="eco_mode",
        field_def={"data_type": "bool", "valid_modes": ["cool"]},
        operating_mode_raw=None,
    )
    assert field_writable_in_current_mode(coord, "eco_mode") is True


def test_unmapped_raw_byte_fails_open():
    """Raw byte not in operating_mode.values → token resolution returns
    None, gate stays open (matches validator's behaviour)."""
    coord = _coord(
        field_name="eco_mode",
        field_def={"data_type": "bool", "valid_modes": ["cool"]},
        operating_mode_raw=0xFE,
    )
    assert field_writable_in_current_mode(coord, "eco_mode") is True


# ── Mode token in / out of valid_modes ───────────────────────────────


def test_writable_when_current_mode_listed():
    coord = _coord(
        field_name="eco_mode",
        field_def={"data_type": "bool", "valid_modes": ["cool", "auto"]},
        operating_mode_raw=2,  # cool
    )
    assert field_writable_in_current_mode(coord, "eco_mode") is True


def test_not_writable_when_current_mode_not_listed():
    coord = _coord(
        field_name="eco_mode",
        field_def={"data_type": "bool", "valid_modes": ["cool"]},
        operating_mode_raw=4,  # heat
    )
    assert field_writable_in_current_mode(coord, "eco_mode") is False


def test_string_operating_mode_compared_directly():
    """Older code paths sometimes return the token string from read()."""
    coord = _coord(
        field_name="eco_mode",
        field_def={"data_type": "bool", "valid_modes": ["cool"]},
        operating_mode_raw="cool",
    )
    assert field_writable_in_current_mode(coord, "eco_mode") is True


def test_string_operating_mode_disallowed():
    coord = _coord(
        field_name="eco_mode",
        field_def={"data_type": "bool", "valid_modes": ["cool"]},
        operating_mode_raw="heat",
    )
    assert field_writable_in_current_mode(coord, "eco_mode") is False
