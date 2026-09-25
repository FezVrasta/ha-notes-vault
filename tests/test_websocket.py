"""The websocket commands behind the note editor and the Notes panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.notes_vault.manager import NotesVault


async def test_panel_round_trip(
    hass: HomeAssistant,
    home: dict,
    manager: NotesVault,
    hass_ws_client,
    vault_dir: Path,
) -> None:
    """Create a note by path, find it, read it with links and backlinks, delete it."""
    ws = await hass_ws_client(hass)

    await ws.send_json_auto_id(
        {
            "type": "notes_vault/set",
            "path": "Projects/Lighting",
            "note": "Swap [[light.kitchen_ceiling]] for a dimmable one.",
        }
    )
    result = (await ws.receive_json())["result"]
    assert result["path"] == "Projects/Lighting.md"
    assert (vault_dir / "Projects/Lighting.md").exists()

    await ws.send_json_auto_id({"type": "notes_vault/tree"})
    notes = {n["path"]: n["name"] for n in (await ws.receive_json())["result"]["notes"]}
    assert "Projects/Lighting.md" in notes
    assert notes["Home Assistant/Entities/light.kitchen_ceiling.md"] == "Ceiling lamp"

    await ws.send_json_auto_id({"type": "notes_vault/search", "query": "dimmable"})
    results = (await ws.receive_json())["result"]["results"]
    assert [r["path"] for r in results] == ["Projects/Lighting.md"]

    await ws.send_json_auto_id(
        {
            "type": "notes_vault/get",
            "path": "Home Assistant/Entities/light.kitchen_ceiling.md",
        }
    )
    light = (await ws.receive_json())["result"]
    assert light["ha"] == {"type": "entity", "id": "light.kitchen_ceiling"}
    backlinks = sorted(light["backlinks"], key=lambda b: b["path"])
    assert backlinks == [
        {
            "path": "Home Assistant/Devices/Ceiling lamp.md",
            "name": "Ceiling lamp",
            "snippet": "entities: Ceiling lamp",
        },
        {
            "path": "Projects/Lighting.md",
            "name": None,
            "snippet": "Swap light.kitchen_ceiling for a dimmable one.",
        },
    ]

    await ws.send_json_auto_id(
        {"type": "notes_vault/delete", "path": "Projects/Lighting.md"}
    )
    assert (await ws.receive_json())["success"]
    assert not (vault_dir / "Projects/Lighting.md").exists()


async def test_paths_need_an_admin(
    hass: HomeAssistant,
    manager: NotesVault,
    hass_ws_client,
    hass_read_only_access_token,
) -> None:
    """A regular user can't browse, read or write arbitrary files."""
    ws = await hass_ws_client(hass, hass_read_only_access_token)
    for msg in (
        {"type": "notes_vault/tree"},
        {"type": "notes_vault/get", "path": "anything.md"},
        {"type": "notes_vault/set", "path": "anything.md", "note": "x"},
        {"type": "notes_vault/delete", "path": "anything.md"},
    ):
        await ws.send_json_auto_id(msg)
        response = await ws.receive_json()
        assert not response["success"], msg
        assert response["error"]["code"] == "unauthorized", msg


async def test_path_outside_vault(
    hass: HomeAssistant, manager: NotesVault, hass_ws_client
) -> None:
    """Traversal is refused."""
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(
        {"type": "notes_vault/set", "path": "../x.md", "note": "x"}
    )
    response = await ws.receive_json()
    assert response["error"]["code"] == "invalid_path"
