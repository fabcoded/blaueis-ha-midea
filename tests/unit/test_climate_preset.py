"""Preset handling: the list is mode-aware (only conflict-free, mode-valid
presets are offered), the displayed selection is always an offered option, and
a rejected/unapplied set re-syncs the card instead of leaving a stale pick.

Real-glossary visible_in_modes anchoring these tests:
    frost_protection: [heat]            eco_mode:   [cool, auto, dry]
    turbo_mode:       [cool, heat]      sleep_mode: [cool, heat, dry, auto]
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blaueis.core.codec import load_glossary
from custom_components.blaueis_midea.climate import BlaueisMideaClimate

HOST, PORT = "127.0.0.1", 8765
PRESET_FIELDS = ["turbo_mode", "eco_mode", "sleep_mode", "frost_protection"]
COOL, HEAT = 2, 4


def _entity(mode, active=None, set_result=None):
    """mode = operating_mode raw int; active = the preset field currently on."""
    reads = {"operating_mode": mode}
    for f in PRESET_FIELDS:
        reads[f] = f == active
    coord = MagicMock()
    coord.host, coord.port = HOST, PORT
    coord.device.available_fields = {f: {} for f in PRESET_FIELDS}
    coord.device.glossary = load_glossary()
    coord.device.read = lambda name: reads.get(name)
    coord.device.set = AsyncMock(
        return_value=set_result or {"rejected": {}, "results": {}}
    )
    return BlaueisMideaClimate(coord)


def test_frost_hidden_in_cool():
    modes = _entity(COOL).preset_modes
    assert modes[0] == "none"
    assert "Frost Protection" not in modes  # heat-only
    assert {"Turbo", "ECO", "Sleep"} <= set(modes)


def test_frost_offered_eco_hidden_in_heat():
    modes = _entity(HEAT).preset_modes
    assert "Frost Protection" in modes
    assert "ECO" not in modes  # cool/auto/dry only
    assert {"Turbo", "Sleep"} <= set(modes)


def test_preset_mode_reports_active_valid():
    ent = _entity(HEAT, active="frost_protection")
    assert ent.preset_mode == "Frost Protection"
    assert ent.preset_mode in ent.preset_modes  # selected is always offered


def test_preset_mode_none_when_active_but_invalid_in_mode():
    # frost active while in cool (transient inconsistency) -> not reported, so
    # the displayed selection never falls outside the offered list.
    ent = _entity(COOL, active="frost_protection")
    assert ent.preset_mode == "none"
    assert "Frost Protection" not in ent.preset_modes


def test_preset_mode_none_when_idle():
    assert _entity(COOL).preset_mode == "none"


async def test_set_preset_clears_others_and_sets_target():
    ent = _entity(HEAT)
    await ent.async_set_preset_mode("Frost Protection")
    kwargs = ent._device.set.call_args.kwargs
    assert kwargs["frost_protection"] is True
    # mutual exclusion: every other preset explicitly cleared
    assert kwargs["turbo_mode"] is False
    assert kwargs["eco_mode"] is False
    assert kwargs["sleep_mode"] is False


async def test_rejected_preset_resyncs_card():
    # A device-layer rejection raises, but the finally must still re-push state
    # so the card reverts to the real (none) selection instead of the pick.
    ent = _entity(
        COOL,
        set_result={
            "rejected": {"frost_protection": "requires mode [4], current=2"},
            "results": {},
        },
    )
    ent.async_write_ha_state = MagicMock()
    with pytest.raises(Exception):
        await ent.async_set_preset_mode("Frost Protection")
    ent.async_write_ha_state.assert_called_once()
