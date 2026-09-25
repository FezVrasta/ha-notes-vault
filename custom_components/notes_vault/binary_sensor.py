"""Binary sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NotesVaultConfigEntry
from .api import NotesVaultData
from .entity import NotesVaultEntity


@dataclass(frozen=True, kw_only=True)
class NotesVaultBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor and how to read it out of a poll."""

    value_fn: Callable[[NotesVaultData], bool | None]


BINARY_SENSORS: tuple[NotesVaultBinarySensorDescription, ...] = (
    NotesVaultBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: data.online,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotesVaultConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        NotesVaultBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class NotesVaultBinarySensor(NotesVaultEntity, BinarySensorEntity):
    """A single on/off reading."""

    entity_description: NotesVaultBinarySensorDescription

    def __init__(
        self, coordinator, description: NotesVaultBinarySensorDescription
    ) -> None:
        """Bind the entity to its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the reading is on."""
        return self.entity_description.value_fn(self.coordinator.data)
