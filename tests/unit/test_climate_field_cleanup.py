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

from custom_components.blaueis_midea import _cleanup_orphaned_field_entities
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


def _coord(available):
    from blaueis.core.codec import load_glossary

    c = MagicMock()
    c.host, c.port = HOST, PORT
    c.device.glossary = load_glossary()
    c.device.available_fields = {f: {} for f in available}
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
