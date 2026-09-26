"""Device notes: one per physical device, no HACS repositories, readable names."""

from __future__ import annotations

from pathlib import Path

import attr
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notes_vault import manager as manager_module
from custom_components.notes_vault.manager import NotesVault
from custom_components.notes_vault.vault import parse_note

DEVICES = "Home Assistant/Devices"


def _entry(hass: HomeAssistant, domain: str) -> MockConfigEntry:
    entry = MockConfigEntry(domain=domain)
    entry.add_to_hass(hass)
    return entry


async def test_hacs_repositories_are_skipped(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """HACS makes a device per repository; none of them get a note."""
    entry = _entry(hass, "hacs")
    repo = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("hacs", "1")}, name="card-mod"
    )
    er.async_get(hass).async_get_or_create(
        "update", "hacs", "1", device_id=repo.id, config_entry=entry
    )
    await manager.async_sync()
    assert not (vault_dir / f"{DEVICES}/card-mod.md").exists()
    assert not list((vault_dir / "Home Assistant/Entities").glob("update.*"))


async def test_split_device_is_one_note(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """The parts of a device split per integration share one note."""
    reg = dr.async_get(hass)
    esphome, bluetooth = _entry(hass, "esphome"), _entry(hass, "bluetooth")
    main = reg.async_get_or_create(
        config_entry_id=esphome.entry_id, identifiers={("esphome", "p")}, name="Proxy"
    )
    part = reg.async_get_or_create(
        config_entry_id=bluetooth.entry_id,
        identifiers={("bluetooth", "p")},
        name="Proxy",
    )
    # What 2026.9's migration leaves behind: both parts point at the old device.
    for device in (main, part):
        reg.devices[device.id] = attr.evolve(device, composite_device_id="old")
    await manager.async_sync()

    notes = sorted(p.name for p in (vault_dir / DEVICES).glob("Proxy*.md"))
    assert notes == ["Proxy.md"]
    fm = parse_note((vault_dir / f"{DEVICES}/Proxy.md").read_text()).frontmatter
    assert fm["ha_id"] == "old"
    assert sorted(fm["device_ids"]) == sorted([main.id, part.id])
    assert sorted(fm["integration"]) == ["bluetooth", "esphome"]
    # Either part's page finds the note.
    assert manager.resolve_target(device_id=part.id) == ("device", "old")


async def test_colliding_names_use_something_readable(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """Two devices with one name are told apart by area, then model."""
    reg = dr.async_get(hass)
    entry = _entry(hass, "shelly")
    garage = ar.async_get(hass).async_create("Garage")
    for n, area in (("1", garage.id), ("2", None)):
        device = reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("shelly", n)},
            name="Relay",
            model="Plus 1",
        )
        reg.async_update_device(device.id, area_id=area)
    unnamed = reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("shelly", "3")},
        model="Plug S",
    )
    # Some integrations report an empty name (a zte router, on a real install).
    reg.async_update_device(unnamed.id, name="")
    await manager.async_sync()

    names = sorted(p.stem for p in (vault_dir / DEVICES).glob("*.md"))
    assert "Relay" in names
    assert "Relay (Garage)" in names or "Relay (Plus 1)" in names
    assert "Plug S" in names
    assert not any(unnamed.id[:6] in n for n in names)


async def test_service_devices_are_skipped(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """A service device gets no note; its entity hangs off the integration."""
    entry = _entry(hass, "sun")
    sun = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("sun", "1")},
        name="Sun",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    dawn = er.async_get(hass).async_get_or_create(
        "sensor",
        "sun",
        "dawn",
        device_id=sun.id,
        config_entry=entry,
        suggested_object_id="sun_next_dawn",
    )
    hass.states.async_set(dawn.entity_id, "06:30")
    await manager.async_sync()

    assert not (vault_dir / f"{DEVICES}/Sun.md").exists()
    note = parse_note(
        (vault_dir / "Home Assistant/Entities/sensor.sun_next_dawn.md").read_text()
    ).frontmatter
    assert "device" not in note
    integration = parse_note(
        (vault_dir / "Home Assistant/Integrations/Sun.md").read_text()
    ).frontmatter
    assert any("sensor.sun_next_dawn" in link for link in integration["entities"])


async def test_automation_links_split_device_note(
    hass: HomeAssistant, manager: NotesVault, vault_dir: Path
) -> None:
    """An automation targeting one part of a split device links its one note."""
    reg = dr.async_get(hass)
    esphome, bluetooth = _entry(hass, "esphome"), _entry(hass, "bluetooth")
    main = reg.async_get_or_create(
        config_entry_id=esphome.entry_id, identifiers={("esphome", "p")}, name="Proxy"
    )
    part = reg.async_get_or_create(
        config_entry_id=bluetooth.entry_id,
        identifiers={("bluetooth", "p")},
        name="Proxy",
    )
    for device in (main, part):
        reg.devices[device.id] = attr.evolve(device, composite_device_id="old")
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "restart_proxy": {
                    "sequence": [
                        {
                            "action": "button.press",
                            "target": {"device_id": part.id},
                        }
                    ]
                }
            }
        },
    )
    await hass.async_block_till_done()
    await manager.async_sync()
    script = parse_note(
        (vault_dir / "Home Assistant/Scripts/script.restart_proxy.md").read_text()
    ).frontmatter
    assert script["devices"] == [f"[[{DEVICES}/Proxy|Proxy]]"]


async def test_kept_note_on_skipped_device_is_writable(
    hass: HomeAssistant,
    manager: NotesVault,
    vault_dir: Path,
    monkeypatch,
) -> None:
    """A note kept for a device that is now skipped can still be edited.

    Notes written before HACS repositories were skipped stay in the vault and
    `get_note` still reads them, so `set_note` has to accept them too.
    """
    entry = _entry(hass, "hacs")
    repo = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("hacs", "2")}, name="Alarmo"
    )
    monkeypatch.setattr(manager_module, "ALWAYS_SKIPPED_INTEGRATIONS", frozenset())
    await manager.async_set_note(("device", repo.id), "Arms when both are out.")
    monkeypatch.undo()
    await manager.async_sync()

    assert (await manager.async_get_note(("device", repo.id)))["note"] == (
        "Arms when both are out."
    )
    await manager.async_set_note(("device", repo.id), "No siren.", append=True)

    note = parse_note((vault_dir / f"{DEVICES}/Alarmo.md").read_text())
    assert note.body.strip() == "Arms when both are out.\n\nNo siren."
    assert note.frontmatter["ha_type"] == "device"
