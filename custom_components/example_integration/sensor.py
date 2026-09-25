"""Sensor platform.

The description-driven shape below is worth keeping even for two entities: adding a
reading becomes one tuple entry rather than a new class, and everything the frontend
needs -- units, device class, state class -- sits in one readable table.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ExampleConfigEntry
from .api import ExampleData
from .entity import ExampleEntity


@dataclass(frozen=True, kw_only=True)
class ExampleSensorDescription(SensorEntityDescription):
    """A sensor and how to read its value out of a poll."""

    value_fn: Callable[[ExampleData], float | int | str | None]


SENSORS: tuple[ExampleSensorDescription, ...] = (
    ExampleSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: data.temperature,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ExampleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        ExampleSensor(coordinator, description) for description in SENSORS
    )


class ExampleSensor(ExampleEntity, SensorEntity):
    """A single reading."""

    entity_description: ExampleSensorDescription

    def __init__(self, coordinator, description: ExampleSensorDescription) -> None:
        """Bind the entity to its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | None:
        """Return the reading."""
        return self.entity_description.value_fn(self.coordinator.data)
