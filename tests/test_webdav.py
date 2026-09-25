"""The WebDAV endpoint, driven the way remotely-save drives it."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.notes_vault.manager import NotesVault

ROOT = "/api/notes_vault/dav"


def _basic(token: str) -> dict[str, str]:
    raw = base64.b64encode(f"obsidian:{token}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture
async def dav(
    hass: HomeAssistant, manager: NotesVault, hass_client_no_auth, hass_access_token
):
    """Return a client authenticated the way remotely-save does it."""
    client = await hass_client_no_auth()
    headers = _basic(hass_access_token)

    async def request(method: str, path: str, **kwargs):
        return await client.request(
            method,
            ROOT + path,
            headers={**headers, **kwargs.pop("headers", {})},
            **kwargs,
        )

    return request


async def test_rejects_bad_credentials(
    hass: HomeAssistant, manager: NotesVault, hass_client_no_auth
) -> None:
    """No token, a wrong token, and a garbage header are all turned away."""
    client = await hass_client_no_auth()
    resp = await client.request("PROPFIND", ROOT + "/vault/")
    assert resp.status == 401
    assert "Basic" in resp.headers["WWW-Authenticate"]
    resp = await client.request("PROPFIND", ROOT + "/vault/", headers=_basic("nope"))
    assert resp.status == 401


async def test_non_admin_is_refused(
    hass: HomeAssistant,
    manager: NotesVault,
    hass_client_no_auth,
    hass_read_only_access_token,
) -> None:
    """The vault is an admin thing."""
    client = await hass_client_no_auth()
    resp = await client.request(
        "PROPFIND", ROOT + "/vault/", headers=_basic(hass_read_only_access_token)
    )
    assert resp.status == 403


async def test_bearer_token_works(
    hass: HomeAssistant, manager: NotesVault, hass_client
) -> None:
    """Home Assistant's own Bearer auth is accepted too."""
    client = await hass_client()
    resp = await client.request("PROPFIND", ROOT + "/vault/", headers={"Depth": "0"})
    assert resp.status == 207


async def test_round_trip(dav, vault_dir: Path) -> None:
    """Create a folder, upload, list, download, move and delete."""
    resp = await dav("OPTIONS", "/vault/")
    assert "1" in resp.headers["DAV"]

    resp = await dav("PROPFIND", "/", headers={"Depth": "1"})
    assert resp.status == 207
    assert f"<d:href>{ROOT}/vault/</d:href>" in await resp.text()

    assert (await dav("MKCOL", "/vault/Projects/")).status == 201
    assert (await dav("MKCOL", "/vault/Projects/")).status == 405
    assert (await dav("MKCOL", "/vault/a/b/")).status == 409

    resp = await dav("PUT", "/vault/Projects/Garden%20plan.md", data=b"# Plan\n")
    assert resp.status == 201
    assert (vault_dir / "Projects/Garden plan.md").read_text() == "# Plan\n"
    assert (
        await dav("PUT", "/vault/Projects/Garden%20plan.md", data=b"v2")
    ).status == 204
    assert (await dav("PUT", "/vault/Nope/x.md", data=b"x")).status == 409

    resp = await dav("PROPFIND", "/vault/Projects/", headers={"Depth": "1"})
    body = await resp.text()
    assert f"<d:href>{ROOT}/vault/Projects/Garden%20plan.md</d:href>" in body
    assert "<d:getcontentlength>2</d:getcontentlength>" in body

    resp = await dav("GET", "/vault/Projects/Garden%20plan.md")
    assert await resp.read() == b"v2"
    assert resp.headers["Last-Modified"]

    resp = await dav(
        "MOVE",
        "/vault/Projects/Garden%20plan.md",
        headers={
            "Destination": f"http://example.com{ROOT}/vault/Garden.md",
            "Overwrite": "F",
        },
    )
    assert resp.status == 201
    assert (vault_dir / "Garden.md").exists()

    assert (await dav("DELETE", "/vault/Projects/")).status == 204
    assert not (vault_dir / "Projects").exists()
    assert (await dav("GET", "/vault/Projects/")).status == 404


async def test_paths_cannot_escape(dav) -> None:
    """Traversal is refused, and so is anything outside the vault collection."""
    resp = await dav("GET", "/vault/..%2F..%2Fsecrets.yaml")
    assert resp.status in (400, 404)
    assert (await dav("GET", "/other/file.md")).status == 404


async def test_editing_a_generated_note(
    hass: HomeAssistant, home: dict, manager: NotesVault, dav
) -> None:
    """A note written from Obsidian is what the UI shows."""
    path = "/vault/Home%20Assistant/Entities/light.kitchen_ceiling.md"
    text = await (await dav("GET", path)).text()
    await dav("PUT", path, data=(text + "Written in Obsidian.\n").encode())
    note = await manager.async_get_note(("entity", home["light"].id))
    assert note["note"] == "Written in Obsidian."
