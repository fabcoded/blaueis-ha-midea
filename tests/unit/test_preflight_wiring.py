"""Service-handler wiring tests — confirm validate_or_raise fires
before device.set() and that device.set() is NOT awaited when the
preflight raises.

Each platform handler should follow the pattern:

    validate_or_raise(coord, field_name, value)   # may raise
    result = await device.set(...)
    check_set_result(...)

These tests exercise the order: a glossary gate that fails must short-
circuit before the wire write happens, regardless of platform.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.blaueis_midea.select import BlaueisMideaSelect
from custom_components.blaueis_midea.switch import BlaueisMideaSwitch


# ── Coord factory ────────────────────────────────────────────────────


def _coord_with_glossary(
    field_name: str,
    gdef: dict,
    *,
    operating_mode_raw: int | None = None,
    extra_fields: dict | None = None,
) -> MagicMock:
    """Build a coord whose `device.glossary` includes the field plus a
    minimal `operating_mode` definition (so `valid_modes:` resolution
    works) and whose `device.status` reports the supplied raw mode."""
    fields_block: dict = {field_name: gdef}
    fields_block["operating_mode"] = {
        "description": "x", "data_type": "uint8",
        "values": {
            "cool": {"raw": 0x40, "label": "Cool"},
            "heat": {"raw": 0x80, "label": "Heat"},
        },
    }
    if extra_fields:
        fields_block.update(extra_fields)

    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.hass.config.language = "en"

    coord.device.glossary = {"fields": {"control": fields_block}}
    coord.device.field_gdef.side_effect = (
        lambda name: fields_block.get(name)
    )
    coord.device.available_fields = {field_name: {}, "operating_mode": {}}
    coord.device.read.return_value = True  # power on, etc.
    coord.device.set = AsyncMock(
        return_value={"expanded": {field_name: True}, "rejected": {}, "results": {}}
    )

    if operating_mode_raw is not None:
        coord.device.status = {
            "fields": {
                "operating_mode": {
                    "sources": {
                        "rsp_0xc0": {
                            "value": operating_mode_raw,
                            "ts": "t0",
                            "generation": "legacy",
                        }
                    }
                }
            }
        }
    else:
        coord.device.status = {"fields": {}}
    return coord


# ── Switch wiring ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_switch_turn_on_blocked_by_mode_gate_does_not_call_set():
    """eco_mode permitted only in cool; current is heat → preflight
    raises and device.set() is never awaited."""
    gdef = {
        "description": "x", "data_type": "bool",
        "label": "Eco",
        "valid_modes": ["cool"],
    }
    coord = _coord_with_glossary("eco_mode", gdef, operating_mode_raw=0x80)
    entry = MagicMock()
    sw = BlaueisMideaSwitch(coord, entry, {"field_name": "eco_mode"})

    with pytest.raises(ServiceValidationError):
        await sw.async_turn_on()

    coord.device.set.assert_not_called()


@pytest.mark.asyncio
async def test_switch_turn_on_passes_validator_calls_set():
    gdef = {
        "description": "x", "data_type": "bool",
        "label": "Eco",
        "valid_modes": ["cool"],
    }
    coord = _coord_with_glossary("eco_mode", gdef, operating_mode_raw=0x40)
    entry = MagicMock()
    sw = BlaueisMideaSwitch(coord, entry, {"field_name": "eco_mode"})

    await sw.async_turn_on()

    coord.device.set.assert_awaited_once_with(eco_mode=True)


@pytest.mark.asyncio
async def test_switch_turn_off_runs_validator_for_false():
    """Validator is called even for `False` so that a future glossary
    field that gates *off* (unlikely but possible) is honoured."""
    gdef = {
        "description": "x", "data_type": "bool",
        "label": "Eco",
        "valid_modes": ["cool"],
    }
    coord = _coord_with_glossary("eco_mode", gdef, operating_mode_raw=0x40)
    entry = MagicMock()
    sw = BlaueisMideaSwitch(coord, entry, {"field_name": "eco_mode"})

    await sw.async_turn_off()
    coord.device.set.assert_awaited_once_with(eco_mode=False)


# ── Select wiring ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_option_blocked_by_enum_gate_does_not_call_set():
    """Picking an option whose mapped raw isn't in the glossary's
    enum (e.g. drift between dropdown and glossary) is rejected by
    the validator, not by the wire write."""
    gdef = {
        "description": "x", "data_type": "uint8",
        "label": "Vane position",
        "values": {
            "left": {"raw": 1, "label": "Left"},
            "right": {"raw": 2, "label": "Right"},
        },
    }
    coord = _coord_with_glossary("vane_position", gdef)
    sel = BlaueisMideaSelect(coord, {"field_name": "vane_position"})
    # Inject a name→raw entry whose raw isn't in the glossary
    sel._name_to_raw["unmapped"] = 99
    sel._user_selectable_raws = sorted({1, 2, 99})

    with pytest.raises(ServiceValidationError) as exc:
        await sel.async_select_option("unmapped")
    assert exc.value.translation_key == "value_not_in_enum"
    coord.device.set.assert_not_called()


@pytest.mark.asyncio
async def test_select_option_passes_validator_calls_set():
    gdef = {
        "description": "x", "data_type": "uint8",
        "label": "Vane position",
        "values": {
            "left": {"raw": 1, "label": "Left"},
            "right": {"raw": 2, "label": "Right"},
        },
    }
    coord = _coord_with_glossary("vane_position", gdef)
    sel = BlaueisMideaSelect(coord, {"field_name": "vane_position"})

    await sel.async_select_option("Left")

    coord.device.set.assert_awaited_once_with(vane_position=1)
