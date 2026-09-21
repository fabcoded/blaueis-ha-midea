"""Integration tests — the Repairs issue for a prolonged gateway outage.

``async_setup_entry`` raises ``ConfigEntryNotReady`` when the gateway cannot
be reached, and HA retries with backoff. Those retries are silent for the
first 15 minutes of an outage; once it has lasted that long a warning issue
keyed on the config entry appears in Repairs, and it disappears as soon as a
setup succeeds (or the gateway answers with an auth failure, or the entry is
removed).

The gateway connection is patched at ``BlaueisMideaCoordinator.async_start``;
the retries are driven by reloading the entry rather than by waiting on HA's
backoff timer, with ``freezer`` moving the clock.
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
from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import issue_registry as ir  # noqa: E402

from custom_components.blaueis_midea.const import DOMAIN  # noqa: E402

pytestmark = pytest.mark.asyncio

_START = "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_start"


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
