---
name: integration-tests
description: >-
  How the test suite for these Home Assistant integrations is set up and what is worth
  testing. Use when adding or fixing tests, when a test needs a Home Assistant fixture,
  when the suite fails to import, or when deciding whether something needs a test at
  all.
---

# Testing a custom integration

## How it runs

`pytest-homeassistant-custom-component` packages Home Assistant's own test fixtures and
registers itself as a pytest plugin. The suite therefore needs nothing but that installed
package — no checkout of Home Assistant core, and it runs identically locally and in CI.

The pin in `requirements-test.txt` **is** the Home Assistant version being tested against,
and it dictates the Python version. Bumping it is how you test against a newer Home
Assistant; when you do, bump `PYTHON_VERSION` in `.github/workflows/ci.yml` and the
`homeassistant` floor in `hacs.json` to match.

```bash
scripts/setup   # once
scripts/test    # ruff + translations diff + pytest
```

`asyncio_mode = "auto"` is set, so `async def test_…` needs no decorator.

## The fixtures that matter

- `enable_custom_integrations` — autouse in `conftest.py`. Without it Home Assistant
  refuses to load anything from `custom_components/` and every test fails with a
  confusing "integration not found".
- `hass` — a running Home Assistant. Anything scheduled needs
  `await hass.async_block_till_done()` before you assert.
- `MockConfigEntry` — build the entry, `entry.add_to_hass(hass)`, then
  `hass.config_entries.async_setup(entry.entry_id)`.
- `socket_enabled` — the plugin blocks real sockets, which is right for an integration
  that mocks its client. An integration that runs its own server (binding loopback on an
  OS-assigned port) needs this fixture, because faking the transport would leave the
  framing and reassembly untested.
- `snapshot` (syrupy) is available. Useful for diagnostics output and large entity
  tables, where the diff is the assertion.

## Mock the client, not the network

Patch the client class where it is *constructed* — the coordinator module and the config
flow module both import it by name, so both need patching, and they should share one mock
so a test can set `side_effect` once. `autospec=True`, so a renamed method fails the test
instead of silently returning a `Mock`.

This keeps the wire protocol tested in the protocol layer's own tests, where it belongs,
instead of breaking every integration test whenever the framing changes.

## What is worth a test

In rough order of how often it catches something real:

1. **Setup and unload.** That the entry reaches `LOADED`, and that unloading returns to
   `NOT_LOADED` and closes the connection. Catches most refactoring damage.
2. **The two failure branches.** A transient error must give `SETUP_RETRY`; a credential
   error must give `SETUP_ERROR` and start a reauth flow. Getting these the wrong way
   round is the classic bug and the suite is the only place it shows up.
3. **Config flow error recovery.** Not just that the error appears — that the flow still
   completes once the problem is fixed.
4. **The duplicate guard.** Setting up the same device twice must update the address,
   not create a second entry.
5. **Unique IDs.** Assert on `unique_id`, not `entity_id` — the entity ID is the user's
   to rename, the unique ID is the contract that keeps their history attached. A test
   here is what stops an innocuous-looking refactor orphaning everyone's statistics.
6. **Anything that has broken before.** One test per past failure, named after it. These
   are the most valuable tests in any of these repositories.

## What is not worth a test

Assertions that restate the code (`assert DOMAIN == "foo"`), a test per sensor in a
description table when one parametrised test covers the shape, and anything that only
passes because it mocks the thing it claims to test.
