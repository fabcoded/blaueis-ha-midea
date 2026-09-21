"""Integration tests — the Repairs issue for a prolonged gateway outage.

Two paths raise the same issue, off one per-entry outage clock. At setup,
``async_setup_entry`` raises ``ConfigEntryNotReady`` when the gateway cannot
be reached and HA retries with backoff. On a loaded entry the Device's own
reconnect loop keeps the entry loaded, so the coordinator's connection hooks
start a timer instead. Either way the outage is silent for the first 15
minutes; once it has lasted that long a warning issue keyed on the config
entry appears in Repairs, and it disappears as soon as the gateway is back
(a setup succeeds, or the Device reconnects), answers with an auth failure,
or the entry is removed. A plain unload or reload neither raises nor clears
it.

The setup path patches the gateway connection at
``BlaueisMideaCoordinator.async_start`` and drives the retries by reloading
the entry rather than by waiting on HA's backoff timer. The runtime path
patches ``Device.start`` (so the coordinator wires its real callbacks) and
plays the Device's ``on_disconnected`` / ``on_connected`` calls. ``freezer``
moves the clock in both.
"""

from __future__ import annotations

import sys
from pathlib import Path

# conftest.py adds these, but pytest's collection order can bite —
# import-time path inserts are the safe belt-and-braces.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_VENDORED_LIB = _REPO_ROOT / "custom_components" / "blaueis_midea" / "lib"
if str(_VENDORED_LIB) not in sys.path:
    sys.path.insert(0, str(_VENDORED_LIB))

from datetime import timedelta  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import issue_registry as ir  # noqa: E402
from pytest_homeassistant_custom_component.common import async_fire_time_changed  # noqa: E402

import custom_components.blaueis_midea as integration  # noqa: E402
from custom_components.blaueis_midea.const import DOMAIN  # noqa: E402

pytestmark = pytest.mark.asyncio

_START = "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_start"
_DEVICE_START = "blaueis.client.device.Device.start"


def _issue(hass: HomeAssistant, entry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"gateway_unreachable_{entry.entry_id}")


