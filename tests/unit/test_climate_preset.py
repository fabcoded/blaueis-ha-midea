"""Preset handling: the list is mode-aware (only conflict-free, mode-valid
presets are offered), the displayed selection is always an offered option, and
a rejected/unapplied set re-syncs the card instead of leaving a stale pick.

Real-glossary visible_in_modes anchoring these tests:
    frost_protection: [heat]            eco_mode:   [cool, auto, dry]
    strong_wind:      [cool, heat, fan_only]   sleep_mode: [cool, heat, dry, auto]
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from blaueis.core.codec import load_glossary, walk_fields
from homeassistant.exceptions import ServiceValidationError

from custom_components.blaueis_midea.climate import BlaueisMideaClimate

HOST, PORT = "127.0.0.1", 8765
PRESET_FIELDS = ["strong_wind", "eco_mode", "sleep_mode", "frost_protection"]
COOL, HEAT = 2, 4
_FIELDS = walk_fields(load_glossary())


def _entity(mode, active=None, power=True, set_result=None, cap_values=None):
    """mode = operating_mode raw int; active = the preset field currently on.
    cap_values = {cap_id: raw} for the gate mode-fork axis (default: none applied)."""
    reads = {"operating_mode": mode, "power": power}
    for f in PRESET_FIELDS:
        reads[f] = f == active
    coord = MagicMock()
    coord.host, coord.port = HOST, PORT
    coord.hass.config.language = "en"
    coord.device.available_fields = {f: {} for f in PRESET_FIELDS}
    coord.device.glossary = load_glossary()
    coord.device.read = lambda name: reads.get(name)
    coord.device.field_gdef = lambda n: _FIELDS.get(n)
    coord.device.caps_bitmap = lambda: {}
    # No B5 caps applied in this fixture → cap-mode axis inert (a real device
    # returns None here, not a MagicMock). Without this, a field's gate.cap_mode
    # would read the auto-mock as an empty mode set and gate it off everywhere.
    coord.device.active_constraints = lambda name: None
    coord.device.cap_values = lambda: (cap_values or {})
    coord.device.set = AsyncMock(return_value=set_result or {"rejected": {}, "results": {}})
    entry = MagicMock()
    entry.options = {}
    return BlaueisMideaClimate(coord, entry)


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


def test_no_presets_offered_when_off():
    # Presets only engage while running (the device power-gates them), so a
    # powered-off unit offers nothing but 'none'.
    ent = _entity(COOL, power=False)
    assert ent.preset_modes == ["none"]
    assert ent.preset_mode == "none"


def test_active_preset_not_shown_when_off():
    # Even if a preset flag is still set, while off it's neither displayed nor
    # offered (it can't be engaged).
    ent = _entity(COOL, active="strong_wind", power=False)
    assert ent.preset_mode == "none"
    assert "Turbo" not in ent.preset_modes


async def test_set_preset_clears_others_and_sets_target():
    ent = _entity(HEAT)
    await ent.async_set_preset_mode("Frost Protection")
    kwargs = ent._device.set.call_args.kwargs
    assert kwargs["frost_protection"] is True
    # mutual exclusion: the other mode-valid presets are cleared
    assert kwargs["strong_wind"] is False
    assert kwargs["sleep_mode"] is False
    # eco is invalid in heat, so it isn't sent at all (would trip the mode gate)
    assert "eco_mode" not in kwargs


async def test_preset_blocked_preflight_raises_validation_error():
    # Picking a preset not offered in the current mode (e.g. via a service call —
    # the card already hides it) raises a reasoned ServiceValidationError BEFORE
    # any write, and still resyncs the card.
    ent = _entity(COOL)  # Frost Protection is heat-only
    ent.async_write_ha_state = MagicMock()
    with pytest.raises(ServiceValidationError) as exc:
        await ent.async_set_preset_mode("Frost Protection")
    assert exc.value.translation_key == "field_inactive_in_mode"
    ent._device.set.assert_not_awaited()  # blocked before sending
    ent.async_write_ha_state.assert_called_once()


async def test_offered_preset_device_rejection_resyncs():
    # An OFFERED preset the gate lets through but the device still rejects
    # post-send: it raises, the write WAS sent, and the finally re-pushes state.
    ent = _entity(
        HEAT,  # Frost is offered in heat → gate passes
        set_result={"rejected": {"frost_protection": "device busy"}, "results": {}},
    )
    ent.async_write_ha_state = MagicMock()
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await ent.async_set_preset_mode("Frost Protection")
    ent._device.set.assert_awaited_once()  # gate passed → write sent
    ent.async_write_ha_state.assert_called_once()


# ── G4: eco mode-fork live (special-eco cap → cool-only) ─────────────────
AUTO, DRY = 1, 3


def test_eco_offered_in_auto_without_caps():
    # No caps → fork inert → eco offered per visible_in_modes (cool/auto/dry).
    assert "ECO" in _entity(AUTO).preset_modes


def test_eco_cool_only_with_special_eco_cap():
    # Our unit: cap 0x12=1 (special eco) ⇒ eco offered in cool, hidden in auto/dry.
    assert "ECO" in _entity(COOL, cap_values={"0x12": 1}).preset_modes
    assert "ECO" not in _entity(AUTO, cap_values={"0x12": 1}).preset_modes
    assert "ECO" not in _entity(DRY, cap_values={"0x12": 1}).preset_modes


def test_eco_full_set_with_window_eco_cap():
    # Window variant: cap 0x12=2 ⇒ eco keeps cool/auto/dry.
    assert "ECO" in _entity(COOL, cap_values={"0x12": 2}).preset_modes
    assert "ECO" in _entity(AUTO, cap_values={"0x12": 2}).preset_modes
