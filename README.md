<p align="center">
  <img src="custom_components/example_integration/brand/icon.png" width="128" alt="">
</p>

<h1 align="center">Home Assistant integration template</h1>

<p align="center">
  A working custom integration, a green CI pipeline, and the conventions written down —<br>
  so a new one starts at the interesting part.
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=FezVrasta&repository=ha-integration-template&category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open this repository in HACS">
  </a>
</p>

<p align="center">
  <img src="https://github.com/FezVrasta/ha-integration-template/actions/workflows/ci.yml/badge.svg" alt="CI">
  <img src="https://img.shields.io/badge/HACS-custom-41BDF5.svg" alt="HACS custom repository">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">
</p>

---

Click **Use this template**, clone it, and run:

```bash
scripts/bootstrap --domain growatt_datalogger --name "Growatt Datalogger"
```

That renames the placeholder domain everywhere, rewrites the class names from the display
name, points the manifest and badges at your repository, replaces this README with a
skeleton, and deletes itself. Then:

```bash
scripts/setup
scripts/test
```

Both should be green before you have written a line — the scaffold is a real integration,
not a stub, and that is the point: you convert it piece by piece and the suite tells you
the moment you break it.

## What you get

**A working integration.** Config flow with `user`, `reauth` and `reconfigure` steps and
an options flow; a `DataUpdateCoordinator` that raises the right exception for each kind
of failure; a shared entity base; two description-driven platforms; diagnostics with
redaction; `strings.json` wired to `translations/`. A protocol layer in `api.py` with no
Home Assistant imports, which is the seam along which it gets lifted into its own PyPI
package if the integration is ever upstreamed.

**A test suite that tests the things that break.** Setup and unload, both failure
branches, config flow error *recovery*, the duplicate guard, and unique IDs. Backed by
`pytest-homeassistant-custom-component`, so it needs no checkout of Home Assistant core.

**CI.** ruff on Home Assistant core's own configuration, pytest, hassfest, the HACS
action, and a job that diffs `strings.json` against `translations/en.json` — the drift
nothing else catches. Plus a release workflow that sets `manifest.json`'s version from
the tag, so it is never bumped by hand.

**The conventions, written down.** Six skills in `.claude/skills/`, which Claude Code
picks up automatically in any repository made from this template:

| Skill | What it covers |
| --- | --- |
| `new-integration` | Bootstrapping: `integration_type`, `iot_class`, what to replace and in what order |
| `ha-integration-conventions` | Unique IDs, entity naming, `runtime_data`, coordinator and availability patterns, deprecated APIs |
| `integration-tests` | The fixtures, mocking the client not the network, what is worth a test |
| `readme-style` | The README layout, badges and voice used across these repositories |
| `brand-assets` | The 2026.3 `brand/` folder, sizes, rendering from SVG, the librsvg quirks |
| `cut-release` | The tag-driven release, and verifying on real hardware before shipping |
| `hacs-publish` | What the HACS action actually checks, the default list, upstreaming to core |

**Repository furniture.** Issue template that asks for diagnostics, dependabot for the
actions, `CONTRIBUTING.md`, `CLAUDE.md`, MIT license, and a placeholder brand icon —
the HACS job fails outright on a missing `icon.png`, and a new repository should not
start red. Replace it before the first release.

## Layout

```
custom_components/example_integration/
  __init__.py          entry setup, runtime_data typing
  api.py               the protocol layer — no Home Assistant imports
  coordinator.py       polling, and which exception means what
  config_flow.py       user / reauth / reconfigure / options
  entity.py            shared base: device_info, unique_id, has_entity_name
  sensor.py            description-driven platform
  binary_sensor.py     the same shape, second platform
  diagnostics.py       redacted dump
  strings.json         → copied to translations/en.json
  brand/               icons Home Assistant serves since 2026.3
tests/                 conftest fixtures + the four suites above
scripts/               bootstrap, setup, test
tools/make_icon.py     generates the placeholder squircle icon, then renders it
tools/render_brand.py  SVG → the PNG sizes Home Assistant wants
```

## Keeping the versions in step

The pin in `requirements-test.txt` **is** the Home Assistant version being tested against,
and it dictates the Python version. Currently `0.13.357` → Home Assistant 2026.8 → Python
3.14. When you bump it, bump `PYTHON_VERSION` in `.github/workflows/ci.yml` and the
`homeassistant` floor in `hacs.json` with it.

## License

MIT.
