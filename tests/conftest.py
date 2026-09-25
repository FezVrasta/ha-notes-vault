"""Shared fixtures.

Home Assistant's own test fixtures come from `pytest-homeassistant-custom-component`,
which registers itself as a pytest plugin — so the suite needs only the installed
package, not a checkout of Home Assistant core.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notes_vault.const import (
    CONF_FOLDER,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.notes_vault.manager import NotesVault


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load this integration in every test."""


@pytest.fixture(autouse=True)
def _config_dir(hass: HomeAssistant, tmp_path: Path) -> None:
    """Keep every vault in a throwaway config directory, not the shared test one."""
    hass.config.config_dir = str(tmp_path)


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Return the folder the vault lives in."""
    return tmp_path / "notes_vault"


@pytest.fixture
def options() -> dict:
    """Options for the entry. Override in a test module to change the filters."""
    return dict(DEFAULT_OPTIONS)


@pytest.fixture
def config_entry(options: dict) -> MockConfigEntry:
    """Return a configured entry, not yet added to Home Assistant."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Notes Vault",
        data={CONF_FOLDER: "notes_vault"},
        options=options,
    )


@pytest.fixture
async def manager(
    hass: HomeAssistant, config_entry: MockConfigEntry, vault_dir: Path
) -> NotesVault:
    """Set the integration up with Home Assistant already running."""
    assert await async_setup_component(hass, "http", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry.runtime_data


ENTITIES = "Home Assistant/Entities"
DEVICES = "Home Assistant/Devices"
AREAS = "Home Assistant/Areas"


@pytest.fixture
async def home(hass: HomeAssistant) -> dict:
    """Create a kitchen with a lamp that has a light and a diagnostic sensor."""
    source = MockConfigEntry(domain="hue")
    source.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Kitchen")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("hue", "lamp-1")},
        name="Ceiling lamp",
        manufacturer="Signify",
        model="LCT015",
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    ent_reg = er.async_get(hass)
    light = ent_reg.async_get_or_create(
        "light",
        "hue",
        "lamp-1-light",
        device_id=device.id,
        config_entry=source,
        original_name="Ceiling lamp",
        suggested_object_id="kitchen_ceiling",
    )
    diag = ent_reg.async_get_or_create(
        "sensor",
        "hue",
        "lamp-1-rssi",
        device_id=device.id,
        config_entry=source,
        entity_category=EntityCategory.DIAGNOSTIC,
        original_device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        suggested_object_id="kitchen_ceiling_rssi",
    )
    hass.states.async_set(light.entity_id, "on", {"friendly_name": "Ceiling lamp"})
    return {"area": area, "device": device, "light": light, "diag": diag}
