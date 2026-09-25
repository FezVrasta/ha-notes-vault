---
name: new-integration
description: >-
  Turn this template into a real Home Assistant integration. Use immediately after
  creating a repository from ha-integration-template, or when asked to "start a new
  integration", "bootstrap this", or "set up the scaffold". Covers running
  scripts/bootstrap, choosing integration_type and iot_class, what to replace, and how
  to know the scaffold still works afterwards.
---

# Starting a new integration from the template

The scaffold that ships here is a working integration — it sets up, creates two
entities, passes hassfest and has a green test suite. That is deliberate: you convert it
into the real thing a piece at a time, and the suite tells you the moment you break it.
Do not start by deleting things.

## 1. Bootstrap

```bash
scripts/bootstrap --domain growatt_datalogger --name "Growatt Datalogger"
```

This renames `example_integration` everywhere, rewrites `Example*` class names from the
display name, points the manifest and badges at the `origin` remote, moves the component
directory, replaces the template's README with a skeleton, and deletes itself. Run it
**once**, before writing any code — it is a blunt string replacement and will happily
mangle a half-written integration. `--dry-run` prints the plan.

The domain is permanent in practice. Changing it later orphans every entity and device
in every installation, so pick it as though you cannot change it: lowercase, no
`ha_` prefix, no vendor suffix you might outgrow.

## 2. Fill in the manifest

Two fields are worth thinking about rather than guessing:

**`integration_type`** — `device` for one physical thing per entry, `hub` for one entry
fronting many devices, `service` for a cloud or local service with no device behind it,
`helper` for something that only derives from other entities. It decides which list the
integration appears in and how Home Assistant words the setup dialogs.

**`iot_class`** — `local_push`, `local_polling`, `cloud_push`, `cloud_polling`, or
`calculated`. Say what the code actually does. `local_push` on something that polls
every 30 seconds is the kind of thing reviewers and users both notice.

Also: `requirements` must pin exactly (`foo==1.2.3`), never a range — Home Assistant
installs what the manifest says, and a floating pin means two users run different code.
Leave `version` at whatever it is. `scripts/bump-version` sets it as part of cutting
a release, and CI fails the release if the tag and the manifest disagree.

## 3. Replace the scaffold, in this order

1. **`api.py`** — the real client. Keep it free of Home Assistant imports; that is what
   lets it be tested without Home Assistant and lifted into its own PyPI package if the
   integration is ever upstreamed. Keep the two exception types: the coordinator
   translates one into a retry and the other into a reauth prompt.
2. **`coordinator.py`** — the update strategy. If the device pushes, drop the interval
   to a long reconnect backstop and call `async_set_updated_data` from the callback.
3. **`config_flow.py`** — delete the steps you do not need, and their `strings.json`
   entries with them. Keep the unique-ID handling: it must key on something the device
   reports, never on the host.
4. **The platforms** — `sensor.py` and `binary_sensor.py` show the description-driven
   shape. Add platforms by copying it, and list them in `const.PLATFORMS`.
5. **`strings.json`**, then copy it to `translations/en.json`. CI fails if they differ.

See `.claude/skills/ha-integration-conventions` before writing entity code — it has the
rules that are cheap to follow now and expensive to retrofit.

## 4. Prove it still works

```bash
scripts/setup   # once
scripts/test
```

`scripts/test` runs ruff, the translations diff and pytest — everything CI runs except
hassfest and the HACS action, which need a container. Push and let those two run.

Then install it on a real Home Assistant before the first release. A green suite means
the code does what the tests say; it does not mean the device agrees.

## 5. Repository settings

The HACS action fails without these, so do this before wondering why CI is red:

```bash
gh repo edit --description "One line, the same one as the README subtitle" \
             --add-topic home-assistant --add-topic hacs \
             --add-topic home-assistant-custom-component
```

## What to do next

- README — `.claude/skills/readme-style`
- Icon — `.claude/skills/brand-assets`. The scaffold ships a generic placeholder so the
  HACS job passes on day one; it is not something to release.
- First release — `.claude/skills/cut-release`
