"""Constants for the Example Integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "example_integration"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

#: How often the coordinator polls. A push-based integration drops this in favour of
#: `async_set_updated_data` and keeps a long interval as a reconnect backstop.
SCAN_INTERVAL: Final = timedelta(seconds=60)

DEFAULT_PORT: Final = 80
