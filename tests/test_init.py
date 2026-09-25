"""Setup, unload, and what happens when the device is unreachable."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.example_integration.api import ExampleAuthError, ExampleError


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A reachable device sets up, and unloading leaves nothing behind."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.close.assert_awaited()


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (ExampleError("unreachable"), ConfigEntryState.SETUP_RETRY),
        (ExampleAuthError("bad token"), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    error: Exception,
    expected_state: ConfigEntryState,
) -> None:
    """A transient failure retries; a credential failure asks the user for help.

    Getting these the wrong way round is the classic mistake: retrying a rejected
    token forever, or giving up on a device that was merely rebooting.
    """
    mock_client.fetch.side_effect = error
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is expected_state
