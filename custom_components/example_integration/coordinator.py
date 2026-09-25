"""Update coordinator."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ExampleAuthError, ExampleClient, ExampleData, ExampleError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class ExampleCoordinator(DataUpdateCoordinator[ExampleData]):
    """Keeps one device's readings fresh."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Build the coordinator and its client from the entry."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{entry.data[CONF_HOST]}",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = ExampleClient(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            token=entry.data.get(CONF_TOKEN),
        )

    async def _async_update_data(self) -> ExampleData:
        try:
            return await self.client.fetch()
        except ExampleAuthError as err:
            # Raising this instead of UpdateFailed is what makes Home Assistant offer
            # the user a "reconfigure" prompt rather than retrying wrong credentials
            # every minute until the token is fixed by hand.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ExampleError as err:
            raise UpdateFailed(str(err)) from err

    async def async_shutdown(self) -> None:
        """Stop polling and release the connection."""
        await super().async_shutdown()
        await self.client.close()
