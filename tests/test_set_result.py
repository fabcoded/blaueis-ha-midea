"""Tests for _set_result.check_set_result — mode gate error surfacing."""

from __future__ import annotations

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.blaueis_midea._set_result import (
    _humanize_field,
    _humanize_rejection,
    check_set_result,
)


# ── No-op cases ─────────────────────────────────────────────


class TestNoOp:
    def test_none_result(self):
        check_set_result(None, primary_fields={"power"})

    def test_empty_result(self):
        check_set_result({}, primary_fields={"power"})

    def test_old_device_shape(self):
        result = {"cmd_0x40": {"body": b"\x00", "preflight": [], "fields_encoded": 1}}
        check_set_result(result, primary_fields={"power"})

    def test_no_rejections(self):
        result = {"expanded": {"power": True}, "rejected": {}, "results": {}}
        check_set_result(result, primary_fields={"power"})

    def test_only_secondary_rejected(self):
        result = {
            "expanded": {"frost_protection": True},
            "rejected": {"turbo_mode": "requires mode ['cool'], current=4"},
            "results": {},
        }
        check_set_result(result, primary_fields={"frost_protection"})


# ── Raises on primary rejection ─────────────────────────────


class TestPrimaryRejection:
    def test_single_rejection(self):
        result = {
            "expanded": {},
            "rejected": {"frost_protection": "requires mode ['heat'], current=2"},
            "results": {},
        }
        with pytest.raises(HomeAssistantError, match="Frost Protection"):
            check_set_result(result, primary_fields={"frost_protection"})

    def test_message_contains_mode(self):
        result = {
            "expanded": {},
            "rejected": {"frost_protection": "requires mode ['heat'], current=2"},
            "results": {},
        }
        with pytest.raises(HomeAssistantError, match="Heat.*Cool"):
            check_set_result(result, primary_fields={"frost_protection"})

    def test_multiple_primaries_rejected(self):
        result = {
            "expanded": {},
            "rejected": {
                "frost_protection": "requires mode ['heat'], current=2",
                "sleep_mode": "requires mode ['cool','heat','dry','auto'], current=5",
            },
            "results": {},
        }
        with pytest.raises(HomeAssistantError, match="Frost Protection.*Sleep"):
            check_set_result(result, primary_fields={"frost_protection", "sleep_mode"})

    def test_mixed_primary_and_secondary(self):
        result = {
            "expanded": {"eco_mode": True},
            "rejected": {
                "frost_protection": "requires mode ['heat'], current=2",
                "turbo_mode": "requires mode ['cool','heat'], current=5",
            },
            "results": {},
        }
        with pytest.raises(HomeAssistantError, match="Frost Protection"):
            check_set_result(result, primary_fields={"frost_protection"})

    def test_unknown_field_titlecased(self):
        result = {
            "expanded": {},
            "rejected": {"jet_cool": "requires mode ['cool'], current=4"},
            "results": {},
        }
        with pytest.raises(HomeAssistantError, match="Jet Cool"):
            check_set_result(result, primary_fields={"jet_cool"})


# ── Preflight blocks ────────────────────────────────────────


class TestPreflight:
    def test_preflight_blocked(self):
        result = {
            "expanded": {"power": True},
            "rejected": {},
            "results": {
                "cmd_0x40": {
                    "body": None,
                    "preflight": ["fan_speed: stale (>300s)"],
                    "fields_encoded": 0,
                },
            },
        }
        with pytest.raises(HomeAssistantError, match="stale"):
            check_set_result(result, primary_fields={"power"})

    def test_preflight_passes_when_body_present(self):
        result = {
            "expanded": {"power": True},
            "rejected": {},
            "results": {
                "cmd_0x40": {
                    "body": b"\x00",
                    "preflight": [],
                    "fields_encoded": 1,
                },
            },
        }
        check_set_result(result, primary_fields={"power"})

    def test_rejection_preferred_over_preflight(self):
        result = {
            "expanded": {},
            "rejected": {"frost_protection": "requires mode ['heat'], current=2"},
            "results": {
                "cmd_0x40": {
                    "body": None,
                    "preflight": ["fan_speed: stale"],
                    "fields_encoded": 0,
                },
            },
        }
        with pytest.raises(HomeAssistantError, match="Frost Protection"):
            check_set_result(result, primary_fields={"frost_protection"})


# ── Humanize helpers ─────────────────────────────────────────


class TestHumanize:
    def test_field_preset_label(self):
        assert _humanize_field("frost_protection") == "Frost Protection"
        assert _humanize_field("eco_mode") == "ECO"
        assert _humanize_field("turbo_mode") == "Turbo"
        assert _humanize_field("sleep_mode") == "Sleep"

    def test_field_fallback(self):
        assert _humanize_field("jet_cool") == "Jet Cool"
        assert _humanize_field("swing_vertical") == "Swing Vertical"

    def test_rejection_single_mode(self):
        msg = _humanize_rejection("requires mode ['heat'], current=2")
        assert "Heat" in msg
        assert "Cool" in msg

    def test_rejection_multi_mode(self):
        msg = _humanize_rejection("requires mode ['cool','heat','dry','auto'], current=5")
        assert "Fan Only" in msg

    def test_rejection_unknown_format(self):
        raw = "something unexpected"
        assert _humanize_rejection(raw) == raw
