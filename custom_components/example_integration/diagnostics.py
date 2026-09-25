"""Diagnostics dump.

Worth writing before the first release rather than after the first bug report: it is the
difference between "it doesn't work" and a file that says exactly what the device
returned.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ExampleConfigEntry

#: Anything that identifies a specific person's hardware or grants access to it.
TO_REDACT = {"serial", "serial_number", "token", "password", "api_key", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ExampleConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return async_redact_data(
        {
            "entry": {
                "data": dict(entry.data),
                "options": dict(entry.options),
                "unique_id": entry.unique_id,
            },
            "coordinator": {
                "last_update_success": coordinator.last_update_success,
                "data": asdict(coordinator.data) if coordinator.data else None,
            },
        },
        TO_REDACT,
    )
