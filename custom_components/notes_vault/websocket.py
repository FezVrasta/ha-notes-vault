"""Websocket commands used by the note editor in the Home Assistant UI."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from .const import CONF_WEBDAV, DAV_COLLECTION, DAV_URL, DOMAIN
from .manager import NotesVault
from .vault import VaultError

_TARGET = {
    vol.Exclusive("entity_id", "target"): str,
    vol.Exclusive("device_id", "target"): str,
    vol.Exclusive("area_id", "target"): str,
}
#: Notes by path are anything in the vault, so only administrators get to them.
_TARGET_OR_PATH = {**_TARGET, vol.Exclusive("path", "target"): str}


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
    websocket_api.async_register_command(hass, ws_tree)
    websocket_api.async_register_command(hass, ws_search)
    websocket_api.async_register_command(hass, ws_delete)


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


@websocket_api.websocket_command(
    {vol.Required("type"): "notes_vault/get", **_TARGET_OR_PATH}
)
@websocket_api.async_response
async def ws_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the note of an entity, device or area, or any note by path."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    if "path" in msg:
        if not connection.user.is_admin:
            raise Unauthorized
        try:
            connection.send_result(msg["id"], await manager.async_get_file(msg["path"]))
        except VaultError as err:
            connection.send_error(msg["id"], "invalid_path", str(err))
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
    {
        vol.Required("type"): "notes_vault/set",
        vol.Required("note"): str,
        **_TARGET_OR_PATH,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Replace the note of an entity, device or area, or of any note by path."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    if "path" in msg:
        try:
            result = await manager.async_set_file(msg["path"], msg["note"])
        except VaultError as err:
            connection.send_error(msg["id"], "invalid_path", str(err))
            return
        connection.send_result(msg["id"], result)
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


@websocket_api.websocket_command({vol.Required("type"): "notes_vault/tree"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_tree(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List every note in the vault."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    connection.send_result(msg["id"], {"notes": await manager.async_tree()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "notes_vault/search",
        vol.Required("query"): str,
        vol.Optional("limit", default=50): vol.All(int, vol.Range(1, 200)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_search(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Search the vault."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    results = await hass.async_add_executor_job(
        lambda: manager.vault.search(msg["query"], limit=msg["limit"])
    )
    connection.send_result(msg["id"], {"results": results})


@websocket_api.websocket_command(
    {vol.Required("type"): "notes_vault/delete", vol.Required("path"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a note."""
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
        return
    try:
        path = manager.vault.normalize(msg["path"])
        async with manager.lock:
            await hass.async_add_executor_job(manager.vault.delete, path)
    except VaultError as err:
        connection.send_error(msg["id"], "invalid_path", str(err))
        return
    manager.file_removed(path)
    connection.send_result(msg["id"], {"path": path})
