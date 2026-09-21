"""Integration tests — entity unique_ids and device identifiers keyed on the
config-entry id.

Runs on the real HA config-entry engine via
pytest-homeassistant-custom-component. Only the gateway connection is
patched (``BlaueisMideaCoordinator.async_start``); the platforms load for
real, so the entity and device registries hold exactly what a fresh install
would write. With no gateway, no caps are discovered: the always-present
entities (climate, gateway health sensors) and both devices are what shows up.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_VENDORED_LIB = _REPO_ROOT / "custom_components" / "blaueis_midea" / "lib"
if str(_VENDORED_LIB) not in sys.path:
    sys.path.insert(0, str(_VENDORED_LIB))

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.blaueis_midea.const import DOMAIN  # noqa: E402

pytestmark = pytest.mark.asyncio

_START = "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator.async_start"


async def _setup(hass: HomeAssistant, entry) -> None:
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    with patch(_START, AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _entities(hass: HomeAssistant, entry) -> list[er.RegistryEntry]:
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


def _identifiers(hass: HomeAssistant, entry) -> set[str]:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return {ident for d in devices for dom, ident in d.identifiers if dom == DOMAIN}


async def test_fresh_install_keys_everything_on_the_entry_id(hass: HomeAssistant, mock_config_entry) -> None:
    await _setup(hass, mock_config_entry)

    entities = _entities(hass, mock_config_entry)
    uids = {e.unique_id for e in entities}
    assert f"{mock_config_entry.entry_id}_climate" in uids
    assert f"{mock_config_entry.entry_id}_gw_cpu_percent" in uids
    assert all(uid.startswith(f"{mock_config_entry.entry_id}_") for uid in uids)
    assert not any("127.0.0.1" in uid for uid in uids)
    assert _identifiers(hass, mock_config_entry) == {
        f"{mock_config_entry.entry_id}_ac",
        f"{mock_config_entry.entry_id}_gw",
    }
