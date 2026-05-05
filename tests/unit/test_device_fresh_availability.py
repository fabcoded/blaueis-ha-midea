"""Coordinator.device_fresh propagates into entity availability.

When the AC stops responding (powered off / firmware crash / comms
partition), every UI-visible entity must fade together — not just
disconnect-aware ones. The single coordinator-level check is wired
into _ux_mixin.field_ux_available + climate.available + number.available.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.blaueis_midea._ux_mixin import field_ux_available


def _coord(*, connected: bool, fresh: bool) -> MagicMock:
    coord = MagicMock()
    coord.connected = connected
    coord.device_fresh = fresh
    coord.device.field_gdef.return_value = {}
    coord.device.read.return_value = None
    coord.device.caps_bitmap.return_value = {}
    return coord


# ── _ux_mixin gate ───────────────────────────────────────────────────


def test_field_ux_available_false_when_not_connected():
    assert field_ux_available(_coord(connected=False, fresh=True), "x") is False


def test_field_ux_available_false_when_not_fresh():
    """Connected but stale → unavailable. Mirrors the staleness rule
    so a silent AC fades every entity."""
    assert field_ux_available(_coord(connected=True, fresh=False), "x") is False


def test_field_ux_available_true_when_connected_and_fresh():
    assert field_ux_available(_coord(connected=True, fresh=True), "x") is True
