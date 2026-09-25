"""Websocket commands used by the note editor in the Home Assistant UI."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_WEBDAV, DAV_COLLECTION, DAV_URL, DOMAIN
from .manager import NotesVault

_TARGET = {
    vol.Exclusive("entity_id", "target"): str,
    vol.Exclusive("device_id", "target"): str,
    vol.Exclusive("area_id", "target"): str,
}


def _manager(hass: HomeAssistant) -> NotesVault | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the commands."""
    websocket_api.async_register_command(hass, ws_info)
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_set)
    websocket_api.async_register_command(hass, ws_template)


@websocket_api.websocket_command({vol.Required("type"): "notes_vault/info"})
@callback
def ws_info(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tell the frontend whether the vault is up and where WebDAV lives."""
    manager = _manager(hass)
    connection.send_result(
        msg["id"],
        {
            "loaded": manager is not None,
            "can_edit": connection.user.is_admin,
            "webdav_url": f"{DAV_URL}/{DAV_COLLECTION}"
            if manager and manager.options[CONF_WEBDAV]
            else None,
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "notes_vault/get", **_TARGET})
@websocket_api.async_response
async def ws_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the note of an entity, device or area."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    try:
        key = manager.resolve_target(
            entity_id=msg.get("entity_id"),
            device_id=msg.get("device_id"),
            area_id=msg.get("area_id"),
        )
        result = await manager.async_get_note(key)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): "notes_vault/set", vol.Required("note"): str, **_TARGET}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Replace the note of an entity, device or area."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    try:
        key = manager.resolve_target(
            entity_id=msg.get("entity_id"),
            device_id=msg.get("device_id"),
            area_id=msg.get("area_id"),
        )
        result = await manager.async_set_note(key, msg["note"], source="ui")
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "notes_vault/template",
        vol.Optional("name"): vol.Any(str, None),
        **_TARGET,
    }
)
@websocket_api.async_response
async def ws_template(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Render a template for an object and list the ones that could apply to it."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    try:
        key = manager.resolve_target(
            entity_id=msg.get("entity_id"),
            device_id=msg.get("device_id"),
            area_id=msg.get("area_id"),
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    connection.send_result(
        msg["id"],
        {
            "template": await manager.async_template(key, msg.get("name")),
            "templates": [t["name"] for t in await manager.async_templates(key[0])],
        },
    )
