"""Option A fan-mode: an off-grid fan_speed blanks the tile (no synthetic
"Custom").

Instantiates the real climate entity against a stub coordinator (conftest mocks
homeassistant.* incl. a real ClimateEntity base). __init__ reads only
coordinator.host/port and device.available_fields; read() runs lazily in the
fan_mode property. The base ClimateEntity is a bare stub here, so we assert on
``_attr_fan_modes`` (which __init__ sets) rather than the base ``fan_modes``
property; ``fan_mode`` is our own subclass property and resolves directly.
"""

from unittest.mock import MagicMock

from custom_components.blaueis_midea.climate import BlaueisMideaClimate

HOST, PORT = "127.0.0.1", 8765

# Named presets exactly as the active cap (0x10) carries them (raw/label).
# Off-grid raws (e.g. 55) have no entry here.
FAN_VALUES = {
    "ultra_low": {"raw": 1, "label": "Ultra Low"},
    "low": {"raw": 40, "label": "Low"},
    "medium": {"raw": 60, "label": "Medium"},
    "high": {"raw": 80, "label": "High"},
    "auto": {"raw": 102, "label": "Auto"},
}


def _entity(fan_speed_read):
    avail = {
        "fan_speed": {
            "active_constraints": {
                "values": FAN_VALUES,
                # Present in the cap; Option A must ignore it (no "Custom").
                "custom_value": {"label": "Custom"},
            }
        }
    }
    coord = MagicMock()
    coord.host, coord.port = HOST, PORT
    coord.device.available_fields = avail
    coord.device.read = lambda name: fan_speed_read if name == "fan_speed" else None
    return BlaueisMideaClimate(coord)


def test_custom_not_in_fan_modes():
    ent = _entity(fan_speed_read=None)
    assert "Custom" not in ent._attr_fan_modes
    assert ent._attr_fan_modes == ["Ultra Low", "Low", "Medium", "High", "Auto"]


def test_offgrid_raw_blanks_fan_mode():
    # raw 55 has no named preset -> Option A blanks the tile (None), not "Custom".
    ent = _entity(fan_speed_read=55)
    assert ent.fan_mode is None


def test_ongrid_raw_resolves_to_preset():
    ent = _entity(fan_speed_read=60)
    assert ent.fan_mode == "Medium"


def test_unknown_fan_speed_is_none():
    # None read (pre-status) -> None, no crash, no "Custom".
    ent = _entity(fan_speed_read=None)
    assert ent.fan_mode is None
