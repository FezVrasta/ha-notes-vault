"""Links that keep the graph connected: integration notes and what helpers are built from."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notes_vault.const import (
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_GENERATE_INTEGRATIONS,
    DEFAULT_OPTIONS,
)
from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.vault import parse_note

BASE = "Home Assistant"
LAMP = f"[[{BASE}/Entities/light.kitchen_ceiling|Ceiling lamp]]"


def frontmatter(vault_dir: Path, path: str) -> dict:
    """Return the frontmatter of a note."""
    return parse_note((vault_dir / f"{path}.md").read_text()).frontmatter


async def test_integration_note_links_devices_and_deviceless_entities(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A device without an area, and an entity without a device, meet at the integration."""
    entry = MockConfigEntry(domain="shelly")
    entry.add_to_hass(hass)
    repo = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("shelly", "1")},
        name="Garden relay",
    )
    # Its only entity is a configuration entity, so it has no note of its own and
    # the device would otherwise link to nothing.
    er.async_get(hass).async_get_or_create(
        "update",
        "shelly",
        "1-update",
        device_id=repo.id,
        config_entry=entry,
        entity_category=er.EntityCategory.CONFIG,
    )
    loose = er.async_get(hass).async_get_or_create(
        "sensor",
        "shelly",
        "cloud",
        config_entry=entry,
        suggested_object_id="shelly_cloud",
    )
    hass.states.async_set(loose.entity_id, "0")
    await manager.async_sync()

    shelly = frontmatter(vault_dir, f"{BASE}/Integrations/Shelly")
    assert shelly["ha_type"] == "integration"
    assert shelly["ha_id"] == "shelly"
    assert shelly["devices"] == [f"[[{BASE}/Devices/Garden relay|Garden relay]]"]
    assert shelly["entities"] == [
        f"[[{BASE}/Entities/sensor.shelly_cloud|shelly cloud]]"
    ]
    assert shelly["ha_url"].endswith("/config/integrations/integration/shelly")

    # Entities of a device reach the integration through the device, so the
    # integration doesn't list the lamp, only its device.
    hue = frontmatter(vault_dir, f"{BASE}/Integrations/Philips Hue")
    assert hue["devices"] == [f"[[{BASE}/Devices/Ceiling lamp|Ceiling lamp]]"]
    assert "entities" not in hue

    target = manager.ha_target(f"{BASE}/Integrations/Shelly.md")
    assert target == {"type": "integration", "id": "shelly"}


async def test_group_members_are_linked(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """An entity naming others in its attributes links to them."""
    hass.states.async_set(
        "light.kitchen_all",
        "on",
        {"entity_id": ["light.kitchen_ceiling"], "friendly_name": "Kitchen lights"},
    )
    await manager.async_sync()

    group = frontmatter(vault_dir, f"{BASE}/Entities/light.kitchen_all")
    assert group["entities"] == [LAMP]


async def test_template_entity_links_what_it_reads(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A template sensor links to the entities its templates read."""
    assert await async_setup_component(
        hass,
        "template",
        {
            "template": [
                {
                    "sensor": [
                        {
                            "name": "Kitchen summary",
                            "unique_id": "kitchen_summary",
                            "state": "{{ states.light.kitchen_ceiling.state }}",
                        }
                    ]
                }
            ]
        },
    )
    await hass.async_block_till_done()
    await manager.async_sync()

    summary = frontmatter(vault_dir, f"{BASE}/Entities/sensor.kitchen_summary")
    assert summary["entities"] == [LAMP]


async def test_helper_links_its_source(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A helper set up from the UI links to the entities in its options."""
    entry = MockConfigEntry(
        domain="min_max",
        options={"entity_ids": ["light.kitchen_ceiling"], "type": "max"},
    )
    entry.add_to_hass(hass)
    helper = er.async_get(hass).async_get_or_create(
        "sensor",
        "min_max",
        "brightest",
        config_entry=entry,
        suggested_object_id="brightest",
    )
    hass.states.async_set(helper.entity_id, "1")
    await manager.async_sync()

    brightest = frontmatter(vault_dir, f"{BASE}/Entities/sensor.brightest")
    assert brightest["entities"] == [LAMP]


async def test_automation_links_entities_read_in_templates(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """An entity only read inside a template still counts as touched."""
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "lamp_check",
                "alias": "Lamp check",
                "triggers": [{"trigger": "event", "event_type": "check"}],
                "conditions": [
                    {
                        "condition": "template",
                        "value_template": "{{ is_state('light.kitchen_ceiling', 'on') }}",
                    }
                ],
                "actions": [],
            }
        },
    )
    await hass.async_block_till_done()
    await manager.async_sync()

    auto = frontmatter(vault_dir, f"{BASE}/Automations/automation.lamp_check")
    assert auto["entities"] == [LAMP]


@pytest.mark.parametrize(
    "options",
    [
        {**DEFAULT_OPTIONS, CONF_GENERATE_INTEGRATIONS: False},
        {**DEFAULT_OPTIONS, CONF_EXCLUDE_INTEGRATIONS: ["hue"]},
    ],
    ids=["disabled", "excluded"],
)
async def test_no_integration_note(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Integration notes can be turned off, and an excluded integration gets none."""
    await manager.async_sync()
    assert not (vault_dir / f"{BASE}/Integrations/Philips Hue.md").exists()
