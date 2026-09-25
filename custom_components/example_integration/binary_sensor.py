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

from . import ExampleConfigEntry
from .api import ExampleData
from .entity import ExampleEntity


@dataclass(frozen=True, kw_only=True)
class ExampleBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor and how to read it out of a poll."""

    value_fn: Callable[[ExampleData], bool | None]


BINARY_SENSORS: tuple[ExampleBinarySensorDescription, ...] = (
    ExampleBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: data.online,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ExampleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        ExampleBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class ExampleBinarySensor(ExampleEntity, BinarySensorEntity):
    """A single on/off reading."""

    entity_description: ExampleBinarySensorDescription

    def __init__(
        self, coordinator, description: ExampleBinarySensorDescription
    ) -> None:
        """Bind the entity to its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the reading is on."""
        return self.entity_description.value_fn(self.coordinator.data)
