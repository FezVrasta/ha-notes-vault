"""Websocket commands used by the note editor and the Notes panel."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from .const import CONF_WEBDAV, DAV_COLLECTION, DAV_URL
from .manager import DocKey, LockedFolderError, NotesVault, loaded_manager
from .vault import ConflictError, VaultError

_TARGET = {
    vol.Exclusive("entity_id", "target"): str,
    vol.Exclusive("device_id", "target"): str,
    vol.Exclusive("area_id", "target"): str,
}
#: Notes by path are anything in the vault, so only administrators get to them.
_TARGET_OR_PATH = {**_TARGET, vol.Exclusive("path", "target"): str}

type _Handler = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any], NotesVault],
    Awaitable[Any],
]


def _with_manager(func: _Handler) -> websocket_api.AsyncWebSocketCommandHandler:
    """Hand the handler the loaded vault, send its result, and map vault errors."""

    @wraps(func)
    async def wrapper(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        manager = loaded_manager(hass)
        if manager is None:
            connection.send_error(msg["id"], "not_loaded", "Notes Vault is not loaded")
            return
        try:
            result = await func(hass, connection, msg, manager)
        except LockedFolderError:
            connection.send_error(
                msg["id"],
                "locked",
                "This folder holds the generated notes. Change where they go in "
                "the integration's options instead.",
            )
        except ConflictError:
            connection.send_error(
                msg["id"], "exists", "A folder or note with that name already exists"
            )
        except VaultError as err:
            connection.send_error(msg["id"], "invalid_path", str(err))
        except Unauthorized:
            raise
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "not_found", str(err))
        else:
            connection.send_result(msg["id"], result)

    return wrapper


def _target(manager: NotesVault, msg: dict[str, Any]) -> DocKey:
    return manager.resolve_target(
        entity_id=msg.get("entity_id"),
        device_id=msg.get("device_id"),
        area_id=msg.get("area_id"),
    )


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the commands."""
    for command in (
        ws_info,
        ws_get,
        ws_set,
        ws_template,
        ws_tree,
        ws_search,
        ws_delete,
        ws_mkdir,
        ws_move,
    ):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command({vol.Required("type"): "notes_vault/info"})
@callback
def ws_info(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tell the frontend whether the vault is up and where WebDAV lives."""
    manager = loaded_manager(hass)
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
@_with_manager
async def ws_get(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """Return the note of an entity, device or area, or any note by path."""
    if "path" in msg:
        if not connection.user.is_admin:
            raise Unauthorized
        return await manager.async_get_file(msg["path"])
    return await manager.async_get_note(_target(manager, msg))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "notes_vault/set",
        vol.Required("note"): str,
        **_TARGET_OR_PATH,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_manager
async def ws_set(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """Replace the note of an entity, device or area, or of any note by path."""
    if "path" in msg:
        return await manager.async_set_file(msg["path"], msg["note"])
    return await manager.async_set_note(_target(manager, msg), msg["note"], source="ui")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "notes_vault/template",
        vol.Optional("name"): vol.Any(str, None),
        **_TARGET_OR_PATH,
    }
)
@websocket_api.async_response
@_with_manager
async def ws_template(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """Render a template for an object and list the ones that could apply to it."""
    if "path" in msg:
        # Only generated notes have an object to fit a template to.
        key = manager.key_for_path(msg["path"])
        if key is None:
            return {"template": None, "templates": []}
    else:
        key = _target(manager, msg)
    return {
        "template": await manager.async_template(key, msg.get("name")),
        "templates": [t["name"] for t in await manager.async_templates(key[0])],
    }


@websocket_api.websocket_command({vol.Required("type"): "notes_vault/tree"})
@websocket_api.require_admin
@websocket_api.async_response
@_with_manager
async def ws_tree(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """List every note and folder in the vault."""
    return await manager.async_tree()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "notes_vault/search",
        vol.Required("query"): str,
        vol.Optional("limit", default=50): vol.All(int, vol.Range(1, 200)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_manager
async def ws_search(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """Search the vault."""
    results = await hass.async_add_executor_job(
        lambda: manager.vault.search(
            msg["query"], limit=msg["limit"], skip=frozenset({manager.index_path})
        )
    )
    return {"results": results}


@websocket_api.websocket_command(
    {vol.Required("type"): "notes_vault/delete", vol.Required("path"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_manager
async def ws_delete(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """Delete a note or a folder."""
    await manager.async_delete(msg["path"])
    return {"path": msg["path"]}


@websocket_api.websocket_command(
    {vol.Required("type"): "notes_vault/mkdir", vol.Required("path"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_manager
async def ws_mkdir(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """Create a folder."""
    return {"path": await manager.async_mkdir(msg["path"])}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "notes_vault/move",
        vol.Required("path"): str,
        vol.Required("to"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_manager
async def ws_move(hass, connection, msg, manager: NotesVault) -> dict[str, Any]:
    """Rename or move a note or folder, rewriting the links to it."""
    return {"path": await manager.async_move(msg["path"], msg["to"])}
