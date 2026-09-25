"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ExampleCoordinator


class ExampleEntity(CoordinatorEntity[ExampleCoordinator]):
    """Base for every entity this integration creates.

    `_attr_has_entity_name` plus a translation key is the modern naming contract: the
    entity's own name comes from `strings.json`, Home Assistant prefixes the device
    name, and the result is translated for free. Never set `_attr_name` to a string
    that already includes the device name.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: ExampleCoordinator, key: str) -> None:
        """Bind the entity to the coordinator and give it its permanent ID."""
        super().__init__(coordinator)
        self._key = key
        # The unique ID must survive a rename, a firmware update and a reconfigure.
        # Anything derived from the host or the entity's display name will not.
        self._attr_unique_id = f"{coordinator.data.serial}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the device every entity of this entry hangs off."""
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, data.serial)},
            manufacturer="Example",
            model="Example Device",
            name=self.coordinator.config_entry.title,
            serial_number=data.serial,
            sw_version=data.firmware,
        )
