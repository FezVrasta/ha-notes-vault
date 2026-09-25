---
name: ha-integration-conventions
description: >-
  House conventions for Home Assistant custom integration code — config entry runtime
  data, unique IDs, entity naming and translation keys, coordinator and availability
  patterns, config flow rules, services, and the deprecated APIs to avoid. Read before
  writing or reviewing any file under custom_components/, and when asked why an entity
  is named oddly, why history was lost, or whether something is the modern API.
---

# Home Assistant integration conventions

These are the rules that are cheap to follow while writing and expensive to retrofit,
because getting them wrong changes entity IDs or loses history in installations you
cannot reach.

## The three that cost users data if you get them wrong

**Unique IDs are permanent.** `_attr_unique_id` is what ties an entity to its recorded
history, its customisations and its area. Derive it from something the *device* reports —
serial, MAC — plus a stable key. Never from the host, the IP, the display name, the
config entry ID, or an index into a list. Changing it later silently creates a new entity
with a `_2` suffix and abandons years of statistics.

Corollary: leave out anything that can be corrected. If the model or the protocol version
is part of the ID, fixing a mis-detection orphans everything.

**The config entry's unique ID is the device's identity.** Set it in the config flow with
`async_set_unique_id(serial)` and `_abort_if_unique_id_configured(updates=...)`. Keying on
the host means a DHCP lease change adds a duplicate entry; the `updates=` argument is what
makes a re-run of the flow move the existing entry to the new address instead.

**Migrations are one-way.** If you must change a unique ID scheme, migrate explicitly in
`async_migrate_entry` with `entity_registry.async_update_entity`, bump `VERSION`, and test
it. Do not hope users will re-add the integration.

## Naming and translation

```python
class FooEntity(CoordinatorEntity[FooCoordinator]):
    _attr_has_entity_name = True
```

With `has_entity_name`, the entity's own name is just the *thing it measures* —
"Temperature", not "Living Room Sensor Temperature". Home Assistant composes the device
name in front of it. Setting `_attr_name` to a string containing the device name gives
users "Kitchen Kettle Kitchen Kettle Temperature".

Names come from `translation_key` + `strings.json`, not from Python strings:

```python
SensorEntityDescription(key="temperature", translation_key="temperature", ...)
```

```json
{"entity": {"sensor": {"temperature": {"name": "Temperature"}}}}
```

Set `_attr_name = None` on the one entity that *is* the device (a single lamp's light
entity, a lock's lock entity) so it inherits the device name alone.

`strings.json` is the source; `translations/en.json` is what Home Assistant serves. They
must be identical — CI diffs them. Copy, never hand-edit one of them.

## Config entry runtime data

```python
type FooConfigEntry = ConfigEntry[FooCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: FooConfigEntry) -> bool:
    entry.runtime_data = coordinator
```

Not `hass.data[DOMAIN][entry.entry_id]`. The typed alias means every platform reads
`entry.runtime_data` with no cast and no `KeyError` on a half-torn-down entry.

## Coordinator

- `await coordinator.async_config_entry_first_refresh()` in `async_setup_entry`. It
  raises `ConfigEntryNotReady` on failure, which is what makes Home Assistant retry with
  backoff rather than marking the entry broken.
- Raise `UpdateFailed` for transient problems and `ConfigEntryAuthFailed` for rejected
  credentials. The first retries on a timer; the second prompts the user to
  reauthenticate. Retrying a bad token every 30 seconds forever is the standard version
  of this bug.
- For a push protocol, keep a `DataUpdateCoordinator` but call `async_set_updated_data`
  from the callback and use `update_interval` only as a reconnect backstop.
- Do not log every failed poll. The coordinator already logs the first failure and the
  recovery, and suppresses the rest.

## Availability

The default — entities go unavailable when the coordinator fails — is right for most
things. Override it only with a reason worth writing down. A solar inverter that sleeps
overnight, for example, should stay available and expose staleness as data (a
`last_seen` timestamp, a connectivity binary sensor), because marking it unavailable puts
a nightly gap in every history graph. If you do override it, say why in a docstring; the
next person will assume it is a mistake otherwise.

## Config flow

- Every flow needs `user`. Add `reauth` if credentials can expire and `reconfigure` if
  the device can move. Both are cheap and both are the difference between a user fixing
  something in 10 seconds and deleting the integration.
- `_abort_if_unique_id_mismatch(reason="wrong_device")` in `reconfigure`, so nobody
  points an entry at a different device and silently merges two histories.
- Errors go back to the same form with `errors={"base": "..."}` and the flow must still
  work once the problem is fixed. Test the recovery, not just the message.
- Discovery (`dhcp`, `zeroconf`, `bluetooth`, `usb` blocks in the manifest) beats asking
  for an IP. If the protocol makes it possible, do it.
- `data` is what the integration needs to connect. `options` is what the user can change
  without re-validating. Do not put a poll interval in `data`.

## Services

Register in `async_setup` (not `async_setup_entry`) so the service exists once, not once
per entry. Every service needs an entry in `services.yaml` and matching `strings.json`
text, with selectors — a service that asks for a raw entity ID string in the UI is a
service nobody discovers. Raise `ServiceValidationError` for bad input from the user and
`HomeAssistantError` for a failure of the device; only the second one gets a traceback.

## Diagnostics

Implement `async_get_config_entry_diagnostics` before the first release. It turns "it
doesn't work" into a file. Redact serials, tokens and anything else that identifies a
person's hardware with `async_redact_data`.

## Deprecated — do not write these

| Instead of | Use |
| --- | --- |
| `hass.data[DOMAIN][entry.entry_id]` | `entry.runtime_data` |
| `async_setup_platforms` | `async_forward_entry_setups` |
| `entity.async_update_ha_state()` | `async_write_ha_state()` |
| `device_id` in anything user-facing | `entity_id` |
| a `SCAN_INTERVAL` module constant | `update_interval` on the coordinator |
| `hass.helpers.*` | import the helper module directly |
| `AddEntitiesCallback` | `AddConfigEntryEntitiesCallback` |

## Blocking calls

Everything in `async_` code must be non-blocking. File I/O, `requests`, `time.sleep` and
most third-party clients are not. Wrap them in `hass.async_add_executor_job`. Home
Assistant detects and warns about some of these at runtime, but only some.
