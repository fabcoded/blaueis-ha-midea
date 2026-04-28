"""Shared fixtures for the pytest-homeassistant-custom-component suite.

Integration tests use this conftest (the mock-everything conftest in
``tests/unit/conftest.py`` doesn't get applied here — each subdir is
its own fixture scope).

Fixtures provided:

- ``hass`` (from pytest-homeassistant-custom-component) — real HA
  event loop + state machine.
- ``enable_custom_integrations`` (autouse) — lets ``blaueis_midea``
  load as a custom integration.
- ``mock_config_entry`` — a pre-populated ``MockConfigEntry`` for
  ``blaueis_midea``, NOT added to hass. Tests call
  ``.add_to_hass(hass)`` if they need it registered.
- ``mock_gateway_device`` — a ``Device`` stub whose
  ``register_frame_observer`` / ``unregister_frame_observer`` /
  ``_client.send_frame`` etc. can be driven from tests without
  opening a WS connection.
- ``replay_session_15_frame`` — helper that feeds the Session 15
  C1 Group 4 frame through whatever observers are registered on
  the mock device, so tests can assert the decode + classify +
  synthesize paths end-to-end.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Make ``custom_components.blaueis_midea`` importable from integration
# tests. phcc's ``enable_custom_integrations`` teaches HA to discover
# the integration but Python imports still need the path.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# Also vendored lib under custom_components — the integration uses
# ``sys.path.insert(_LIB)`` at import time, but in tests we may need
# ``blaueis.core.*`` importable earlier.
_VENDORED_LIB = _REPO_ROOT / "custom_components" / "blaueis_midea" / "lib"
if str(_VENDORED_LIB) not in sys.path:
    sys.path.insert(0, str(_VENDORED_LIB))

import pytest  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

# Canonical Q11 C1 Group 4 frame — 721.57 kWh lifetime / 0.191 kW realtime.
SESSION_15_C1G4_BODY = bytes.fromhex(
    "c1210144000119dd00000000000000000007760000"
)

# Synthetic B5 cap record: cap 0x16=0 (Q11 reports "no power calc").
Q11_CAP_0x16_0 = [
    {
        "cap_id": "0x16",
        "cap_type": 2,
        "key_16": "0x0216",
        "data_len": 1,
        "data": [0],
        "data_hex": "00",
    }
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Without this fixture, HA refuses to load custom_components/*.

    Applied autouse so every integration test benefits. The canonical
    pytest-homeassistant-custom-component pattern is to consume
    ``enable_custom_integrations`` and simply return — declaring the
    dependency is enough; the phcc fixture does the mutation.
    """
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A fresh MockConfigEntry matching the real config-flow shape.

    Not added to hass — tests call ``.add_to_hass(hass)`` themselves
    so they control entry lifecycle explicitly.
    """
    return MockConfigEntry(
        domain="blaueis_midea",
        title="Blaueis AC (test)",
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: 8765,
            "psk": "00" * 16,  # placeholder PSK — tests bypass crypto
        },
        options={
            "follow_me_function_configured": False,
            "follow_me_function_enabled": False,
            "follow_me_function_guard_temp_max": 40.0,
            "follow_me_function_guard_temp_min": -15.0,
            "follow_me_function_safety_timeout": 300,
            "glossary_overrides_yaml": "",
        },
        unique_id="test_entry",
    )


@pytest.fixture
def mock_gateway_device():
    """A Device stub with the frame-observer hook wired up.

    Tests register their ShadowDecoder via ``register_frame_observer``;
    ``replay_session_15_frame`` (or a custom feed) then calls the
    observers to simulate frame ingress.

    ``_client.send_frame`` is an AsyncMock — tests can assert on the
    frames the inventory scan injected.
    """
    device = MagicMock()
    device._frame_observers = []
    device._glossary = None  # tests populate from load_glossary if needed
    device._status = {"capabilities_raw": list(Q11_CAP_0x16_0)}

    def register_observer(cb):
        if cb not in device._frame_observers:
            device._frame_observers.append(cb)

    def unregister_observer(cb):
        if cb in device._frame_observers:
            device._frame_observers.remove(cb)

    device.register_frame_observer = register_observer
    device.unregister_frame_observer = unregister_observer

    # Async stubs for send / query paths
    device._client = MagicMock()
    device._client._ws = MagicMock()  # truthy — "connected"
    device._client.send_frame = AsyncMock()

    return device


@pytest.fixture
def replay_session_15_frame(
    mock_gateway_device,
) -> Callable[[], None]:
    """Push the Session 15 C1 Group 4 frame through registered observers.

    Returns a zero-arg callable; tests attach their observer first, then
    call the fixture to trigger one frame's worth of ingress:

        def test_thing(mock_gateway_device, replay_session_15_frame):
            shadow = ShadowDecoder(glossary)
            mock_gateway_device.register_frame_observer(
                lambda pk, body: shadow.observe(pk, body)
            )
            replay_session_15_frame()
            # ... assert on shadow state ...
    """

    def _fire():
        for obs in list(mock_gateway_device._frame_observers):
            obs("rsp_0xc1_group4", SESSION_15_C1G4_BODY)

    return _fire
