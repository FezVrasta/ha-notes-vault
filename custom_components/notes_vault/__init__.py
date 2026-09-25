"""Notes Vault: notes on entities and devices, stored as an Obsidian-friendly vault."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_FOLDER,
    DEFAULT_FOLDER,
    DOMAIN,
    FRONTEND_SCRIPT,
    FRONTEND_URL,
    PANEL_URL,
)
from .manager import NotesVault
from .services import async_setup_services
from .vault import Vault
from .webdav import NotesVaultDavView
from .websocket import async_setup_websocket

type NotesVaultConfigEntry = ConfigEntry[NotesVault]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

FRONTEND_DIR = Path(__file__).parent / "frontend"


def _script_url() -> str:
    # The mtime busts the browser cache whenever an update ships a new script.
    version = int((FRONTEND_DIR / FRONTEND_SCRIPT).stat().st_mtime)
    return f"{FRONTEND_URL}/{FRONTEND_SCRIPT}?v={version}"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register what exists once, whatever the entries do."""
    async_setup_services(hass)
    async_setup_websocket(hass)
    hass.http.register_view(NotesVaultDavView(hass))
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NotesVaultConfigEntry) -> bool:
    """Open the vault and start generating notes."""
    folder = entry.data.get(CONF_FOLDER, DEFAULT_FOLDER)
    manager = NotesVault(hass, Vault(Path(hass.config.path(folder))), entry.options)
    entry.runtime_data = manager

    script = await hass.async_add_executor_job(_script_url)
    add_extra_js_url(hass, script)
    entry.async_on_unload(lambda: remove_extra_js_url(hass, script))
    # The sidebar panel. Same script URL as above, so the browser evaluates it once.
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="notes-vault-panel",
        sidebar_title="Notes",
        sidebar_icon="mdi:notebook-outline",
        module_url=script,
        require_admin=True,
    )
    entry.async_on_unload(lambda: frontend.async_remove_panel(hass, PANEL_URL))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    async def _start(_event: Event | None = None) -> None:
        await manager.async_start()

    # Registries are complete only once every integration has set up. Starting
    # earlier would delete the notes of entities that simply have not loaded yet.
    if hass.state is CoreState.running:
        await _start()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start)
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NotesVaultConfigEntry) -> bool:
    """Stop following registry changes."""
    await entry.runtime_data.async_stop()
    return True


async def _async_reload_entry(
    hass: HomeAssistant, entry: NotesVaultConfigEntry
) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)
