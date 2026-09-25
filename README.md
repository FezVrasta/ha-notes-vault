<p align="center">
  <img src="custom_components/notes_vault/brand/icon.png" width="128" alt="">
</p>

<h1 align="center">Notes Vault for Home Assistant</h1>

<p align="center">
  A full notes app for your home, inside Home Assistant, with a note on every entity, device and area.<br>
  Built so your AI assistant writes down what it learns about your house, and reads it back next time.
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=FezVrasta&repository=ha-notes-vault&category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open this repository in HACS">
  </a>
</p>

<p align="center">
  <img src="https://github.com/FezVrasta/ha-notes-vault/actions/workflows/ci.yml/badge.svg" alt="CI">
  <img src="https://img.shields.io/badge/HACS-custom-41BDF5.svg" alt="HACS custom repository">
  <img src="https://img.shields.io/badge/Home%20Assistant-2026.8%2B-41BDF5" alt="Home Assistant 2026.8+">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status: alpha">
  <img src="https://img.shields.io/badge/config-no%20YAML-brightgreen" alt="No YAML">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">
</p>

---

Every home has a pile of facts that live nowhere: which breaker the boiler is on, when the smoke detector battery was replaced, why that automation has a 40 second delay. An AI assistant working on Home Assistant has it worse. It spends an hour figuring out why the heat pump ignores the thermostat, fixes it, and the next session starts from zero.

Notes Vault gives Home Assistant a proper notes vault: Markdown notes with wikilinks, backlinks, folders, templates and search, and a generated note for every entity, device and area. You write in it from the Home Assistant UI. Agents read and write it through Home Assistant actions, so anything connected over MCP can check the note on a device before touching it and add what it found afterwards.

The vault is a plain folder of Markdown files in the Obsidian format, so you can also sync it to Obsidian, or any other app that reads Obsidian vaults, and work on it there.

## What you get

<p align="center">
  <img src="docs/images/panel.png" alt="The Notes panel in Home Assistant. On the left, the vault as a tree: the user's own Home folder with Electrical panel and Network, then the generated Areas. On the right, the Heat pump note with its location, purchase details, maintenance log and quirks, linking to the Ecobee thermostat, the outside temperature sensor and the energy contract, with a Go to device button and the notes that link to it underneath.">
  <br><em>The Notes panel: every note in the vault, with the ones linking to it.</em>
</p>

<table>
  <tr>
    <td width="60%"><img src="docs/images/device-page.png" alt="The Heat pump device page in Home Assistant with a Notes card under Device info, showing where the unit is and its purchase and warranty details, with links to the Garden area and the Yearly maintenance note."></td>
    <td width="40%"><img src="docs/images/more-info.png" alt="The more-info dialog of the Outside Temperature sensor, with a Notes section under the history graph saying it feeds the weather curve of the Heat pump, which is a link."></td>
  </tr>
  <tr>
    <td><em>A Notes card on every device and area page.</em></td>
    <td><em>A Notes section in every entity's more-info dialog.</em></td>
  </tr>
</table>

- **A Notes panel.** **Notes** in the sidebar lists every note in the vault as a tree, with search, and opens any of them in the editor, with the notes that link to it underneath. Create, rename, move and delete notes and folders there; links to them follow. Administrators only, since the vault can hold anything.
- **Notes where you need them.** Add or edit a note from any entity's more-info dialog, from device and area pages, and in the automation, script and scene editors. Wikilinks work: a link to an entity opens its more-info dialog, a link to a device or area opens its page, and a link to any other note opens it in the Notes panel.
- **A generated note per entity, device and area.** The frontmatter carries the name, IDs, integration, area, device and labels, with links between them, so backlinks and graph views show how your home fits together. Renaming an entity ID renames its note and rewrites the links pointing at it.
- **Templates.** Each kind of thing starts from its own headings: a light asks for the bulb and the breaker, a battery device for the battery type and a replacement log. Agents get the same template, so their notes look like yours.
- **Actions for AI and automations.** Read, write, append, list and search, all with response data, so any Home Assistant MCP server can use the vault without extra setup.
- **Sync with Obsidian and compatible apps.** A WebDAV endpoint on Home Assistant's own web server, authenticated with a long-lived access token.
- **A dashboard card.** `custom:notes-vault-card` shows and edits the note of one entity, device or area.

## Notes for your AI

Assistants that work on Home Assistant through MCP are good at reading the current state and bad at remembering anything else. The registries tell them a device exists; they don't tell them it's in the attic, that its firmware update bricked it once, or that you already tried lowering the flow temperature. Notes Vault is where that goes.

