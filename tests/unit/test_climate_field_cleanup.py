"""Registry-cleanup tests for climate-exclusive fields.

The four louver fields stay in ``available_fields`` (the climate entity reads
them for swing_mode / swing_horizontal_mode), but their *standalone* selects
must be removed — they're folded into the climate dropdowns. This is the gap
``_cleanup_orphaned_field_entities`` closes via ``CLIMATE_EXCLUSIVE_FIELDS``.

These tests drive the cleanup against a fake entity registry. ``async_get`` is
set directly on the conftest's mocked ``homeassistant.helpers`` module so the
function's ``from homeassistant.helpers import entity_registry`` resolves to
the same object we patched.
"""

import sys
from unittest.mock import MagicMock

from custom_components.blaueis_midea import _REMOVED_FIELDS, _cleanup_orphaned_field_entities
from custom_components.blaueis_midea.const import CLIMATE_EXCLUSIVE_FIELDS

HOST, PORT = "127.0.0.1", 8765
ENTRY_ID = "entry1"
LOUVER_FIELDS = [
    "louver_swing_vertical",
    "louver_swing_horizontal",
    "louver_swing_angle_ud_enum",
    "louver_swing_angle_lr_enum",
]
# A real glossary field that is NOT climate-exclusive (keeps its own entity).
NONEXCLUSIVE_FIELD = "indoor_temperature"


class _RegEntry:
    def __init__(self, entity_id, unique_id, config_entry_id=ENTRY_ID):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.config_entry_id = config_entry_id


class _FakeRegistry:
    def __init__(self, entries):
        self.entities = {e.entity_id: e for e in entries}
        self.removed = []

    def async_remove(self, entity_id):
        self.removed.append(entity_id)
        self.entities.pop(entity_id, None)


def _uid(suffix, host=HOST, port=PORT):
    return f"{host}_{port}_{suffix}"


def _coord(available, sliders=()):
    """``sliders``: fields whose active cap carries a ``slider:`` block —
    the condition the number platform builds a ``<field>_slider`` on."""
    from blaueis.core.codec import load_glossary

    c = MagicMock()
    c.host, c.port = HOST, PORT
    c.device.glossary = load_glossary()
    c.device.available_fields = {
        f: ({"active_constraints": {"slider": {"range": [1, 100]}}} if f in sliders else {}) for f in available
    }
    return c


def _entry():
    e = MagicMock()
    e.entry_id = ENTRY_ID
    return e


def _run(registry, coord):
    # The function does `from homeassistant.helpers import entity_registry`,
    # which getattrs the conftest's mocked `homeassistant.helpers` module —
    # set async_get on that exact object so the function sees our registry.
    sys.modules["homeassistant.helpers"].entity_registry.async_get = lambda hass: registry
    _cleanup_orphaned_field_entities(MagicMock(), _entry(), coord)


def test_setup_assumptions():
    """Guard the fixtures: louvers ARE exclusive, the control field is not,
    and all are real glossary fields the sweep can see."""
    from blaueis.core.codec import load_glossary, walk_fields

    names = set(walk_fields(load_glossary()).keys())
    for f in LOUVER_FIELDS:
        assert f in CLIMATE_EXCLUSIVE_FIELDS and f in names
    assert NONEXCLUSIVE_FIELD not in CLIMATE_EXCLUSIVE_FIELDS
    assert NONEXCLUSIVE_FIELD in names


def test_louver_selects_removed_even_though_available():
    # All four louver fields ARE advertised (climate reads them), yet their
    # standalone selects must still be removed.
    available = LOUVER_FIELDS + [NONEXCLUSIVE_FIELD]
    louver_entries = [_RegEntry(f"select.blaueis_{f}", _uid(f)) for f in LOUVER_FIELDS]
    keep = _RegEntry(f"sensor.blaueis_{NONEXCLUSIVE_FIELD}", _uid(NONEXCLUSIVE_FIELD))
    reg = _FakeRegistry(louver_entries + [keep])

    _run(reg, _coord(available))

    for f in LOUVER_FIELDS:
        assert f"select.blaueis_{f}" in reg.removed
    # The unrelated, still-available field keeps its standalone entity.
    assert f"sensor.blaueis_{NONEXCLUSIVE_FIELD}" not in reg.removed
    assert f"sensor.blaueis_{NONEXCLUSIVE_FIELD}" in reg.entities


def test_rerun_is_noop():
    available = LOUVER_FIELDS + ["power"]
    reg = _FakeRegistry([_RegEntry(f"select.x_{f}", _uid(f)) for f in LOUVER_FIELDS])
    coord = _coord(available)

    _run(reg, coord)
    assert len(reg.removed) == 4

    before = list(reg.removed)
    _run(reg, coord)  # nothing left to remove
    assert reg.removed == before


def test_other_config_entry_untouched():
    reg = _FakeRegistry(
        [
            _RegEntry(
                "select.other_louver",
                _uid("louver_swing_vertical"),
                config_entry_id="other-entry",
            )
        ]
    )
    _run(reg, _coord(LOUVER_FIELDS))
    assert reg.removed == []


def test_foreign_prefix_untouched():
    reg = _FakeRegistry([_RegEntry("select.foreign", _uid("louver_swing_vertical", host="10.0.0.9"))])
    _run(reg, _coord(LOUVER_FIELDS))
    assert reg.removed == []


def test_orphaned_nonexclusive_field_removed_when_absent():
    # Non-exclusive field that dropped out of available_fields -> removed
    # (pre-existing orphan branch, unaffected by the climate-exclusive add).
    reg = _FakeRegistry([_RegEntry("sensor.it", _uid(NONEXCLUSIVE_FIELD))])
    _run(reg, _coord(["power"]))  # NONEXCLUSIVE_FIELD not available
    assert "sensor.it" in reg.removed


