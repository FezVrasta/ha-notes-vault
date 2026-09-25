"""The entities the platforms create."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.example_integration.const import DOMAIN


async def test_entities_are_created(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Each description becomes one entity, keyed on the device's serial.

    Asserting on the unique ID rather than the entity ID is deliberate: the entity ID
    is the user's to rename, the unique ID is the contract that keeps their history
    attached across restarts and renames.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)

    assert {entry.unique_id for entry in entries} == {
        "ABC123_temperature",
        "ABC123_online",
    }
    assert {entry.domain for entry in entries} == {"sensor", "binary_sensor"}


async def test_sensor_reports_the_reading(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The value reaches the state machine."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, "ABC123_temperature")
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "21.5"
