"""Config flow for Blaueis Midea AC integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_FMF_ENABLED,
    CONF_FMF_GUARD_TEMP_MAX,
    CONF_FMF_GUARD_TEMP_MIN,
    CONF_FMF_SAFETY_TIMEOUT,
    CONF_FMF_SENSOR,
    CONF_PSK,
    DOMAIN,
)

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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        return OptionsFlowHandler(config_entry)

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


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow — configure Follow Me Function."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_FMF_ENABLED,
                    default=opts.get(CONF_FMF_ENABLED, False),
                ): bool,
                vol.Optional(
                    CONF_FMF_SENSOR,
                    default=opts.get(CONF_FMF_SENSOR, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="temperature",
                    )
                ),
                vol.Optional(
                    CONF_FMF_GUARD_TEMP_MIN,
                    default=opts.get(CONF_FMF_GUARD_TEMP_MIN, -15.0),
                ): vol.All(vol.Coerce(float), vol.Range(min=-40, max=10)),
                vol.Optional(
                    CONF_FMF_GUARD_TEMP_MAX,
                    default=opts.get(CONF_FMF_GUARD_TEMP_MAX, 40.0),
                ): vol.All(vol.Coerce(float), vol.Range(min=25, max=50)),
                vol.Optional(
                    CONF_FMF_SAFETY_TIMEOUT,
                    default=opts.get(CONF_FMF_SAFETY_TIMEOUT, 300),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""