def test_available_nonexclusive_field_kept():
    reg = _FakeRegistry([_RegEntry("sensor.it", _uid(NONEXCLUSIVE_FIELD))])
    _run(reg, _coord([NONEXCLUSIVE_FIELD]))  # available
    assert reg.removed == []


# ── Deleted glossary fields (pass 2) ──────────────────────────────────

REMOVED_FIELD = "run_status"


def test_removed_field_is_not_a_glossary_field():
    """Guard the fixture: the listed field really is gone from the glossary,
    so pass 1 cannot see it — which is exactly the gap pass 2 closes."""
    from blaueis.core.codec import load_glossary, walk_fields

    assert REMOVED_FIELD in _REMOVED_FIELDS
    assert REMOVED_FIELD not in set(walk_fields(load_glossary()).keys())


def test_removed_field_entity_swept():
    reg = _FakeRegistry(
        [
            _RegEntry("sensor.rs", _uid(REMOVED_FIELD)),
            _RegEntry("number.rs_slider", _uid(f"{REMOVED_FIELD}_slider")),
            _RegEntry("sensor.it", _uid(NONEXCLUSIVE_FIELD)),
        ]
    )
    _run(reg, _coord([NONEXCLUSIVE_FIELD, "power"]))
    assert "sensor.rs" in reg.removed
    assert "number.rs_slider" in reg.removed
    assert "sensor.it" not in reg.removed


def test_unknown_synthetic_suffix_still_left_alone():
    # A non-field suffix that is neither a removed field nor in the synthetic
    # catalog (climate, gw_* stats, <field>_slider) must survive the sweep.
    reg = _FakeRegistry(
        [
            _RegEntry("climate.ac", _uid("climate")),
            _RegEntry("sensor.gw_cpu", _uid("gw_cpu_percent")),
            _RegEntry("number.fan", _uid("fan_speed_slider")),
        ]
    )
    _run(reg, _coord(["power", "fan_speed"], sliders=["fan_speed"]))
    assert reg.removed == []


# ── `<field>_slider` numbers follow their base field (pass 1) ─────────

LOUVER_ANGLE = "louver_swing_angle_ud_enum"


def test_slider_fixture_assumptions():
    """fan_speed is climate-exclusive yet keeps an intentional slider; the
    non-exclusive field is not; both are real glossary fields."""
    from blaueis.core.codec import load_glossary, walk_fields

    names = set(walk_fields(load_glossary()).keys())
    assert "fan_speed" in CLIMATE_EXCLUSIVE_FIELDS and "fan_speed" in names
    assert LOUVER_ANGLE in CLIMATE_EXCLUSIVE_FIELDS
    assert f"{NONEXCLUSIVE_FIELD}_slider" not in names


def test_slider_of_unavailable_field_removed():
    reg = _FakeRegistry(
        [
            _RegEntry("number.it_slider", _uid(f"{NONEXCLUSIVE_FIELD}_slider")),
            _RegEntry("number.fan_slider", _uid("fan_speed_slider")),
        ]
    )
    _run(reg, _coord(["power"]))  # neither base field available
    assert sorted(reg.removed) == ["number.fan_slider", "number.it_slider"]


def test_slider_of_available_nonexclusive_field_kept():
    reg = _FakeRegistry([_RegEntry("number.it_slider", _uid(f"{NONEXCLUSIVE_FIELD}_slider"))])
    _run(reg, _coord([NONEXCLUSIVE_FIELD], sliders=[NONEXCLUSIVE_FIELD]))
    assert reg.removed == []


def test_slider_of_available_nonexclusive_field_without_slider_block_removed():
    # The number platform builds a slider only where the cap has a slider
    # block, whatever the field's climate exclusivity — without one, nothing
    # would rebuild the number.
    reg = _FakeRegistry([_RegEntry("number.it_slider", _uid(f"{NONEXCLUSIVE_FIELD}_slider"))])
    _run(reg, _coord([NONEXCLUSIVE_FIELD]))
    assert reg.removed == ["number.it_slider"]


def test_slider_of_climate_exclusive_field_without_slider_block_removed():
    # The retired louver-angle sliders: field still available (climate reads
    # it), cap no longer carries a slider, so nothing rebuilds the number.
    reg = _FakeRegistry([_RegEntry("number.vane_slider", _uid(f"{LOUVER_ANGLE}_slider"))])
    _run(reg, _coord([LOUVER_ANGLE]))
    assert reg.removed == ["number.vane_slider"]


def test_slider_of_climate_exclusive_field_with_slider_block_kept():
    # fan_speed: climate owns the preset dropdown, the number platform
    # still builds the free-range slider — the sweep must not delete it.
    reg = _FakeRegistry(
        [
            _RegEntry("number.fan_slider", _uid("fan_speed_slider")),
            _RegEntry("select.fan", _uid("fan_speed")),
        ]
    )
    _run(reg, _coord(["fan_speed"], sliders=["fan_speed"]))
    assert reg.removed == ["select.fan"]


def test_slider_of_other_entry_or_prefix_untouched():
    reg = _FakeRegistry(
        [
            _RegEntry("number.other", _uid("fan_speed_slider"), config_entry_id="other-entry"),
            _RegEntry("number.foreign", _uid("fan_speed_slider", host="10.0.0.9")),
        ]
    )
    _run(reg, _coord(["power"]))
    assert reg.removed == []
