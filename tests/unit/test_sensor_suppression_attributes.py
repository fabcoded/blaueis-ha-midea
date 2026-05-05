"""Unit tests — BlaueisMideaSensor.extra_state_attributes surfaces
value-suppression provenance.

When the codec/process layer suppresses a field (sentinel hit or
out-of-range decoded value), ``device.read_full()`` returns a dict
that carries a ``suppression`` sub-dict alongside ``value: None``.
The HA sensor entity exposes this as ``extra_state_attributes`` so a
developer or power user can see *why* the tile is showing ``unknown``
without pulling a diagnostic bundle.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.blaueis_midea.sensor import BlaueisMideaSensor


def _make_sensor(
    read_full_payload: dict | None, *, power: bool = True
) -> BlaueisMideaSensor:
    """Build a sensor with a mocked coordinator/device.

    ``read_full_payload`` is what ``device.read_full(field_name)`` returns;
    pass ``None`` to simulate "no slot for this field yet". ``power``
    drives ``device.read("power")`` for the off-behavior path that
    ``native_value`` consults — defaults to ``True`` so that path
    doesn't interfere with attribute assertions.
    """
    coord = MagicMock()
    coord.host = "127.0.0.1"
    coord.port = 8765
    coord.device = MagicMock()
    coord.device.field_gdef.return_value = {"feature_available": "readable"}

    def read(field_name):
        if field_name == "power":
            return power
        # Mirror the value from read_full when present, else None.
        return (read_full_payload or {}).get("value")

    coord.device.read.side_effect = read
    coord.device.read_full.return_value = read_full_payload
    return BlaueisMideaSensor(coord, {"field_name": "fixture_field"})


def test_attributes_present_for_sentinel_hit() -> None:
    """When the freshest read carries a sentinel suppression, the
    sensor's attributes carry reason / raw / ts."""
    payload = {
        "value": None,
        "ts": "2026-05-05T12:00:00+00:00",
        "source": "rsp_0xc0",
        "generation": "legacy",
        "scope_matched": "protocol_all",
        "disagreements": [],
        "suppression": {
            "reason": "sentinel",
            "raw": 0xFF,
            "frame_no": 7,
            "ts": "2026-05-05T12:00:00+00:00",
        },
    }
    s = _make_sensor(payload)
    attrs = s.extra_state_attributes
    assert attrs is not None
    assert attrs["last_suppression"] == "sentinel"
    assert attrs["last_suppression_raw"] == 0xFF
    assert attrs["last_suppression_at"] == "2026-05-05T12:00:00+00:00"


def test_attributes_present_for_out_of_range_hit() -> None:
    payload = {
        "value": None,
        "ts": "2026-05-05T12:00:00+00:00",
        "source": "rsp_0xc0",
        "generation": "legacy",
        "scope_matched": "protocol_all",
        "disagreements": [],
        "suppression": {
            "reason": "out_of_range",
            "raw": 102.0,
            "frame_no": 12,
            "ts": "2026-05-05T12:00:00+00:00",
        },
    }
    s = _make_sensor(payload)
    attrs = s.extra_state_attributes
    assert attrs is not None
    assert attrs["last_suppression"] == "out_of_range"
    assert attrs["last_suppression_raw"] == 102.0


def test_attributes_absent_when_no_suppression() -> None:
    """A normal reading (no suppression in the read_full payload) must
    not introduce an empty attributes block — return None so HA
    renders nothing."""
    payload = {
        "value": 21.5,
        "ts": "2026-05-05T12:00:00+00:00",
        "source": "rsp_0xc0",
        "generation": "legacy",
        "scope_matched": "protocol_all",
        "disagreements": [],
    }
    s = _make_sensor(payload)
    assert s.extra_state_attributes is None


def test_attributes_absent_when_field_unread() -> None:
    """``device.read_full()`` returning None (field has no slot yet)
    must yield no attributes block."""
    s = _make_sensor(None)
    assert s.extra_state_attributes is None
