"""Config flow.

Covers the four steps almost every integration ends up needing: the initial `user` step,
`reauth` for when credentials expire, `reconfigure` for when the device moves to a new
address, and an options flow. Delete the ones that do not apply -- their `strings.json`
entries too, or hassfest will complain about keys with no step behind them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import callback

from .api import ExampleAuthError, ExampleClient, ExampleError
from .const import DEFAULT_PORT, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_TOKEN): str,
    }
)


async def _validate(data: Mapping[str, Any]) -> str:
    """Connect once and return the device's stable identifier.

    The identifier -- a serial number, a MAC address, anything the device will still
    report after a factory reset of the *integration* -- becomes the config entry's
    unique ID. Using the host instead means a DHCP lease change creates a duplicate
    entry and orphans every entity.
    """
    client = ExampleClient(
        host=data[CONF_HOST], port=data[CONF_PORT], token=data.get(CONF_TOKEN)
    )
    try:
        result = await client.fetch()
    finally:
        await client.close()
    return result.serial


class ExampleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up a new device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                serial = await _validate(user_input)
            except ExampleAuthError:
                errors["base"] = "invalid_auth"
            except ExampleError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured(updates=dict(user_input))
                return self.async_create_entry(
                    title=user_input[CONF_HOST], data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start over when the credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh token."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                await _validate(data)
            except ExampleAuthError:
                errors["base"] = "invalid_auth"
            except ExampleError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an existing entry at a new address."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                serial = await _validate(user_input)
            except ExampleAuthError:
                errors["base"] = "invalid_auth"
            except ExampleError:
                errors["base"] = "cannot_connect"
            else:
                # Refusing a different serial is what stops someone reconfiguring an
                # entry onto a second device and silently rewriting its history.
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> ExampleOptionsFlow:
        """Return the options flow."""
        return ExampleOptionsFlow()


class ExampleOptionsFlow(OptionsFlow):
    """Settings that can change without re-validating the connection."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({}), dict(self.config_entry.options)
            ),
        )