async def _setup_unreachable(hass: HomeAssistant, entry, err: Exception | None = None) -> None:
    """One setup attempt against a gateway that does not answer."""
    with patch(_START, AsyncMock(side_effect=err or OSError("connection refused"))):
        if entry.state is ConfigEntryState.NOT_LOADED:
            await hass.config_entries.async_setup(entry.entry_id)
        else:
            await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def _setup_reachable(hass: HomeAssistant, entry) -> None:
    with (
        patch(_START, AsyncMock()),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _unload(hass: HomeAssistant, entry) -> None:
    with patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_transient_outage_stays_silent(hass: HomeAssistant, mock_config_entry, freezer) -> None:
    """Retries within the first 15 minutes raise no issue."""
    mock_config_entry.add_to_hass(hass)

    await _setup_unreachable(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is None

    freezer.tick(timedelta(minutes=14, seconds=59))
    await _setup_unreachable(hass, mock_config_entry, TimeoutError())
    assert _issue(hass, mock_config_entry) is None


async def test_prolonged_outage_raises_a_warning_issue(hass: HomeAssistant, mock_config_entry, freezer) -> None:
    mock_config_entry.add_to_hass(hass)

    await _setup_unreachable(hass, mock_config_entry)
    freezer.tick(timedelta(minutes=15))
    await _setup_unreachable(hass, mock_config_entry)

    issue = _issue(hass, mock_config_entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "gateway_unreachable"
    assert issue.is_fixable is False
    assert issue.translation_placeholders == {
        "title": mock_config_entry.title,
        "host": "127.0.0.1",
        "port": "8765",
        "minutes": "15",
    }


async def test_issue_is_keyed_per_config_entry(hass: HomeAssistant, mock_config_entry, freezer) -> None:
    """A second entry's outage clock is its own: one entry down for 15
    minutes does not raise an issue for another that just started failing."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(
        domain=DOMAIN,
        title="Blaueis AC (other)",
        data={**mock_config_entry.data, "host": "127.0.0.2"},
        options=dict(mock_config_entry.options),
        unique_id="other_entry",
    )
    mock_config_entry.add_to_hass(hass)

    await _setup_unreachable(hass, mock_config_entry)
    freezer.tick(timedelta(minutes=16))
    await _setup_unreachable(hass, mock_config_entry)
    # Added only now: setting up the domain sets up every entry it has.
    other.add_to_hass(hass)
    await _setup_unreachable(hass, other)

    assert _issue(hass, mock_config_entry) is not None
    assert _issue(hass, other) is None


async def test_successful_setup_deletes_the_issue(hass: HomeAssistant, mock_config_entry, freezer) -> None:
    mock_config_entry.add_to_hass(hass)
    await _setup_unreachable(hass, mock_config_entry)
    freezer.tick(timedelta(minutes=20))
    await _setup_unreachable(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is not None

    await _setup_reachable(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is None

    # The outage clock was reset: a fresh failure is transient again.
    await _unload(hass, mock_config_entry)
    await _setup_unreachable(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is None


async def test_auth_failure_deletes_the_issue(hass: HomeAssistant, mock_config_entry, freezer) -> None:
    """A gateway that rejects our key is reachable — the unreachable issue
    goes, and the reauth flow takes over."""
    from blaueis.core.crypto import AuthenticationError

    mock_config_entry.add_to_hass(hass)
    await _setup_unreachable(hass, mock_config_entry)
    freezer.tick(timedelta(minutes=20))
    await _setup_unreachable(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is not None

    with patch(_START, AsyncMock(side_effect=AuthenticationError("PSK mismatch"))):
        await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert _issue(hass, mock_config_entry) is None


async def test_removing_the_entry_deletes_the_issue(hass: HomeAssistant, mock_config_entry, freezer) -> None:
    mock_config_entry.add_to_hass(hass)
    await _setup_unreachable(hass, mock_config_entry)
    freezer.tick(timedelta(minutes=20))
    await _setup_unreachable(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is not None

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, mock_config_entry) is None


# ── Runtime path: the connection drops while the entry is loaded ───────


@pytest.fixture
async def coordinator(hass: HomeAssistant, mock_config_entry):
    """A loaded entry whose coordinator is really started (its Device
    callbacks wired) against a Device that never opens a socket."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch(_DEVICE_START, AsyncMock()),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    yield mock_config_entry.runtime_data
    if mock_config_entry.state is ConfigEntryState.LOADED:
        await _unload(hass, mock_config_entry)


async def _elapse(hass: HomeAssistant, freezer, **delta) -> None:
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_runtime_disconnect_stays_silent_before_the_deadline(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    coordinator.device.on_disconnected()
    assert not coordinator.connected

    await _elapse(hass, freezer, minutes=14, seconds=59)

    assert _issue(hass, mock_config_entry) is None


async def test_runtime_outage_raises_a_warning_issue(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    coordinator.device.on_disconnected()

    await _elapse(hass, freezer, minutes=15)

    issue = _issue(hass, mock_config_entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "gateway_unreachable"
    assert issue.is_fixable is False
    assert issue.translation_placeholders == {
        "title": mock_config_entry.title,
        "host": "127.0.0.1",
        "port": "8765",
        "minutes": "15",
    }


async def test_reconnect_deletes_the_issue_and_resets_the_clock(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=20)
    assert _issue(hass, mock_config_entry) is not None

    coordinator.device.on_connected()

    assert coordinator.connected
    assert _issue(hass, mock_config_entry) is None
    assert mock_config_entry.entry_id not in integration._unreachable_since(hass)

    # The next drop starts a fresh, silent 15 minutes.
    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=14)
    assert _issue(hass, mock_config_entry) is None
    await _elapse(hass, freezer, minutes=1)
    assert _issue(hass, mock_config_entry) is not None


async def test_reconnect_before_the_deadline_cancels_the_timer(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=10)
    coordinator.device.on_connected()

    await _elapse(hass, freezer, minutes=20)

    assert _issue(hass, mock_config_entry) is None


async def test_repeated_disconnect_keeps_the_first_clock(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=10)
    coordinator.device.on_disconnected()  # e.g. a reconnect that dropped again before on_connected
    await _elapse(hass, freezer, minutes=5)

    assert _issue(hass, mock_config_entry) is not None


async def test_timer_waking_before_the_clock_deadline_waits_out_the_rest(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    """The timer runs on the loop clock, the deadline on the wall clock; if
    the timer wakes first it must re-arm rather than give up."""
    coordinator.device.on_disconnected()
    since = integration._unreachable_since(hass)
    since[mock_config_entry.entry_id] += timedelta(seconds=30)

    await _elapse(hass, freezer, minutes=15)
    assert _issue(hass, mock_config_entry) is None

    await _elapse(hass, freezer, seconds=30)
    assert _issue(hass, mock_config_entry) is not None


async def test_unload_while_disconnected_cancels_the_timer(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=5)

    await _unload(hass, mock_config_entry)
    await _elapse(hass, freezer, minutes=30)

    assert _issue(hass, mock_config_entry) is None
    assert mock_config_entry.entry_id not in integration._unreachable_since(hass)


async def test_plain_reload_while_connected_is_not_an_outage(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    """Device.stop() reports a disconnect on the way out; that must not be
    taken for a lost connection."""
    with (
        patch(_DEVICE_START, AsyncMock()),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)),
    ):
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.entry_id not in integration._unreachable_since(hass)

    await _elapse(hass, freezer, minutes=30)

    assert _issue(hass, mock_config_entry) is None


async def test_stopping_the_coordinator_is_not_a_lost_connection(coordinator) -> None:
    lost = MagicMock()
    coordinator.on_connection_lost = lost

    await coordinator.async_stop()  # Device.stop() calls on_disconnected

    lost.assert_not_called()


async def test_setup_failing_after_the_connect_stops_the_device_and_leaves_no_outage(
    hass: HomeAssistant, mock_config_entry, freezer
) -> None:
    """HA does not run the unload callbacks of an entry whose setup failed,
    so the hooks wired after the connect must not outlive it: the Device is
    stopped, and a drop reported afterwards arms no timer for a dead entry."""
    from blaueis.client.device import Device

    mock_config_entry.add_to_hass(hass)
    with (
        patch(_DEVICE_START, AsyncMock()),
        patch.object(Device, "stop", autospec=True, side_effect=Device.stop) as stop,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", AsyncMock(side_effect=RuntimeError("platform boom"))
        ),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    coordinator = mock_config_entry.runtime_data
    stop.assert_awaited_once_with(coordinator.device)
    assert coordinator.on_connection_lost is None
    assert coordinator.on_connection_restored is None

    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=30)

    assert not integration._outage_timers(hass)
    assert mock_config_entry.entry_id not in integration._unreachable_since(hass)
    assert _issue(hass, mock_config_entry) is None


async def test_unload_leaves_a_raised_issue_and_removal_deletes_it(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer
) -> None:
    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=20)
    assert _issue(hass, mock_config_entry) is not None

    await _unload(hass, mock_config_entry)
    assert _issue(hass, mock_config_entry) is not None

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, mock_config_entry) is None


@pytest.mark.parametrize("minutes_down", [5, 20], ids=["before_the_deadline", "after_the_issue_is_up"])
async def test_runtime_auth_failure_hands_over_to_reauth(
    hass: HomeAssistant, mock_config_entry, coordinator, freezer, minutes_down: int
) -> None:
    """The reconnect loop reports the disconnect before it finds the key
    rejected. The gateway answered, so no issue is raised (or kept) and the
    timer is gone."""
    coordinator.device.on_disconnected()
    await _elapse(hass, freezer, minutes=minutes_down)

    coordinator.device.on_auth_failed("PSK mismatch")
    await hass.async_block_till_done()
    assert _issue(hass, mock_config_entry) is None

    await _elapse(hass, freezer, minutes=30)
    assert _issue(hass, mock_config_entry) is None
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())
