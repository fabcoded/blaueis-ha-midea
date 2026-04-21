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

from ._glossary_override import (
    GlossaryOverrideError,
    validate_and_parse_overrides,
)
from .const import (
    CONF_DISPLAY_BUZZER_MODE,
    CONF_FMF_ENABLED,
    CONF_FMF_GUARD_TEMP_MAX,
    CONF_FMF_GUARD_TEMP_MIN,
    CONF_FMF_SAFETY_TIMEOUT,
    CONF_FMF_SENSOR,
    CONF_GLOSSARY_OVERRIDES,
    CONF_PSK,
    DISPLAY_BUZZER_MODE_DEFAULT,
    DISPLAY_BUZZER_POLICIES,
    DISPLAY_BUZZER_POLICY_NON_ENFORCED,
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
    """Single-step options flow.

    The glossary-override YAML is parsed and schema-validated on submit
    via ``validate_and_parse_overrides`` (G3). Failure surfaces as an
    in-form error with the line/column or JSON-pointer path of the
    problem; success saves immediately and HA reloads the entry.

    Confirmation feedback arrives via three out-of-band channels:
    1. The integration logs an INFO line on save listing the affected
       leaf paths.
    2. Entities reflecting the override (e.g. cap-gated entities going
       ``unavailable``) update within ~2 s of the entry reload.
    3. The diagnostics download includes the ``glossary_override``
       block for offline inspection.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate glossary override BEFORE saving. Bad YAML or schema
            # rejections abort the save and re-show the form with errors.
            override_text = user_input.get(CONF_GLOSSARY_OVERRIDES, "") or ""
            try:
                _, affected, warnings = validate_and_parse_overrides(
                    override_text
                )
            except GlossaryOverrideError as err:
                errors[CONF_GLOSSARY_OVERRIDES] = "invalid_override"
                _LOGGER.warning("Glossary override rejected: %s", err)
                # Fall through to re-show the form with the error message
                # in the description placeholder.
                return self._show_init_form(
                    user_input=user_input,
                    errors=errors,
                    extra_description=str(err),
                )

            # Override (if any) is valid. Log a one-line summary so the
            # user can confirm via HA logs what was applied (the
            # confirmation form approach hit a HA flow-data-filtering
            # quirk that stripped options to empty between the form and
            # storage). Save directly.
            if affected:
                _LOGGER.info(
                    "Glossary override accepted: %d leaf path(s) affected (%s)",
                    len(affected),
                    ", ".join(affected[:5]) + ("…" if len(affected) > 5 else ""),
                )
            for w in warnings:
                _LOGGER.info("Glossary override warning: %s", w)
            # See docs/ha_config_flow_gotchas.md §1: async_create_entry
            # REPLACES options. Merging preserves fields hidden by
            # cap-gating (e.g. display_buzzer_mode when an override has
            # force-off'd screen_display) so the policy survives the
            # cap-hidden cycle.
            new_options = {**self._config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        return self._show_init_form()

    def _show_init_form(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        extra_description: str | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Render the init form. Used both on first show and on validation
        failure (where ``errors`` and ``extra_description`` carry the
        error context to the user)."""
        opts = self._config_entry.options

        # Display & Buzzer mode is cap-gated. When the connected AC
        # advertises `screen_display`, all three policies are selectable
        # and the field appears in the form. When the cap is absent
        # (real device limitation OR user-supplied glossary override
        # that force-offs `screen_display`), the field is omitted
        # entirely. Mirrors the entity-on-controls-card behaviour: no
        # cap → no entity → no policy field. The Advanced YAML field
        # stays visible regardless so the user can always clear an
        # override that's currently hiding the cap.
        #
        # See docs/ha_config_flow_gotchas.md §3 for why "show the field
        # but lock to current value" (Path B) is broken — voluptuous
        # treats single-option SelectSelector as an enum constraint and
        # rejects ANY submit that disagrees, deadlocking the form.
        coord = getattr(self._config_entry, "runtime_data", None)
        cap_available = (
            coord is not None
            and "screen_display" in coord.device.available_fields
        )
        current_dbm = opts.get(
            CONF_DISPLAY_BUZZER_MODE, DISPLAY_BUZZER_MODE_DEFAULT
        )
        if current_dbm not in DISPLAY_BUZZER_POLICIES:
            current_dbm = DISPLAY_BUZZER_POLICY_NON_ENFORCED

        schema_dict: dict = {
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
        if cap_available:
            # Display & Buzzer mode — persisted default. The select
            # entity on the device's control page also writes this
            # option live when the user picks a forced_* option.
            schema_dict[
                vol.Optional(CONF_DISPLAY_BUZZER_MODE, default=current_dbm)
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(DISPLAY_BUZZER_POLICIES),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_DISPLAY_BUZZER_MODE,
                )
            )
        # Advanced — glossary overrides (multiline YAML).
        # Stored verbatim; parsed and schema-validated on save
        # via _glossary_override.validate_and_parse_overrides.
        # See docs/ha_config_flow_gotchas.md §2: the default MUST be the
        # stored value or "" — never a non-empty placeholder. Voluptuous
        # Optional with a non-empty default substitutes back on empty
        # submissions, making the field impossible to clear via the UI.
        schema_dict[
            vol.Optional(
                CONF_GLOSSARY_OVERRIDES,
                default=opts.get(CONF_GLOSSARY_OVERRIDES, ""),
            )
        ] = selector.TextSelector(
            selector.TextSelectorConfig(
                multiline=True,
                type=selector.TextSelectorType.TEXT,
            )
        )
        schema = vol.Schema(schema_dict)
        # See docs/ha_config_flow_gotchas.md §5: every placeholder
        # referenced in strings.json's description MUST be supplied,
        # even on the happy path. Missing keys → "invalid flow
        # configured" and the form never opens.
        placeholders: dict[str, str] = {
            "override_error": extra_description or "",
        }
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors or {},
            description_placeholders=placeholders,
        )



class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""
