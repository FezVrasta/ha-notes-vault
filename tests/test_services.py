"""The actions an assistant uses through a Home Assistant MCP server."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.notes_vault.const import DOMAIN
from custom_components.notes_vault.manager import NotesVault


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def test_note_by_entity(
    hass: HomeAssistant, home: dict, manager: NotesVault
) -> None:
    """Set, append and read back an entity's note."""
    await _call(hass, "set_note", entity_id="light.kitchen_ceiling", note="First.")
    await _call(
        hass, "set_note", entity_id="light.kitchen_ceiling", note="Second.", append=True
    )
    result = await _call(hass, "get_note", entity_id="light.kitchen_ceiling")
    assert result["note"] == "First.\n\nSecond."
    assert result["path"] == "Home Assistant/Entities/light.kitchen_ceiling.md"
    assert (
        result["link"]
        == "[[Home Assistant/Entities/light.kitchen_ceiling|light.kitchen_ceiling]]"
    )
    assert result["frontmatter"]["entity_id"] == "light.kitchen_ceiling"


async def test_note_by_device_and_area(
    hass: HomeAssistant, home: dict, manager: NotesVault
) -> None:
    """Devices and areas take notes too."""
    await _call(hass, "set_note", device_id=home["device"].id, note="Signify, 2021.")
    result = await _call(hass, "get_note", device_id=home["device"].id)
    assert result["note"] == "Signify, 2021."
    result = await _call(hass, "get_note", area_id=home["area"].id)
    assert result["path"] == "Home Assistant/Areas/Kitchen.md"


async def test_unknown_target(hass: HomeAssistant, manager: NotesVault) -> None:
    """A missing entity is the caller's mistake, not a crash."""
    with pytest.raises(Exception, match="light.nope"):
        await _call(hass, "get_note", entity_id="light.nope")


async def test_files_and_search(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Free-form notes: write, list, search, read and delete."""
    await _call(
        hass,
        "write_file",
        path="Projects/Irrigation.md",
        content="Valve on [[switch.garden]] leaks.\n",
    )
    assert (vault_dir / "Projects/Irrigation.md").exists()

    listing = await _call(hass, "list_files", folder="Projects")
    assert [f["path"] for f in listing["files"]] == ["Projects/Irrigation.md"]

    found = await _call(hass, "search", query="valve leaks")
    assert found["results"][0]["path"] == "Projects/Irrigation.md"
    assert found["results"][0]["link"] == "[[Projects/Irrigation]]"

    read = await _call(hass, "read_file", path="Projects/Irrigation.md")
    assert read["content"].startswith("Valve")

    await hass.services.async_call(
        DOMAIN, "delete_file", {"path": "Projects"}, blocking=True
    )
    assert not (vault_dir / "Projects").exists()


async def test_file_paths_are_checked(hass: HomeAssistant, manager: NotesVault) -> None:
    """Nothing outside the vault can be read or written."""
    with pytest.raises(ServiceValidationError):
        await _call(hass, "read_file", path="../secrets.yaml")
    with pytest.raises(ServiceValidationError):
        await _call(hass, "write_file", path="../x.md", content="x")
    with pytest.raises(ServiceValidationError):
        await _call(hass, "read_file", path="missing.md")
