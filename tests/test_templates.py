"""Note templates: seeding, picking the best fit, and filling in placeholders."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.notes_vault.const import (
    DOMAIN,
    KIND_AREA,
    KIND_DEVICE,
    KIND_ENTITY,
)
from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.templates import (
    DEFAULT_TEMPLATES,
    best_template,
    parse_template,
    render,
)
from custom_components.notes_vault.vault import Note, parse_note, render_note

TEMPLATES = "Home Assistant/Templates"


def _template(name: str, text: str):
    return parse_template(name, f"{name}.md", parse_note(text))


def test_every_default_template_parses() -> None:
    """A typo in a default template would silently drop it."""
    for name, text in DEFAULT_TEMPLATES.items():
        assert _template(name, text) is not None, name


def test_most_specific_template_wins() -> None:
    """A light template beats the entity fallback; a battery light beats both."""
    templates = [
        _template(name, text)
        for name, text in {
            "Entity": "---\nha_template:\n  applies_to: entity\n---\nany",
            "Light": "---\nha_template:\n  applies_to: entity\n  domains: [light]\n---\nlight",
            "Battery light": (
                "---\nha_template:\n  applies_to: entity\n  domains: [light]\n"
                "  device_classes: [battery]\n---\nbattery"
            ),
        }.items()
    ]
    pick = lambda facts: best_template(templates, "entity", facts).name  # noqa: E731
    assert pick({"domains": ["switch"]}) == "Entity"
    assert pick({"domains": ["light"]}) == "Light"
    assert (
        pick({"domains": ["light"], "device_classes": ["battery"]}) == "Battery light"
    )
    assert best_template(templates, "device", {}) is None


def test_not_a_template() -> None:
    """Notes without a valid ha_template block are ignored."""
    assert parse_template("x", "x.md", Note({}, "body")) is None
    assert (
        parse_template("x", "x.md", Note({"ha_template": {"applies_to": "car"}}, ""))
        is None
    )


def test_render_leaves_unknown_placeholders() -> None:
    """Obsidian's own placeholders (like {{time}}) survive for Obsidian to fill."""
    assert render("{{name}} at {{ time }}", {"name": "Lamp"}) == "Lamp at {{ time }}"


