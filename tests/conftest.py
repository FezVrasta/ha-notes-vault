"""Shared fixtures.

Home Assistant's own test fixtures come from `pytest-homeassistant-custom-component`,
which registers itself as a pytest plugin — so the suite needs only the installed
package, not a checkout of Home Assistant core. That package pins the Home Assistant
version the suite runs against; bump it in `requirements-test.txt` to test against a
newer one.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notes_vault.api import NotesVaultData
from custom_components.notes_vault.const import DOMAIN


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load this integration in every test."""


@pytest.fixture
def device_data() -> NotesVaultData:
    """One poll's worth of readings."""
    return NotesVaultData(serial="ABC123", firmware="1.2.3", temperature=21.5, online=True)


@pytest.fixture
def mock_client(device_data: NotesVaultData) -> Generator[AsyncMock]:
    """Patch the protocol client everywhere it is constructed.

    Patching the class rather than the network means the tests never depend on a real
    device, and a change to the wire protocol shows up in the protocol layer's own
    tests instead of breaking every integration test at once.
    """
    with (
        patch(
            "custom_components.notes_vault.coordinator.NotesVaultClient",
            autospec=True,
        ) as coordinator_client,
        patch(
            "custom_components.notes_vault.config_flow.NotesVaultClient",
            new=coordinator_client,
        ),
    ):
        client = coordinator_client.return_value
        client.fetch = AsyncMock(return_value=device_data)
        client.close = AsyncMock()
        yield client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a configured entry, not yet added to Home Assistant."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="NotesVault",
        unique_id="ABC123",
        data={CONF_HOST: "192.0.2.10", CONF_PORT: 80, CONF_TOKEN: "secret"},
    )
