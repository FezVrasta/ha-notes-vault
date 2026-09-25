"""Config flow: where the vault lives, and which notes get generated."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    LabelSelector,
    LabelSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_BASE_FOLDER,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_EXCLUDE_LABELS,
    CONF_FOLDER,
    CONF_GENERATE_AREAS,
    CONF_GENERATE_DEVICES,
    CONF_GENERATE_ENTITIES,
    CONF_GENERATE_INTEGRATIONS,
    CONF_INCLUDE_CONFIG,
    CONF_INCLUDE_DIAGNOSTIC,
    CONF_INCLUDE_DISABLED,
    CONF_INCLUDE_HIDDEN,
    CONF_INCLUDE_SERVICE_DEVICES,
    CONF_WEBDAV,
    DEFAULT_FOLDER,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .vault import InvalidPathError, Vault

#: Top-level folders of the config directory that Home Assistant owns. `www` is
#: served without authentication at /local/, so a vault there would be public.
RESERVED_FOLDERS = frozenset(
    {"www", "custom_components", "deps", "blueprints", "tts", "themes", "backups"}
)


def _folder_error(value: str) -> str | None:
    """Return why a vault folder can't be used, or None if it can."""
    try:
        folder = Vault.normalize(value)
    except InvalidPathError:
        return "invalid_folder"
    if not folder or folder.startswith("."):
        return "invalid_folder"
    if folder.split("/", 1)[0].lower() in RESERVED_FOLDERS:
        return "reserved_folder"
    return None


class NotesVaultConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the folder for the vault."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _folder_error(user_input[CONF_FOLDER]):
                errors[CONF_FOLDER] = error
            else:
                return self.async_create_entry(
                    title="Notes Vault",
                    data={CONF_FOLDER: Vault.normalize(user_input[CONF_FOLDER])},
                    options=dict(DEFAULT_OPTIONS),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_FOLDER, default=DEFAULT_FOLDER): TextSelector()}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NotesVaultOptionsFlow:
        """Return the options flow."""
        return NotesVaultOptionsFlow()


class NotesVaultOptionsFlow(OptionsFlow):
    """Which notes get generated, and whether WebDAV is on."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            base = ""
            try:
                base = Vault.normalize(user_input.get(CONF_BASE_FOLDER, ""))
            except InvalidPathError:
                errors[CONF_BASE_FOLDER] = "invalid_folder"
            if not errors:
                return self.async_create_entry(
                    data={**DEFAULT_OPTIONS, **user_input, CONF_BASE_FOLDER: base}
                )

        ent_reg = er.async_get(self.hass)
        domains = sorted(
            {e.domain for e in ent_reg.entities.values()}
            | {s.domain for s in self.hass.states.async_all()}
        )
        integrations = sorted({e.platform for e in ent_reg.entities.values()})

        def multi(options: list[str]) -> SelectSelector:
            return SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    sort=True,
                )
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_BASE_FOLDER): TextSelector(),
                vol.Required(CONF_GENERATE_ENTITIES): BooleanSelector(),
                vol.Required(CONF_GENERATE_DEVICES): BooleanSelector(),
                vol.Required(CONF_GENERATE_AREAS): BooleanSelector(),
                vol.Required(CONF_GENERATE_INTEGRATIONS): BooleanSelector(),
                vol.Required(CONF_INCLUDE_DIAGNOSTIC): BooleanSelector(),
                vol.Required(CONF_INCLUDE_CONFIG): BooleanSelector(),
                vol.Required(CONF_INCLUDE_HIDDEN): BooleanSelector(),
                vol.Required(CONF_INCLUDE_DISABLED): BooleanSelector(),
                vol.Required(CONF_INCLUDE_SERVICE_DEVICES): BooleanSelector(),
                vol.Optional(CONF_EXCLUDE_DOMAINS): multi(domains),
                vol.Optional(CONF_EXCLUDE_INTEGRATIONS): multi(integrations),
                vol.Optional(CONF_EXCLUDE_LABELS): LabelSelector(
                    LabelSelectorConfig(multiple=True)
                ),
                vol.Optional(CONF_EXCLUDE_DEVICES): DeviceSelector(
                    DeviceSelectorConfig(multiple=True)
                ),
                vol.Optional(CONF_EXCLUDE_ENTITIES): EntitySelector(
                    EntitySelectorConfig(multiple=True)
                ),
                vol.Required(CONF_WEBDAV): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {**DEFAULT_OPTIONS, **self.config_entry.options, **(user_input or {})},
            ),
            errors=errors,
        )