async def test_defaults_are_seeded_once(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """The defaults appear on first start; a template the user deletes stays deleted."""
    folder = vault_dir / TEMPLATES
    assert {p.stem for p in folder.glob("*.md")} == set(DEFAULT_TEMPLATES)

    (folder / "Light.md").unlink()
    await manager.async_stop()
    await manager.async_start()
    assert not (folder / "Light.md").exists()


async def test_new_default_templates_reach_existing_vaults(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path, hass_storage
) -> None:
    """A default added in an update is written; ones seeded before are left alone."""
    folder = vault_dir / TEMPLATES
    (folder / "Scene.md").unlink()
    (folder / "Light.md").unlink()
    # As if Scene shipped after this vault was seeded.
    hass_storage["notes_vault.templates"]["data"]["seeded"].remove("Scene")
    manager._templates_store._data = None
    await manager.async_stop()
    await manager.async_start()
    assert (folder / "Scene.md").exists()
    assert not (folder / "Light.md").exists()


async def test_best_template_for_each_kind(
    hass: HomeAssistant, home: dict, manager: NotesVault
) -> None:
    """Entities, devices and areas each get the template that fits them."""
    light = await manager.async_template((KIND_ENTITY, home["light"].id))
    assert light["name"] == "Light"
    assert "## Fixture" in light["body"]

    area = await manager.async_template((KIND_AREA, home["area"].id))
    assert area["name"] == "Area"


async def test_device_matches_on_its_entities(
    hass: HomeAssistant, home: dict, manager: NotesVault
) -> None:
    """A device with a battery sensor gets the battery template."""
    source = hass.config_entries.async_entries("hue")[0]
    er.async_get(hass).async_get_or_create(
        "sensor",
        "hue",
        "lamp-1-battery",
        device_id=home["device"].id,
        config_entry=source,
        original_device_class="battery",
    )
    result = await manager.async_template((KIND_DEVICE, home["device"].id))
    assert result["name"] == "Battery device"


async def test_placeholders_and_user_templates(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A template the user writes is picked up, with its placeholders filled in."""
    (vault_dir / TEMPLATES / "Hue.md").write_text(
        "---\nha_template:\n  applies_to: entity\n  domains: [light]\n"
        "  integrations: [hue]\n---\n"
        "{{name}} ({{entity_id}}) on {{device}} by {{manufacturer}} {{model}} "
        "in {{area}}, {{date}}\n"
    )
    result = await manager.async_template((KIND_ENTITY, home["light"].id))
    assert result["name"] == "Hue"
    body = result["body"]
    assert body.startswith(
        "Ceiling lamp (light.kitchen_ceiling) on Ceiling lamp by Signify LCT015 in Kitchen, "
    )
    assert "{{date}}" not in body


async def test_empty_note_offers_its_template(
    hass: HomeAssistant, home: dict, manager: NotesVault
) -> None:
    """get_note suggests a template only while the note is empty."""
    result = await hass.services.async_call(
        DOMAIN,
        "get_note",
        {"entity_id": "light.kitchen_ceiling"},
        blocking=True,
        return_response=True,
    )
    assert result["template"]["name"] == "Light"

    await manager.async_set_note((KIND_ENTITY, home["light"].id), "Written.")
    result = await hass.services.async_call(
        DOMAIN,
        "get_note",
        {"entity_id": "light.kitchen_ceiling"},
        blocking=True,
        return_response=True,
    )
    assert result["template"] is None


async def test_template_actions(
    hass: HomeAssistant, home: dict, manager: NotesVault
) -> None:
    """list_templates and get_template, by name and by best match."""
    listing = await hass.services.async_call(
        DOMAIN,
        "list_templates",
        {"applies_to": "area"},
        blocking=True,
        return_response=True,
    )
    assert [t["name"] for t in listing["templates"]] == ["Area"]

    named = await hass.services.async_call(
        DOMAIN,
        "get_template",
        {"entity_id": "light.kitchen_ceiling", "template": "Entity"},
        blocking=True,
        return_response=True,
    )
    assert named["name"] == "Entity"

    with pytest.raises(Exception, match="Nope"):
        await hass.services.async_call(
            DOMAIN,
            "get_template",
            {"entity_id": "light.kitchen_ceiling", "template": "Nope"},
            blocking=True,
            return_response=True,
        )


async def test_templates_are_not_indexed_as_notes(
    hass: HomeAssistant, home: dict, manager: NotesVault
) -> None:
    """Templates never become generated notes or targets of a sync."""
    assert not any(path.startswith(TEMPLATES) for path in manager.index.values())


async def test_untouched_template_counts_as_empty(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A generated note still holding its template reads as empty, with the template."""
    result = await manager.async_get_note((KIND_ENTITY, home["light"].id))
    assert result["note"] == ""
    assert result["template"]["name"] == "Light"
    assert result["template"]["body"].startswith("## Fixture")


async def test_template_edits_reach_untouched_notes_only(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Changing a template re-renders the notes nobody wrote in, and no others."""
    area_note = vault_dir / "Home Assistant/Areas/Kitchen.md"
    light_note = vault_dir / "Home Assistant/Entities/light.kitchen_ceiling.md"
    written = parse_note(light_note.read_text())
    light_note.write_text(
        render_note(written.frontmatter, written.body.replace("- Bulb:", "- Bulb: E27"))
    )

    (vault_dir / TEMPLATES / "Area.md").write_text(
        "---\nha_template:\n  applies_to: area\n---\n## Plants in {{name}}\n"
    )
    (vault_dir / TEMPLATES / "Light.md").write_text(
        "---\nha_template:\n  applies_to: entity\n  domains: [light]\n---\n## New\n"
    )
    await manager.async_sync()

    assert parse_note(area_note.read_text()).body == "## Plants in Kitchen\n"
    assert "- Bulb: E27" in parse_note(light_note.read_text()).body


async def test_untouched_note_is_deleted_with_its_entity(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """A pre-filled note nobody wrote in goes away with its entity."""
    er.async_get(hass).async_remove(home["light"].entity_id)
    hass.states.async_remove(home["light"].entity_id)
    await manager.async_sync()
    assert not (vault_dir / "Home Assistant/Entities/light.kitchen_ceiling.md").exists()
