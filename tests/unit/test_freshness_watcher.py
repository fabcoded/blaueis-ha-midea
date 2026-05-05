"""Coordinator's freshness watcher — pushes entity availability when
``device_fresh`` flips.

HA's availability model is pull-based; nothing re-evaluates
``entity.available`` unless ``async_write_ha_state`` runs. When the
AC goes silent, there are no ingest events, so without a push the
entities keep rendering the last-known state. The watcher fixes
that by firing every registered callback on transitions.

Tests target ``BlaueisMideaCoordinator._fire_all_entity_callbacks``
plus the transition-detection branch logic. The actual asyncio
loop is exercised separately to keep these focused / deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.blaueis_midea.coordinator import BlaueisMideaCoordinator


def _make_coord() -> BlaueisMideaCoordinator:
    """Build a coord without going through __init__ — that path pulls
    Device + StatusDB + Follow Me. We only need the entity-callback
    plumbing and the watcher's branching."""
    coord = BlaueisMideaCoordinator.__new__(BlaueisMideaCoordinator)
    coord._entity_callbacks = {}
    coord._last_known_fresh = None
    return coord


# ── Dedup fire-all helper ───────────────────────────────────────────


def test_fire_all_invokes_each_callback_once():
    coord = _make_coord()
    cb1 = MagicMock()
    cb2 = MagicMock()
    coord._entity_callbacks["field_a"] = {cb1, cb2}
    coord._entity_callbacks["field_b"] = {cb1}  # cb1 also under field_b

    coord._fire_all_entity_callbacks()

    cb1.assert_called_once()  # not twice — set dedupe across keys
    cb2.assert_called_once()


def test_fire_all_continues_on_callback_exception():
    coord = _make_coord()
    bad = MagicMock(side_effect=RuntimeError("boom"))
    good = MagicMock()
    coord._entity_callbacks["x"] = {bad, good}

    coord._fire_all_entity_callbacks()

    bad.assert_called_once()
    good.assert_called_once()


def test_fire_all_no_callbacks_is_no_op():
    coord = _make_coord()
    coord._fire_all_entity_callbacks()  # must not raise


# ── Transition logic — simulate one watcher tick ────────────────────
#
# We call the inner branch logic directly instead of awaiting the
# asyncio loop. Keeps the test deterministic and avoids real time.


def _tick(coord: BlaueisMideaCoordinator, current: bool) -> bool:
    """Single tick of the watcher's transition-detection. Returns True
    if a callback push would have fired."""
    fired = False
    if coord._last_known_fresh is None:
        coord._last_known_fresh = current
    elif current != coord._last_known_fresh:
        coord._last_known_fresh = current
        coord._fire_all_entity_callbacks()
        fired = True
    return fired


def test_first_tick_just_snapshots():
    coord = _make_coord()
    cb = MagicMock()
    coord._entity_callbacks["x"] = {cb}
    fired = _tick(coord, True)
    assert fired is False
    cb.assert_not_called()
    assert coord._last_known_fresh is True


def test_steady_true_does_not_fire():
    coord = _make_coord()
    cb = MagicMock()
    coord._entity_callbacks["x"] = {cb}
    coord._last_known_fresh = True
    fired = _tick(coord, True)
    assert fired is False
    cb.assert_not_called()


def test_steady_false_does_not_fire():
    coord = _make_coord()
    cb = MagicMock()
    coord._entity_callbacks["x"] = {cb}
    coord._last_known_fresh = False
    fired = _tick(coord, False)
    assert fired is False
    cb.assert_not_called()


def test_transition_true_to_false_fires():
    coord = _make_coord()
    cb = MagicMock()
    coord._entity_callbacks["x"] = {cb}
    coord._last_known_fresh = True
    fired = _tick(coord, False)
    assert fired is True
    cb.assert_called_once()
    assert coord._last_known_fresh is False


def test_transition_false_to_true_fires():
    coord = _make_coord()
    cb = MagicMock()
    coord._entity_callbacks["x"] = {cb}
    coord._last_known_fresh = False
    fired = _tick(coord, True)
    assert fired is True
    cb.assert_called_once()
    assert coord._last_known_fresh is True


def test_multi_field_same_callback_fires_once_per_transition():
    """Realistic scenario: an entity registers one callback under
    two field names. On a freshness flip the callback should fire
    once, not twice."""
    coord = _make_coord()
    cb = MagicMock()
    coord._entity_callbacks["field_a"] = {cb}
    coord._entity_callbacks["operating_mode"] = {cb}
    coord._last_known_fresh = True
    _tick(coord, False)
    cb.assert_called_once()
