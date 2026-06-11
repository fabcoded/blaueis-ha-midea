"""Interlock axis wired through field_ux_available (gate engine G6).

strong_wind declares an interlock: the boost is gated off while the auxiliary
electric heater (auxiliary_heat_level) is engaged, scoped to heat/auto so the
mode-multiplexed bit isn't misread in cool. Vacuous on our unit (no PTC ⇒
auxiliary_heat_level reads 0); these drive the dependency value directly to
prove the wiring end-to-end.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from blaueis.core.codec import load_glossary, walk_fields

from custom_components.blaueis_midea._ux_mixin import field_ux_available

COOL, HEAT = 2, 4


def _coord(gdef, reads):
    coord = MagicMock()
    coord.connected = True
    coord.device_fresh = True
    coord.device.field_gdef.return_value = gdef
    coord.device.read = lambda n: reads.get(n)
    coord.device.caps_bitmap.return_value = {}
    coord.device.active_constraints.return_value = None
    return coord


def _strong_wind():
    return walk_fields(load_glossary())["strong_wind"]


def test_boost_blocked_in_heat_while_elecheat_on():
    coord = _coord(_strong_wind(), {"operating_mode": HEAT, "auxiliary_heat_level": 1})
    assert field_ux_available(coord, "strong_wind") is False


def test_boost_offered_in_heat_without_elecheat():
    # Our unit: no PTC ⇒ auxiliary_heat_level reads 0 ⇒ boost offered.
    coord = _coord(_strong_wind(), {"operating_mode": HEAT, "auxiliary_heat_level": 0})
    assert field_ux_available(coord, "strong_wind") is True


def test_boost_offered_in_cool_despite_bit_set():
    # In cool the C0:9 bit means eco, not PTC — the mode guard keeps the boost
    # offered rather than misreading the neighbour's bit as elec-heat.
    coord = _coord(_strong_wind(), {"operating_mode": COOL, "auxiliary_heat_level": 1})
    assert field_ux_available(coord, "strong_wind") is True
