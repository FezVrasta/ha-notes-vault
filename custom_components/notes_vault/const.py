"""Constants for Notes Vault."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "notes_vault"

#: Folder under the Home Assistant config directory that holds the vault.
CONF_FOLDER: Final = "folder"
DEFAULT_FOLDER: Final = "notes_vault"

#: Folder inside the vault that holds the generated notes.
CONF_BASE_FOLDER: Final = "base_folder"
DEFAULT_BASE_FOLDER: Final = "Home Assistant"

CONF_GENERATE_ENTITIES: Final = "generate_entities"
CONF_GENERATE_DEVICES: Final = "generate_devices"
CONF_GENERATE_AREAS: Final = "generate_areas"
CONF_GENERATE_INTEGRATIONS: Final = "generate_integrations"
CONF_GENERATE_VIEWS: Final = "generate_views"
CONF_INCLUDE_HIDDEN: Final = "include_hidden"
CONF_INCLUDE_DISABLED: Final = "include_disabled"
CONF_INCLUDE_DIAGNOSTIC: Final = "include_diagnostic"
CONF_INCLUDE_CONFIG: Final = "include_config"
CONF_INCLUDE_SERVICE_DEVICES: Final = "include_service_devices"
CONF_EXCLUDE_DOMAINS: Final = "exclude_domains"
CONF_EXCLUDE_INTEGRATIONS: Final = "exclude_integrations"
CONF_EXCLUDE_LABELS: Final = "exclude_labels"
CONF_EXCLUDE_ENTITIES: Final = "exclude_entities"
CONF_EXCLUDE_DEVICES: Final = "exclude_devices"
CONF_WEBDAV: Final = "webdav"

DEFAULT_OPTIONS: Final = {
    CONF_BASE_FOLDER: DEFAULT_BASE_FOLDER,
    CONF_GENERATE_ENTITIES: True,
    CONF_GENERATE_DEVICES: True,
    CONF_GENERATE_AREAS: True,
    CONF_GENERATE_INTEGRATIONS: True,
    CONF_GENERATE_VIEWS: True,
    CONF_INCLUDE_HIDDEN: False,
    CONF_INCLUDE_DISABLED: False,
    CONF_INCLUDE_DIAGNOSTIC: False,
    CONF_INCLUDE_CONFIG: False,
    CONF_INCLUDE_SERVICE_DEVICES: False,
    # Feeds (earthquakes, fires, weather alerts) create and drop these by the minute.
    # A note per event is noise, and each one would be one more file to sync.
    CONF_EXCLUDE_DOMAINS: ["geo_location"],
    CONF_EXCLUDE_INTEGRATIONS: [],
    CONF_EXCLUDE_LABELS: [],
    CONF_EXCLUDE_ENTITIES: [],
    CONF_EXCLUDE_DEVICES: [],
    CONF_WEBDAV: True,
}

#: WebDAV endpoint. The vault shows up as a single collection below it, because
#: remotely-save always syncs into a named folder under the server address.
DAV_URL: Final = "/api/notes_vault/dav"
DAV_COLLECTION: Final = "vault"

FRONTEND_URL: Final = "/notes_vault_static"
FRONTEND_SCRIPT: Final = "notes-vault.js"
#: Sidebar panel with every note in the vault.
PANEL_URL: Final = "notes-vault"

#: Fired whenever a note changes through Home Assistant (UI, service or WebDAV).
EVENT_NOTE_UPDATED: Final = "notes_vault_updated"

KIND_ENTITY: Final = "entity"
KIND_DEVICE: Final = "device"
KIND_AREA: Final = "area"
KIND_INTEGRATION: Final = "integration"
#: A generated room page: a view of one area, not a note about it.
KIND_ROOM: Final = "room"

#: Generated folder for each kind of note, inside the generated notes folder.
KIND_FOLDERS: Final = {
    KIND_ENTITY: "Entities",
    KIND_DEVICE: "Devices",
    KIND_AREA: "Areas",
    KIND_INTEGRATION: "Integrations",
}
#: Entity domains with a folder of their own: the home's logic, not its sensors.
DOMAIN_FOLDERS: Final = {
    "automation": "Automations",
    "script": "Scripts",
    "scene": "Scenes",
}

#: Seconds to wait after a registry change before regenerating, so a burst of changes
#: (an integration adding fifty entities) becomes one pass over the vault.
SYNC_DEBOUNCE: Final = 5.0

#: Days a deleted note, or a replaced version of one, stays in the vault's trash.
TRASH_DAYS: Final = 30