Any MCP server for Home Assistant that can call actions can use these. Nothing to install on the AI side.

| Action | Does |
| --- | --- |
| `notes_vault.get_note` | Returns the note of an entity, device or area, with its path and wikilink |
| `notes_vault.set_note` | Replaces or appends to that note |
| `notes_vault.search` | Finds notes containing every word of a query |
| `notes_vault.get_template` | Returns a template filled in for an entity, device or area, the best fit unless you name one |
| `notes_vault.list_templates` | Lists the templates and what each applies to |
| `notes_vault.list_files` | Lists a folder |
| `notes_vault.read_file` | Returns any file in the vault |
| `notes_vault.write_file` | Creates or overwrites any file in the vault |
| `notes_vault.delete_file` | Deletes a file or folder |
| `notes_vault.sync` | Re-reads the vault and regenerates the notes now |

While a note is empty, `get_note` also returns the template that fits it, so an agent writing a note for the first time follows the same structure you would. `get_note`, `get_template` and `list_templates` are available to every user. The rest need an administrator, because the vault can hold anything, not just notes on entities.

Agents don't take notes unless they're told to. I put something like this in the assistant's instructions (a `CLAUDE.md`, a project prompt, a custom GPT's instructions):

```markdown
Home Assistant has a notes vault, through the notes_vault actions.

- Before working on an entity, device or area, read its note with notes_vault.get_note.
- Before asking me something about the house, search the vault with notes_vault.search.
- When you learn something Home Assistant doesn't already know (where a device is,
  why an automation is set up the way it is, what you tried that didn't work),
  append it to the note with notes_vault.set_note and append: true.
- Anything that isn't about one entity, device or area (the network, a project)
  goes in its own file with notes_vault.write_file.
```

Every write fires a `notes_vault_updated` event with the path and, for generated notes, the entity, device or area ID, whichever way it came in (UI, action or WebDAV). Automate on it if you want to know when an agent wrote something.

## Install

Click the badge above (or add this repository to HACS as a custom **Integration**), install, restart, then add **Notes Vault** from **Settings → Devices & services**.

Setup asks for one thing: the folder, relative to the config directory, that holds the vault (default `notes_vault`). It's created if missing, and it's included in Home Assistant backups like the rest of `/config`.

The first sync runs once Home Assistant has started, and writes one note per included entity, device and area under `Home Assistant/`.

## The vault

```
notes_vault/
├── Home Assistant/
│   ├── Areas/Kitchen.md
│   ├── Automations/automation.leak_alert.md
│   ├── Devices/Ceiling lamp.md
│   ├── Entities/light.kitchen_ceiling.md
│   ├── Scenes/scene.movie_night.md
│   ├── Scripts/script.goodnight.md
│   └── Templates/
└── anything else you write
```

A generated note looks like this:

```markdown
---
ha_type: entity
ha_id: 5f1c…
entity_id: light.kitchen_ceiling
name: Ceiling lamp
domain: light
integration: hue
device: '[[Home Assistant/Devices/Ceiling lamp|Ceiling lamp]]'
area: '[[Home Assistant/Areas/Kitchen|Kitchen]]'
ha_url: https://ha.example.com/history?entity_id=light.kitchen_ceiling
aliases:
- Ceiling lamp
tags:
- Home-Assistant/Entity
- Home-Assistant/Entity/Light
---
Bulb is an E27, 2700K. Replaced 2026-01-10.
```

Home Assistant owns the frontmatter keys it writes and leaves everything else alone: the body, and any keys you add yourself. `aliases` are merged, so yours stay. Tags under `Home-Assistant/` are generated (`Home-Assistant/Entity/Air-Quality`, `Home-Assistant/Device/Philips-Hue`, `Home-Assistant/Area`), named after the integration so the tag pane reads as a tree of your home; any other tag you add is kept. A note is only rewritten when its generated metadata changes, which keeps sync conflicts rare.

Automations, scripts and scenes get folders of their own, and their notes carry what they're for and what they touch:

```markdown
---
entity_id: automation.leak_alert
name: Leak alert
description: 'Water on the utility room floor: stop the heat pump and warn everyone.'
mode: single
entities:
- '[[Home Assistant/Entities/binary_sensor.basement_floor_wet|Basement Floor Wet]]'
devices:
- '[[Home Assistant/Devices/Heat pump|Heat pump]]'
---
```

