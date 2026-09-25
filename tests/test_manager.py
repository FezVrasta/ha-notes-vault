"""Generating notes from the registries, and keeping the user's writing safe."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)

from custom_components.notes_vault.const import (
    KIND_DEVICE,
    KIND_ENTITY,
)
from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.vault import parse_note, render_note

ENTITIES = "Home Assistant/Entities"
DEVICES = "Home Assistant/Devices"
AREAS = "Home Assistant/Areas"


def _read(vault_dir: Path, path: str):
    return parse_note((vault_dir / path).read_text())


async def test_generates_linked_notes(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Entities, devices and areas get notes that link to each other."""
    light = _read(vault_dir, f"{ENTITIES}/light.kitchen_ceiling.md")
    assert light.body == ""
    fm = light.frontmatter
    assert fm["ha_type"] == "entity"
    assert fm["ha_id"] == home["light"].id
    # `name` is what the Front Matter Title plugin is set to show instead of the file name.
    assert fm["name"] == "Ceiling lamp"
    assert fm["device"] == f"[[{DEVICES}/Ceiling lamp|Ceiling lamp]]"
    assert fm["area"] == f"[[{AREAS}/Kitchen|Kitchen]]"
    assert "Ceiling lamp" in fm["aliases"]
    assert fm["tags"] == ["Home-Assistant/Entity", "Home-Assistant/Entity/Light"]

    device = _read(vault_dir, f"{DEVICES}/Ceiling lamp.md").frontmatter
    assert device["manufacturer"] == "Signify"
    assert device["tags"] == [
        "Home-Assistant/Device",
        "Home-Assistant/Device/Philips-Hue",
    ]
    assert device["entities"] == [f"[[{ENTITIES}/light.kitchen_ceiling|Ceiling lamp]]"]

    area = _read(vault_dir, f"{AREAS}/Kitchen.md").frontmatter
    assert area["devices"] == [f"[[{DEVICES}/Ceiling lamp|Ceiling lamp]]"]

    # Diagnostic entities are skipped by default.
    assert not (vault_dir / f"{ENTITIES}/sensor.kitchen_ceiling_rssi.md").exists()


async def test_note_survives_regeneration(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """The body and any frontmatter the user added are never touched."""
    path = vault_dir / f"{ENTITIES}/light.kitchen_ceiling.md"
    note = parse_note(path.read_text())
    fm = {
        **note.frontmatter,
        "bulb": "E27",
        # A tag of the user's, and one from before tags were renamed.
        "tags": [*note.frontmatter["tags"], "mine", "ha/light"],
    }
    path.write_text(render_note(fm, "Replaced 2026-01-10.\n"))

    er.async_get(hass).async_update_entity(home["light"].entity_id, name="Main light")
    await manager.async_sync()

    note = parse_note(path.read_text())
    assert note.body == "Replaced 2026-01-10.\n"
    assert note.frontmatter["bulb"] == "E27"
    assert "mine" in note.frontmatter["tags"]
    assert "ha/light" not in note.frontmatter["tags"]
    assert note.frontmatter["name"] == "Main light"


async def test_unchanged_files_are_not_rewritten(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A sync with nothing to change leaves every file alone (and sync clients calm)."""
    stats = await manager.async_sync()
    assert stats["created"] == stats["updated"] == stats["deleted"] == 0


async def test_entity_rename_moves_file_and_links(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Renaming an entity ID renames its note and rewrites links to it."""
    (vault_dir / "Kitchen.md").write_text("The [[light.kitchen_ceiling]] flickers.\n")
    await manager.async_set_note((KIND_ENTITY, home["light"].id), "Needs a new driver.")

    er.async_get(hass).async_update_entity(
        home["light"].entity_id, new_entity_id="light.kitchen_main"
    )
    # Home Assistant moves the state along with the ID.
    hass.states.async_remove("light.kitchen_ceiling")
    await manager.async_sync()

    assert not (vault_dir / f"{ENTITIES}/light.kitchen_ceiling.md").exists()
    moved = _read(vault_dir, f"{ENTITIES}/light.kitchen_main.md")
    assert moved.body == "Needs a new driver.\n"
    assert moved.frontmatter["entity_id"] == "light.kitchen_main"
    assert (
        vault_dir / "Kitchen.md"
    ).read_text() == "The [[light.kitchen_main]] flickers.\n"


async def test_device_rename(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A device renamed in Home Assistant gets its note renamed and the old alias dropped."""
    dr.async_get(hass).async_update_device(
        home["device"].id, name_by_user="Island lamp"
    )
    await manager.async_sync()
    fm = _read(vault_dir, f"{DEVICES}/Island lamp.md").frontmatter
    assert fm["aliases"] == ["Island lamp"]
    assert not (vault_dir / f"{DEVICES}/Ceiling lamp.md").exists()
    light = _read(vault_dir, f"{ENTITIES}/light.kitchen_ceiling.md").frontmatter
    assert light["device"] == f"[[{DEVICES}/Island lamp|Island lamp]]"


async def test_moved_note_is_followed(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A note the user moved elsewhere stays there instead of being duplicated."""
    src = vault_dir / f"{DEVICES}/Ceiling lamp.md"
    (vault_dir / "Mine").mkdir()
    src.rename(vault_dir / "Mine/Lamp.md")
    await manager.async_rescan()
    assert not src.exists()
    assert (
        _read(vault_dir, "Mine/Lamp.md").frontmatter["device_id"] == home["device"].id
    )


async def test_removed_entity(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """An empty note goes with its entity; a written one stays, marked as removed."""
    await manager.async_set_note(
        (KIND_DEVICE, home["device"].id), "Warranty until 2028."
    )
    er.async_get(hass).async_remove(home["light"].entity_id)
    hass.states.async_remove(home["light"].entity_id)
    dr.async_get(hass).async_remove_device(home["device"].id)
    await manager.async_sync()

    assert not (vault_dir / f"{ENTITIES}/light.kitchen_ceiling.md").exists()
    device = _read(vault_dir, f"{DEVICES}/Ceiling lamp.md")
    assert device.frontmatter["ha_removed"] is True
    assert device.body == "Warranty until 2028.\n"


async def test_str_subclass_names_are_plain(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """A state-only entity whose name is a str subclass still gets a note."""

    class Name(str):
        """Stand-in for the str subclasses integrations put in states."""

        __slots__ = ()

    hass.states.async_set("sensor.odd", "1", {"friendly_name": Name("Odd one")})
    await manager.async_sync()
    fm = _read(vault_dir, f"{ENTITIES}/sensor.odd.md").frontmatter
    assert fm["aliases"] == ["Odd one"]
