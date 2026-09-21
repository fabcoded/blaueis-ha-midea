"""Integration tests — ``BlaueisMideaCoordinator.async_start`` and the
connected flag.

``async_start`` leaves ``connected`` to the Device's callbacks. A clean
``Device.start()`` fires ``on_connected`` from inside the call; a link that
drops while ``start()`` is still running fires ``on_disconnected`` instead,
and the coordinator must not report connected afterwards. ``Device.start``
is patched so the callbacks the coordinator wired are played by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# conftest.py adds these, but pytest's collection order can bite —
# import-time path inserts are the safe belt-and-braces.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_VENDORED_LIB = _REPO_ROOT / "custom_components" / "blaueis_midea" / "lib"
if str(_VENDORED_LIB) not in sys.path:
    sys.path.insert(0, str(_VENDORED_LIB))

import pytest  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.blaueis_midea.coordinator import BlaueisMideaCoordinator  # noqa: E402

pytestmark = pytest.mark.asyncio

_DEVICE_START = "blaueis.client.device.Device.start"


@pytest.fixture
async def coordinator(hass: HomeAssistant):
    coordinator = BlaueisMideaCoordinator(hass, "127.0.0.1", 8765, "00" * 16)
    yield coordinator
    await coordinator.async_stop()


async def test_clean_start_ends_connected(hass: HomeAssistant, coordinator) -> None:
    """Device.start() fires on_connected once the handshake is done."""

    async def start() -> None:
        coordinator.device.on_connected()

    with patch(_DEVICE_START, AsyncMock(side_effect=start)):
        await coordinator.async_start()

    assert coordinator.connected


async def test_disconnect_during_start_leaves_the_coordinator_disconnected(hass: HomeAssistant, coordinator) -> None:
    """The link drops while start() is still running: the Device reports
    on_disconnected and never on_connected. async_start must not override
    that by marking the coordinator connected when start() returns."""

    async def start() -> None:
        coordinator.device.on_disconnected()

    with patch(_DEVICE_START, AsyncMock(side_effect=start)):
        await coordinator.async_start()

    assert not coordinator.connected