Because those are links, the heat pump's backlinks in Obsidian list every automation, script and scene that controls it, and the graph shows the home's logic wired to its devices.

`Home Assistant/Index.md` lists every note with something written in it, grouped into your own notes (by folder), areas, devices, automations, scripts, scenes and entities. Notes still holding their untouched template are left out, so it's the quickest way to see what you (or an assistant) have actually written down. It's regenerated as notes change; don't edit it.

Removing an entity, device or area from Home Assistant never costs you what you wrote about it: its note stays, marked `ha_removed: true`. Only notes nobody wrote in are deleted with it.

Everything outside `Home Assistant/` is yours. Notes Vault never touches it except to follow renames of the generated notes.

## Templates

Every generated note starts out holding its template, so opening `Kitchen.md` gives you the headings to fill in. A note whose body is still exactly its template counts as empty: Home Assistant shows **No notes yet**, filters can remove it, and it's deleted along with its entity. The moment you write in it, it's yours. Edit a template and every note still holding the old one is updated to match, and none of the others.

In Home Assistant, **Add note** starts from the same template, and a **Template** dropdown switches to another one or to a blank note.

<p align="center">
  <img src="docs/images/template.png" width="420" alt="Starting a note on the Ceiling Lights entity: the Template dropdown is set to Light, and the editor holds its headings: Fixture with bulb, socket, wattage, wall switch and circuit breaker, then Replacement log and Quirks.">
</p>

