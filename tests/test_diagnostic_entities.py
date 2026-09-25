"""Diagnostic entities, when included, carry enum values into the frontmatter."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.notes_vault.const import CONF_INCLUDE_DIAGNOSTIC, DEFAULT_OPTIONS
from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.vault import parse_note


@pytest.fixture
def options() -> dict:
    """Include diagnostic entities."""
    return {**DEFAULT_OPTIONS, CONF_INCLUDE_DIAGNOSTIC: True}


async def test_enum_values_are_plain_strings(
    hass: HomeAssistant, home: dict, manager: NotesVault, vault_dir: Path
) -> None:
    """Device class and entity category are written as plain YAML strings."""
    path = vault_dir / "Home Assistant/Entities/sensor.kitchen_ceiling_rssi.md"
    text = path.read_text()
    assert "!!python" not in text
    fm = parse_note(text).frontmatter
    assert fm["device_class"] == "signal_strength"
    assert fm["entity_category"] == "diagnostic"
