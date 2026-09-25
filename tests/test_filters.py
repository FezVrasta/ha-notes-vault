"""Filters: they stop empty notes from being generated, never written ones."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.notes_vault.const import (
    CONF_EXCLUDE_DOMAINS,
    DEFAULT_OPTIONS,
    KIND_ENTITY,
)
from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.vault import parse_note

ENTITIES = "Home Assistant/Entities"


@pytest.fixture
def options() -> dict:
    """Skip lights, to test the filters."""
    return {**DEFAULT_OPTIONS, CONF_EXCLUDE_DOMAINS: ["light"]}


async def test_excluded_entity_gets_file_only_with_a_note(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Filters stop empty notes, never written ones."""
    path = vault_dir / f"{ENTITIES}/light.kitchen_ceiling.md"
    assert not path.exists()

    await manager.async_set_note(
        (KIND_ENTITY, home["light"].id), "Dimmer is on the wall."
    )
    assert path.exists()
    await manager.async_sync()
    assert parse_note(path.read_text()).body == "Dimmer is on the wall.\n"

    await manager.async_set_note((KIND_ENTITY, home["light"].id), "")
    await manager.async_sync()
    assert not path.exists()
