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

from .const import CONF_PSK, DEBUG_RING_SIZE_MB, DOMAIN
from .coordinator import BlaueisMideaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]

# Loggers attached to the per-entry DebugRing. Keeping the list explicit (not
# attaching at root) prevents us from slurping unrelated HA records into the
# ring. Level is raised to VERBOSE so the ring can observe packet-level
# events without changing what ends up in homeassistant.log.
_VERBOSE = 5
_RING_LOGGERS = (
    "blaueis_midea",
    "blaueis.device",
    "blaueis.client",
    "hvac_client",
)

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

    debug_ring = _install_debug_ring(entry)

    coordinator = BlaueisMideaCoordinator(hass, host, port, psk, debug_ring=debug_ring)
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
        _uninstall_debug_ring(entry)

    return unload_ok


# ── DebugRing plumbing ─────────────────────────────────────────────────

def _install_debug_ring(entry: BlaueisMideaConfigEntry):
    """Create a per-entry DebugRing, attach it to the blaueis loggers.

    Ring level = VERBOSE, named-logger level raised to VERBOSE so records
    reach the handler. `propagate` is left untouched (default True) so that
    INFO+ records still appear in homeassistant.log. The ring observes
    everything; HA's handlers filter at their own level.
    """
    from blaueis.core.debug_ring import DebugRing

    logging.addLevelName(_VERBOSE, "VERBOSE")

    ring = DebugRing(size_bytes=DEBUG_RING_SIZE_MB * 1024 * 1024)
    ring.setLevel(_VERBOSE)

    attached: list[logging.Logger] = []
    for name in _RING_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(_VERBOSE)
        lg.addHandler(ring)
        attached.append(lg)

    # Stash so unload can detach cleanly.
    entry.async_on_unload(lambda: None)  # no-op, we detach in _uninstall
    entry._blaueis_ring = ring  # type: ignore[attr-defined]
    entry._blaueis_ring_loggers = attached  # type: ignore[attr-defined]
    _LOGGER.debug(
        "DebugRing attached to %d loggers (%d MB)",
        len(attached), DEBUG_RING_SIZE_MB,
    )
    return ring


def _uninstall_debug_ring(entry: BlaueisMideaConfigEntry) -> None:
    ring = getattr(entry, "_blaueis_ring", None)
    loggers = getattr(entry, "_blaueis_ring_loggers", None) or []
    if ring is None:
        return
    for lg in loggers:
        lg.removeHandler(ring)
    ring.clear()
