"""Actions for reading and writing the vault.

These are what an MCP server for Home Assistant, a script or an automation uses. Most
return response data, so an assistant can read a note, search the vault and write back
without needing file access to the Home Assistant host.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN
from .manager import NotesVault
from .vault import MARKDOWN_SUFFIX, ConflictError, InvalidPathError, NotFoundError

ATTR_ENTITY_ID = "entity_id"
ATTR_DEVICE_ID = "device_id"
ATTR_AREA_ID = "area_id"
ATTR_NOTE = "note"
ATTR_APPEND = "append"
ATTR_PATH = "path"
ATTR_CONTENT = "content"
ATTR_QUERY = "query"
ATTR_LIMIT = "limit"
ATTR_FOLDER = "folder"
ATTR_RECURSIVE = "recursive"

TARGET_SCHEMA = {
    vol.Exclusive(ATTR_ENTITY_ID, "target"): cv.entity_id,
    vol.Exclusive(ATTR_DEVICE_ID, "target"): cv.string,
    vol.Exclusive(ATTR_AREA_ID, "target"): cv.string,
}

GET_NOTE_SCHEMA = vol.Schema(TARGET_SCHEMA)
SET_NOTE_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Required(ATTR_NOTE): cv.string,
        vol.Optional(ATTR_APPEND, default=False): cv.boolean,
    }
)
READ_FILE_SCHEMA = vol.Schema({vol.Required(ATTR_PATH): cv.string})
WRITE_FILE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PATH): cv.string,
        vol.Required(ATTR_CONTENT): cv.string,
        vol.Optional(ATTR_APPEND, default=False): cv.boolean,
    }
)
DELETE_FILE_SCHEMA = vol.Schema({vol.Required(ATTR_PATH): cv.string})
LIST_FILES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_FOLDER, default=""): cv.string,
        vol.Optional(ATTR_RECURSIVE, default=False): cv.boolean,
    }
)
SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_LIMIT, default=20): vol.All(
            vol.Coerce(int), vol.Range(1, 200)
        ),
        vol.Optional(ATTR_FOLDER, default=""): cv.string,
    }
)


def _manager(hass: HomeAssistant) -> NotesVault:
    entries = hass.config_entries.async_entries(DOMAIN)
    for entry in entries:
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="not_loaded"
    )


def _target(manager: NotesVault, data: dict[str, Any]):
    return manager.resolve_target(
        entity_id=data.get(ATTR_ENTITY_ID),
        device_id=data.get(ATTR_DEVICE_ID),
        area_id=data.get(ATTR_AREA_ID),
    )


def _bad_path(path: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_path",
        translation_placeholders={"path": path},
    )


def _not_found(path: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="file_not_found",
        translation_placeholders={"path": path},
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def get_note(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        return await manager.async_get_note(_target(manager, call.data))

    async def set_note(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        result = await manager.async_set_note(
            _target(manager, call.data),
            call.data[ATTR_NOTE],
            append=call.data[ATTR_APPEND],
            source="service",
        )
        return result if call.return_response else None

    async def read_file(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        path = call.data[ATTR_PATH]
        try:
            text = await hass.async_add_executor_job(manager.vault.read_text, path)
            info = await hass.async_add_executor_job(manager.vault.stat, path)
        except InvalidPathError as err:
            raise _bad_path(path) from err
        except NotFoundError as err:
            raise _not_found(path) from err
        return {"path": info.path, "content": text, "mtime": info.mtime}

    async def write_file(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        path = call.data[ATTR_PATH]
        content = call.data[ATTR_CONTENT]

        def _write() -> bool:
            if call.data[ATTR_APPEND] and manager.vault.exists(path):
                existing = manager.vault.read_text(path)
                sep = "" if not existing or existing.endswith("\n") else "\n"
                return manager.vault.write_text(path, existing + sep + content)
            return manager.vault.write_text(path, content)

        try:
            async with manager.lock:
                created = await hass.async_add_executor_job(_write)
                if created:
                    await hass.async_add_executor_job(manager.index_file, path)
        except (InvalidPathError, ConflictError) as err:
            raise _bad_path(path) from err
        norm = manager.vault.normalize(path)
        manager.file_changed(norm, "service")
        return {"path": norm, "created": created} if call.return_response else None

    async def delete_file(call: ServiceCall) -> None:
        manager = _manager(hass)
        path = call.data[ATTR_PATH]
        try:
            async with manager.lock:
                await hass.async_add_executor_job(manager.vault.delete, path)
        except InvalidPathError as err:
            raise _bad_path(path) from err
        except NotFoundError as err:
            raise _not_found(path) from err
        manager.file_removed(manager.vault.normalize(path))

    async def list_files(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        folder = call.data[ATTR_FOLDER]

        def _list() -> list[dict[str, Any]]:
            if call.data[ATTR_RECURSIVE]:
                entries = list(manager.vault.walk(folder))
            else:
                entries = [
                    e
                    for e in manager.vault.list_dir(folder)
                    if not e.path.rsplit("/", 1)[-1].startswith(".")
                ]
            return [asdict(e) for e in entries]

        try:
            files = await hass.async_add_executor_job(_list)
        except InvalidPathError as err:
            raise _bad_path(folder) from err
        except NotFoundError as err:
            raise _not_found(folder) from err
        return {"folder": manager.vault.normalize(folder), "files": files}

    async def search(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        try:
            results = await hass.async_add_executor_job(
                lambda: manager.vault.search(
                    call.data[ATTR_QUERY],
                    limit=call.data[ATTR_LIMIT],
                    folder=call.data[ATTR_FOLDER],
                )
            )
        except InvalidPathError as err:
            raise _bad_path(call.data[ATTR_FOLDER]) from err
        for result in results:
            result["link"] = "[[" + result["path"].removesuffix(MARKDOWN_SUFFIX) + "]]"
        return {"results": results}

    async def sync(call: ServiceCall) -> ServiceResponse:
        stats = await _manager(hass).async_rescan()
        return dict(stats) if call.return_response else None

    only = SupportsResponse.ONLY
    optional = SupportsResponse.OPTIONAL
    hass.services.async_register(DOMAIN, "get_note", get_note, GET_NOTE_SCHEMA, only)
    # Everything that writes, or reads beyond a single object's note, needs an
    # administrator: the vault can hold anything, not just notes on entities.
    for name, func, schema, response in (
        ("set_note", set_note, SET_NOTE_SCHEMA, optional),
        ("read_file", read_file, READ_FILE_SCHEMA, only),
        ("write_file", write_file, WRITE_FILE_SCHEMA, optional),
        ("delete_file", delete_file, DELETE_FILE_SCHEMA, SupportsResponse.NONE),
        ("list_files", list_files, LIST_FILES_SCHEMA, only),
        ("search", search, SEARCH_SCHEMA, only),
        ("sync", sync, vol.Schema({}), optional),
    ):
        async_register_admin_service(hass, DOMAIN, name, func, schema, response)
