"""Diagnostics dump.

Counts and settings only. Note contents and file names stay out: they are the user's
writing, and the file names alone describe their home.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.core import HomeAssistant

from . import NotesVaultConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NotesVaultConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager = entry.runtime_data
    by_kind = Counter(kind for kind, _ in manager.index)

    def _count() -> dict[str, int]:
        files = markdown = 0
        for info in manager.vault.walk():
            files += 1
            markdown += info.path.endswith(".md")
        return {"files": files, "markdown": markdown}

    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "vault": await hass.async_add_executor_job(_count),
        "generated_notes": dict(by_kind),
        "last_sync": manager.last_sync,
    }
