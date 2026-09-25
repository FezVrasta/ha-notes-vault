"""Talks to the device or service.

Deliberately free of every Home Assistant import. Keeping the protocol layer separate
means it can be tested without Home Assistant installed, and it is the seam along which
this file is lifted into its own PyPI package if the integration is ever upstreamed --
core integrations are not allowed to carry their own protocol code.

Replace the body with the real client. The shape -- a dataclass of readings, an async
`fetch`, and two exception types the coordinator knows how to translate -- is what the
rest of the integration is written against.
"""

from __future__ import annotations

from dataclasses import dataclass


class ExampleError(Exception):
    """The device answered, but not with something usable."""


class ExampleAuthError(ExampleError):
    """The credentials were rejected.

    Separate from `ExampleError` because Home Assistant treats it differently: it starts
    a reauth flow rather than retrying on a timer.
    """


@dataclass(slots=True)
class ExampleData:
    """One poll's worth of readings."""

    serial: str
    firmware: str
    temperature: float
    online: bool


class ExampleClient:
    """A minimal client for one device."""

    def __init__(self, host: str, port: int, token: str | None = None) -> None:
        """Prepare a client. Does not connect."""
        self.host = host
        self.port = port
        self._token = token

    async def fetch(self) -> ExampleData:
        """Read the current state.

        Raise `ExampleAuthError` when the credentials are refused and `ExampleError` for
        anything else that is not fatal to the config entry.
        """
        return ExampleData(
            serial=f"{self.host}:{self.port}",
            firmware="1.0.0",
            temperature=21.5,
            online=True,
        )

    async def close(self) -> None:
        """Release the connection, if the client holds one open."""
