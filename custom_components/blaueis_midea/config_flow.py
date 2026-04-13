"""Config flow for Blaueis Midea AC integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import CONF_PSK, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=8765): int,
        vol.Required(CONF_PSK): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate user input by testing connection to the gateway."""
    host = data[CONF_HOST]
    port = data[CONF_PORT]
    psk = data[CONF_PSK]

    # Test TCP connectivity first
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
        writer.close()
        await writer.wait_closed()
    except (OSError, asyncio.TimeoutError) as err:
        raise CannotConnect from err

    # Test WebSocket + encryption handshake
    try:
        from blaueis.client.ws_client import HvacClient
        from blaueis.core.crypto import psk_to_bytes

        psk_bytes = psk_to_bytes(psk)
        client = HvacClient(host, port, psk=psk_bytes)
        await client.connect()
        await client.close()
    except Exception as err:
        _LOGGER.debug("WebSocket handshake failed: %s", err)
        raise CannotConnect from err

    return {"title": f"Blaueis AC ({host})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Blaueis Midea AC."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step — gateway connection details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries for same host:port
            self._async_abort_entries_match(
                {CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]}
            )

            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during setup")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""
