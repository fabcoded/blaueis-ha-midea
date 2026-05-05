"""``blaueis_midea.test_suppress`` service — debugging hatch for staleness.

Drops every incoming AC frame for ``duration`` seconds across every
loaded Blaueis Midea config entry, so consumers (HA entity availability,
diagnostic readouts) can be verified against real-world silent-AC
behaviour without disconnecting the AC. Auto-clears on timer expiry.

Registered globally on first entry setup; no-op on subsequent entries.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_TEST_SUPPRESS = "test_suppress"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("duration"): vol.All(cv.positive_float, vol.Range(min=0, max=600)),
    }
)


async def async_setup_test_suppress(hass: HomeAssistant) -> None:
    """Idempotent service registration. Call from each entry's setup;
    only the first call registers."""
    if hass.services.has_service(DOMAIN, SERVICE_TEST_SUPPRESS):
        return

    async def _handler(call: ServiceCall) -> None:
        duration = float(call.data["duration"])
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.warning("test_suppress: no Blaueis Midea AC config entries loaded")
            return
        applied: list[tuple[str, float]] = []
        for entry in entries:
            coord = getattr(entry, "runtime_data", None)
            if coord is None or coord.device is None:
                continue
            actual = coord.device.set_test_suppression(duration)
            applied.append((entry.title, actual))
        _LOGGER.warning(
            "test_suppress: applied %r — entities will fade once the "
            "staleness window expires",
            applied,
        )

    hass.services.async_register(
        DOMAIN, SERVICE_TEST_SUPPRESS, _handler, schema=SERVICE_SCHEMA
    )
