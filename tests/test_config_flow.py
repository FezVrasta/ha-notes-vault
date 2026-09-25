"""The config and options flows."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notes_vault.const import (
    CONF_BASE_FOLDER,
    CONF_EXCLUDE_DOMAINS,
    CONF_FOLDER,
    CONF_INCLUDE_DIAGNOSTIC,
    DEFAULT_OPTIONS,
    DOMAIN,
)


async def test_user_flow(hass: HomeAssistant) -> None:
    """The folder is normalised and the default filters are stored as options."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FOLDER: "../outside"}
    )
    assert result["errors"] == {CONF_FOLDER: "invalid_folder"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FOLDER: "notes/vault/"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_FOLDER: "notes/vault"}
    assert result["options"] == DEFAULT_OPTIONS


async def test_single_instance(hass: HomeAssistant) -> None:
    """There is only ever one vault."""
    MockConfigEntry(domain=DOMAIN, data={CONF_FOLDER: "notes_vault"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Cleared lists fall back to empty, and the rest is stored as given."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_FOLDER: "notes_vault"}, options=DEFAULT_OPTIONS
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    user_input = {
        key: value
        for key, value in DEFAULT_OPTIONS.items()
        if not isinstance(value, list)
    }
    user_input |= {
        CONF_BASE_FOLDER: "HA/",
        CONF_INCLUDE_DIAGNOSTIC: True,
        CONF_EXCLUDE_DOMAINS: ["update"],
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_BASE_FOLDER] == "HA"
    assert entry.options[CONF_INCLUDE_DIAGNOSTIC] is True
    assert entry.options[CONF_EXCLUDE_DOMAINS] == ["update"]
