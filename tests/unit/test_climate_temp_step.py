"""Temperature step + per-mode bounds are LIVE properties.

``target_temperature_step`` is driven by the ``half_degree_steps`` option
(default on → 0.5 °C), NOT the B5 ``half_deg`` cap (which reads 0 on units
whose firmware nonetheless honors the half bit). ``min_temp`` / ``max_temp``
come from the cap's per-mode ``active_constraints['by_mode']`` for the current
operating mode, falling back to 16–30 when absent.
"""

from unittest.mock import MagicMock

from custom_components.blaueis_midea.climate import BlaueisMideaClimate
from custom_components.blaueis_midea.const import CONF_HALF_DEGREE_STEPS


def _entity(by_mode=None, mode_raw=2, options=None):
    coord = MagicMock()
    coord.host, coord.port = "127.0.0.1", 8765
    coord.device.available_fields = {}
    ac = {"by_mode": by_mode} if by_mode is not None else {}
    coord.device.active_constraints = lambda name: ac if name == "target_temperature" else None
    coord.device.read = lambda name: mode_raw if name == "operating_mode" else None
    entry = MagicMock()
    entry.options = options or {}
    return BlaueisMideaClimate(coord, entry)


def test_step_defaults_to_half_degree():
    assert _entity().target_temperature_step == 0.5


def test_step_whole_degree_when_option_off():
    assert _entity(options={CONF_HALF_DEGREE_STEPS: False}).target_temperature_step == 1.0


def test_step_half_degree_when_option_on():
    assert _entity(options={CONF_HALF_DEGREE_STEPS: True}).target_temperature_step == 0.5


def test_bounds_from_current_mode_by_mode():
    ent = _entity(by_mode={"cool": {"valid_range": [17.0, 29.0]}}, mode_raw=2)  # cool
    assert ent.min_temp == 17.0
    assert ent.max_temp == 29.0


def test_bounds_track_mode_switch():
    by_mode = {"cool": {"valid_range": [17.0, 29.0]}, "heat": {"valid_range": [16.0, 31.0]}}
    assert _entity(by_mode=by_mode, mode_raw=4).max_temp == 31.0  # heat


def test_bounds_fallback_when_mode_has_no_entry():
    ent = _entity(by_mode={"cool": {"valid_range": [17.0, 29.0]}}, mode_raw=4)  # heat absent
    assert (ent.min_temp, ent.max_temp) == (16.0, 30.0)


def test_bounds_fallback_when_cap_absent():
    ent = _entity(by_mode=None)
    assert (ent.min_temp, ent.max_temp) == (16.0, 30.0)