Templates are Markdown files in `Home Assistant/Templates/`, so you edit them like any other note (and Obsidian's own Templates plugin can use the same folder). The defaults cover the common cases:

| Template | For |
| --- | --- |
| Device | Any device: location, purchase and warranty, manual, maintenance log |
| Appliance | Devices with a climate, water heater, vacuum, fan, humidifier or mower entity: model, consumables and when they were replaced |
| Battery device | Devices with a battery sensor: battery type and a replacement log |
| Network device | Devices from UniFi, FRITZ!Box, Omada, OpenWrt, ASUSWRT, Netgear, MikroTik or Synology: IP, VLAN, admin URL, firmware log |
| Entity | Any entity: what it's for, quirks |
| Light | Lights: bulb, socket, wattage, wall switch, breaker, replacement log |
| Sensor | Sensors and binary sensors: placement, calibration |
| Automation | Automations and scripts: why it exists, how it works, decisions |
| Scene | Scenes: when it's used, what it sets |
| Lock and security | Locks and alarm panels: where codes and keys are kept (never the codes), battery, service contact |
| Area | Areas: layout, breakers, network |

Each default is written once and never overwritten, so your edits stick and a template you delete stays deleted. New defaults from an update are added. Delete the folder to get all the defaults back.

A template says what it applies to in its frontmatter:

```markdown
---
ha_template:
  applies_to: device              # entity, device or area
  entity_device_classes: [battery]
---
## Battery
- Type:

## Battery log
```

| Criterion | Matches |
| --- | --- |
| `domains` | Entity domain (`light`, `sensor`) |
| `device_classes` | Entity device class (`temperature`, `battery`) |
| `integrations` | The integration providing the entity or device (`hue`, `zha`) |
| `entity_domains` | Devices that have an entity of this domain |
| `entity_device_classes` | Devices that have an entity of this device class |

Every criterion a template sets has to match, and the template setting the most criteria wins. One with none is the fallback for its kind. Placeholders: `{{name}}`, `{{entity_id}}`, `{{device}}`, `{{area}}`, `{{manufacturer}}`, `{{model}}`, `{{integration}}` and `{{date}}` (the day the note was first filled in, so it doesn't change on its own). Anything else in double braces is left as is, for your notes app to fill.

## Obsidian and compatible apps

The vault is written in the Obsidian format: Markdown, YAML frontmatter, `[[wikilinks]]` with paths and aliases, nested tags. Obsidian is what I test with, but anything that opens an Obsidian vault works on it too, like Foam in VS Code or Zettlr. You don't need any of them to use Notes Vault; they're for when you want the notes on your computer or phone.

### Syncing over WebDAV

Home Assistant serves the vault over WebDAV:

| Setting | Value |
| --- | --- |
| Address | `https://<your Home Assistant>/api/notes_vault/dav` |
| Username | anything, it's ignored |
| Password | a long-lived access token of an **administrator** (your profile → Security) |

The vault is the `vault` folder at that address. Any WebDAV client works with it (Finder's **Connect to Server**, rclone, Cyberduck), so an app without its own sync can open a mounted or synced copy.

In Obsidian, sync it with [remotely-save](https://github.com/remotely-save/remotely-save). Install it from **Settings → Community plugins**, pick **WebDAV** as the remote service, and use the settings above plus:

| Setting | Value |
| --- | --- |
| Auth type | `basic` |
| Depth header | `only supports depth='1'` |
| Change the remote base directory | `vault` |

The base directory matters: remotely-save syncs into a folder named after your Obsidian vault unless you set one. Start with an empty Obsidian vault the first time.

### Obsidian: Front Matter Title

Obsidian shows the file name as a note's title, so an entity note shows up as `light.kitchen_ceiling`. [Front Matter Title](https://github.com/snezhig/obsidian-front-matter-title) shows a frontmatter key instead, without renaming the file.

1. In its settings, set **Common main template** to `name`, the key Notes Vault writes the friendly name to.
2. Turn on the features. Each one is off until you enable it:

| Feature | What it changes |
| --- | --- |
| **Explorer** (and **Explorer → Sort**) | File explorer shows and sorts by `Ceiling lamp` instead of `light.kitchen_ceiling` |
| **Search** | Search results |
| **Suggest** | Quick switcher and the `[[` link suggestions |
| **Bookmarks** | Bookmarked notes |
| **Backlink** | The backlinks pane, which is where a device note lists the entities pointing at it |
| **Tabs** | Tab titles |
| **Header** | The note header above the editor |
| **Inline** | The inline title at the top of the note |
| **Window Frame Title** | The window title |
| **Graph** | Graph view nodes |
| **Canvas** | Cards on a canvas |
| **Note Link** | Rewrites the text of `[[light.kitchen_ceiling]]` to the name. Set its strategy to **Replace only links without alias**. It edits your files, so every rewrite is a change to sync. |

Leave **Alias** off: the notes already carry their name in `aliases`.

Links still work either way: type `[[Ceiling` and pick the alias, and Obsidian inserts `[[light.kitchen_ceiling|Ceiling lamp]]`.

### Obsidian: Dataview

[Dataview](https://github.com/blacksmithgu/obsidian-dataview) turns the frontmatter into queries. For example, every light that links to the kitchen:

````markdown
```dataview
TABLE name, device FROM #Home-Assistant/Entity/Light AND [[Kitchen]]
```
````

### Obsidian: Local REST API

Obsidian-side MCP servers such as [mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) talk to Obsidian through the [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin. With it, an assistant on your computer can work on the synced copy of the vault too. You don't need it for an assistant that already talks to Home Assistant.

## Dashboard card

```yaml
type: custom:notes-vault-card
entity: light.kitchen_ceiling   # or device_id: …, or area_id: kitchen
title: Kitchen lamp             # optional
```

## Options

**Settings → Devices & services → Notes Vault → Configure.**

| Option | Default | |
| --- | --- | --- |
| Folder for generated notes | `Home Assistant` | Inside the vault. Empty puts `Entities/`, `Devices/` and `Areas/` at the top. |
| Generate entity / device / area notes | on | |
| Include diagnostic / configuration entities | off | These make up a large share of most installs. |
| Include hidden / disabled | off | |
| Skip these domains | `geo_location` | Feeds create and drop these by the minute. |
| Skip these integrations, labels, devices, entities | none | Skipping a device skips its entities too. |
| Serve the vault over WebDAV | on | |

Filters only stop *empty* notes from being generated. Anything you've written a note on keeps its file whatever the filters say, and an excluded entity gets a file the moment you write one.

## Limitations

- **Agents only take notes if you ask them to.** The actions are there, but no assistant calls them on its own. Put it in their instructions, as in [Notes for your AI](#notes-for-your-ai).
- **Two-way sync can conflict.** If you edit a note in Obsidian while Home Assistant regenerates its frontmatter (after a rename, say), remotely-save sees both sides changed and applies its conflict rule. Home Assistant only writes a note when its metadata really changes, so this is rare, but it can happen.
- **Deleting a generated note doesn't stick.** It comes back, with its template, at the next sync. Exclude the entity or device in the options instead.
- **Notes carry metadata, not live state.** Frontmatter holds names, IDs and relationships, never the current state, so the files don't churn with every sensor update.
- **WebDAV needs an administrator token.** Use HTTPS if you reach Home Assistant from outside your network; the token travels with every request.
- **The UI is added to the frontend from outside.** Home Assistant has no extension point for the more-info dialog or the device page, so a frontend update can move things around. If that happens the notes stop showing in that spot, nothing breaks, and the card and actions keep working.

## License

MIT.
