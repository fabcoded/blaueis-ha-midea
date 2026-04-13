"""Blaueis Midea AC — Home Assistant integration.

Connects to a Blaueis gateway via WebSocket and exposes the AC unit
as HA entities. Capabilities are discovered via B5 queries; only
confirmed features become entities.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make vendored blaueis library importable
_LIB = str(Path(__file__).parent / "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_PSK, DOMAIN
from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]

type BlaueisMideaConfigEntry = ConfigEntry[BlaueisMideaCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: BlaueisMideaConfigEntry
) -> bool:
    """Set up Blaueis Midea AC from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    psk = entry.data[CONF_PSK]

    # Pre-load glossary in executor to avoid blocking the event loop
    from blaueis.core.codec import load_glossary
    await hass.async_add_executor_job(load_glossary)

    coordinator = BlaueisMideaCoordinator(hass, host, port, psk)
    await coordinator.async_start()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BlaueisMideaConfigEntry
) -> bool:
    """Unload a config entry."""
    coordinator: BlaueisMideaCoordinator = entry.runtime_data

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await coordinator.async_stop()

    return unload_ok
