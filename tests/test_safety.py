"""Nothing written to the vault is lost: stale saves fail, deletes go to the trash."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.notes_vault.const import DAV_URL, DOMAIN
from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.vault import Vault

LAMP = "light.kitchen_ceiling"


async def _call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


def _trash(vault_dir: Path) -> list[str]:
    trash = vault_dir / ".trash"
    return sorted(p.name for p in trash.iterdir()) if trash.exists() else []


async def test_stale_save_is_refused(
    hass: HomeAssistant, home: dict, manager: NotesVault, hass_ws_client
) -> None:
    """A save based on an old version fails instead of replacing a newer change."""
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id({"type": "notes_vault/get", "entity_id": LAMP})
    opened = (await ws.receive_json())["result"]

    # Something else writes while the editor is open.
    await _call(hass, "set_note", entity_id=LAMP, note="Bulb is an E27.")

    await ws.send_json_auto_id(
        {
            "type": "notes_vault/set",
            "entity_id": LAMP,
            "note": "Mine",
            "mtime": opened["mtime"],
        }
    )
    reply = await ws.receive_json()
    assert reply["error"]["code"] == "changed"

    await ws.send_json_auto_id({"type": "notes_vault/get", "entity_id": LAMP})
    current = (await ws.receive_json())["result"]
    assert current["note"] == "Bulb is an E27."

    await ws.send_json_auto_id(
        {
            "type": "notes_vault/set",
            "entity_id": LAMP,
            "note": "Mine",
            "mtime": current["mtime"],
        }
    )
    assert (await ws.receive_json())["result"]["note"] == "Mine"


async def test_new_note_created_meanwhile_is_not_overwritten(
    hass: HomeAssistant, manager: NotesVault, hass_ws_client, vault_dir: Path
) -> None:
    """A note started as new fails to save if someone created it in the meantime."""
    ws = await hass_ws_client(hass)
    (vault_dir / "Ideas.md").write_text("Someone else's\n")
    await ws.send_json_auto_id(
        {"type": "notes_vault/set", "path": "Ideas", "note": "Mine", "mtime": None}
    )
    assert (await ws.receive_json())["error"]["code"] == "changed"
    assert (vault_dir / "Ideas.md").read_text() == "Someone else's\n"


async def test_replaced_note_is_kept(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """An action replacing a note keeps the old version; appending doesn't need to."""
    # The first note replaces an untouched template, which isn't worth keeping.
    await _call(hass, "set_note", entity_id=LAMP, note="Bulb is an E27.")
    assert _trash(vault_dir) == []

    await _call(hass, "set_note", entity_id=LAMP, note="More.", append=True)
    assert _trash(vault_dir) == []

    await _call(hass, "set_note", entity_id=LAMP, note="Rewritten.")
    (kept,) = _trash(vault_dir)
    assert kept.startswith(f"{LAMP} (")
    assert "Bulb is an E27.\n\nMore." in (vault_dir / ".trash" / kept).read_text()

    await _call(hass, "write_file", path="Network.md", content="VLAN 10")
    await _call(hass, "write_file", path="Network.md", content="VLAN 20")
    assert any(n.startswith("Network (") for n in _trash(vault_dir))


async def test_delete_goes_to_trash(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """Deleting moves to the trash, which search and the index don't see."""
    await _call(hass, "write_file", path="Projects/Garden.md", content="Irrigation")
    await hass.services.async_call(
        DOMAIN, "delete_file", {"path": "Projects"}, blocking=True
    )
    assert not (vault_dir / "Projects").exists()
    assert (vault_dir / ".trash/Projects/Garden.md").read_text() == "Irrigation"

    results = await _call(hass, "search", query="Irrigation")
    assert results["results"] == []

    # A second folder of the same name doesn't overwrite the first.
    await _call(hass, "write_file", path="Projects/Garden.md", content="Again")
    await hass.services.async_call(
        DOMAIN, "delete_file", {"path": "Projects"}, blocking=True
    )
    assert _trash(vault_dir) == ["Projects", "Projects 2"]

    # Deleting from the trash is for good.
    await hass.services.async_call(
        DOMAIN, "delete_file", {"path": ".trash/Projects 2"}, blocking=True
    )
    assert _trash(vault_dir) == ["Projects"]


def test_trash_empties_after_its_age(tmp_path: Path) -> None:
    """Only what was thrown away long enough ago goes, whatever its edit date."""
    vault = Vault(tmp_path)
    vault.ensure()
    vault.write_text("old.md", "x")
    vault.write_text("new.md", "y")
    # A note last edited long ago is still fresh in the trash.
    ancient = time.time() - 90 * 86400
    os.utime(tmp_path / "new.md", (ancient, ancient))
    vault.trash("old.md")
    vault.trash("new.md")
    os.utime(tmp_path / ".trash/old.md", (ancient, ancient))

    assert vault.empty_trash(30 * 86400) == 1
    assert sorted(p.name for p in (tmp_path / ".trash").iterdir()) == ["new.md"]


async def test_webdav_honours_if_match(
    hass: HomeAssistant,
    manager: NotesVault,
    hass_client_no_auth,
    hass_access_token,
    vault_dir: Path,
) -> None:
    """A sync client with an outdated ETag gets a 412; a delete goes to the trash."""
    client = await hass_client_no_auth()
    raw = base64.b64encode(f"obsidian:{hass_access_token}".encode()).decode()
    auth = {"Authorization": f"Basic {raw}"}
    url = f"{DAV_URL}/vault/Note.md"

    resp = await client.put(url, data=b"one", headers=auth)
    etag = resp.headers["ETag"]
    resp = await client.put(url, data=b"two", headers={**auth, "If-Match": etag})
    assert resp.status == 204

    # The first ETag is stale now.
    resp = await client.put(url, data=b"three", headers={**auth, "If-Match": etag})
    assert resp.status == 412
    resp = await client.put(url, data=b"new", headers={**auth, "If-None-Match": "*"})
    assert resp.status == 412
    assert (vault_dir / "Note.md").read_bytes() == b"two"

    resp = await client.delete(url, headers=auth)
    assert resp.status == 204
    assert (vault_dir / ".trash/Note.md").read_bytes() == b"two"


async def test_panel_names_come_from_the_last_sync(
    hass: HomeAssistant, home: dict, manager: NotesVault, hass_ws_client
) -> None:
    """Opening the panel doesn't walk every registry again."""
    ws = await hass_ws_client(hass)
    with patch.object(manager, "build_docs", side_effect=AssertionError):
        await ws.send_json_auto_id({"type": "notes_vault/tree"})
        notes = (await ws.receive_json())["result"]["notes"]
    names = {n["path"]: n["name"] for n in notes}
    assert names[f"Home Assistant/Entities/{LAMP}.md"] == "Ceiling lamp"
