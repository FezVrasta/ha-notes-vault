"""Automations, scripts and scenes: their own folders, and links to what they touch."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.vault import parse_note

BASE = "Home Assistant"


async def test_logic_notes(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Each gets a folder of its own, its description and links to what it uses."""
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "night_light",
                "alias": "Night light",
                "description": "Dim the kitchen at night.",
                "mode": "restart",
                "triggers": [{"trigger": "event", "event_type": "night"}],
                "actions": [
                    {
                        "action": "light.turn_on",
                        "target": {"entity_id": "light.kitchen_ceiling"},
                    },
                    {"action": "light.turn_on", "target": {"area_id": home["area"].id}},
                ],
            }
        },
    )
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "lamp_off": {
                    "alias": "Lamp off",
                    "sequence": [
                        {
                            "action": "light.turn_off",
                            "target": {"device_id": home["device"].id},
                        }
                    ],
                }
            }
        },
    )
    assert await async_setup_component(
        hass,
        "scene",
        {"scene": [{"name": "Dinner", "entities": {"light.kitchen_ceiling": "on"}}]},
    )
    await hass.async_block_till_done()
    await manager.async_sync()

    auto = parse_note(
        (vault_dir / f"{BASE}/Automations/automation.night_light.md").read_text()
    ).frontmatter
    assert auto["name"] == "Night light"
    assert auto["description"] == "Dim the kitchen at night."
    assert auto["mode"] == "restart"
    assert auto["entities"] == [
        f"[[{BASE}/Entities/light.kitchen_ceiling|Ceiling lamp]]"
    ]
    assert auto["areas"] == [f"[[{BASE}/Areas/Kitchen|Kitchen]]"]

    script = parse_note(
        (vault_dir / f"{BASE}/Scripts/script.lamp_off.md").read_text()
    ).frontmatter
    assert script["devices"] == [f"[[{BASE}/Devices/Ceiling lamp|Ceiling lamp]]"]

    scene = (vault_dir / f"{BASE}/Scenes/scene.dinner.md").read_text()
    assert "## What it sets" in scene
    assert f"[[{BASE}/Entities/light.kitchen_ceiling|Ceiling lamp]]" in scene

    assert not (vault_dir / f"{BASE}/Entities/automation.night_light.md").exists()


async def test_existing_notes_move_to_their_folder(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """Notes generated before the folders existed move, and links follow."""
    hass.states.async_set("script.old", "off", {"friendly_name": "Old"})
    await manager.async_sync()
    moved = vault_dir / f"{BASE}/Scripts/script.old.md"
    assert moved.exists()

    # Put it back where earlier versions wrote it, with a link to it by path.
    legacy = vault_dir / f"{BASE}/Entities/script.old.md"
    legacy.parent.mkdir(exist_ok=True)
    moved.rename(legacy)
    moved.parent.rmdir()  # An install from before the folder existed.
    (vault_dir / "Log.md").write_text(f"Ran [[{BASE}/Entities/script.old]].\n")
    await manager.async_rescan()

    assert moved.exists()
    assert not legacy.exists()
    assert (vault_dir / "Log.md").read_text() == f"Ran [[{BASE}/Scripts/script.old]].\n"
