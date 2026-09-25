<p align="center">
  <img src="custom_components/notes_vault/brand/icon.png" width="128" alt="">
</p>

<h1 align="center">Notes Vault for Home Assistant</h1>

<p align="center">
  Notes on your entities, devices and areas, written from the Home Assistant UI.<br>
  Stored as an Obsidian vault you can sync, link and hand to an AI.
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

Every home has a pile of facts that live nowhere: which breaker the boiler is on, when the smoke detector battery was replaced, why that automation has a 40 second delay. I wanted to write them down next to the thing they're about, in Home Assistant, and still have them as plain Markdown I can open in Obsidian and link together.

Notes Vault keeps a folder of Markdown files inside your Home Assistant config directory. Each entity, device and area gets its own note, generated from the registries, so `[[light.kitchen]]` is a real link in Obsidian. What you write in Home Assistant is the body of that note. The vault syncs with Obsidian over WebDAV through the remotely-save plugin, and every note can be read, searched and written through Home Assistant actions, so an assistant connected to Home Assistant over MCP can work on it too.

## What you get

<table>
  <tr>
    <td width="60%"><img src="docs/images/device-page.png" alt="A Home Assistant device page for Bed Light with a Notes card under Device info. The note says the bulb was swapped for a warm 2700K one, with a link to light.bed_light and a mention of the Bedroom."></td>
    <td width="40%"><img src="docs/images/more-info.png" alt="The more-info dialog of the Bed Light entity, with a Notes section at the bottom showing the path of the note in the vault and its text."></td>
  </tr>
  <tr>
    <td><em>A Notes card on every device and area page.</em></td>
    <td><em>A Notes section in every entity's more-info dialog.</em></td>
  </tr>
</table>

- **Notes in the Home Assistant UI.** Add or edit a note from any entity's more-info dialog, and from device and area pages. Notes are Markdown, and wikilinks work: a link to an entity opens its more-info dialog, a link to a device or area opens its page.
- **A generated note per entity, device and area.** The frontmatter carries the name, IDs, integration, area, device and labels, with links between them, so Obsidian's backlinks and graph show how your home fits together. Renaming an entity ID renames its note and rewrites the links pointing at it.
- **Sync with Obsidian.** A WebDAV endpoint on Home Assistant's own web server, authenticated with a long-lived access token. Built and tested against remotely-save.
- **Actions for AI and automations.** Get, set and append notes, read and write any file, list folders, and search the vault. They return response data, so any Home Assistant MCP server can use them.
- **A dashboard card.** `custom:notes-vault-card` shows and edits the note of one entity, device or area.

## Install

Click the badge above (or add this repository to HACS as a custom **Integration**), install, restart, then add **Notes Vault** from **Settings → Devices & services**.

Setup asks for one thing: the folder, relative to the config directory, that holds the vault (default `notes_vault`). It's created if missing, and it's included in Home Assistant backups like the rest of `/config`.

The first sync runs once Home Assistant has started, and writes one note per included entity, device and area under `Home Assistant/`.

## The vault

```
notes_vault/
├── Home Assistant/
│   ├── Areas/Kitchen.md
│   ├── Devices/Ceiling lamp.md
│   └── Entities/light.kitchen_ceiling.md
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
- ha/entity
- ha/light
---
Bulb is an E27, 2700K. Replaced 2026-01-10.
```

Home Assistant owns the frontmatter keys it writes and leaves everything else alone: the body, and any keys you add yourself. `aliases` and `tags` are merged, so yours stay. A note is only rewritten when its generated metadata changes, which keeps sync conflicts rare.

Everything outside `Home Assistant/` is yours. Notes Vault never touches it except to follow renames of the generated notes.

## Obsidian

### Required: remotely-save

[remotely-save](https://github.com/remotely-save/remotely-save) syncs the vault. Install it from **Settings → Community plugins**, then pick **WebDAV** as the remote service:

| Setting | Value |
| --- | --- |
| Server address | `https://<your Home Assistant>/api/notes_vault/dav` |
| Username | anything, it's ignored |
| Password | a long-lived access token of an **administrator** (your profile → Security) |
| Auth type | `basic` |
| Depth header | `only supports depth='1'` |
| Change the remote base directory | `vault` |

The base directory matters: remotely-save syncs into a folder named after your Obsidian vault unless you set one, and Notes Vault serves the vault as a folder called `vault`. Start with an empty Obsidian vault the first time.

Any other WebDAV client works with the same address and credentials (Finder's **Connect to Server**, rclone, Cyberduck).

### Suggested: Front Matter Title

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

### Suggested: Dataview

[Dataview](https://github.com/blacksmithgu/obsidian-dataview) turns the frontmatter into queries. For example, every light that links to the kitchen:

````markdown
```dataview
TABLE name, device FROM #ha/light AND [[Kitchen]]
```
````

### Optional: Local REST API, for an Obsidian MCP server

Obsidian-side MCP servers such as [mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) talk to Obsidian through the [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin. With it installed, an assistant can work on the synced copy of the vault from your computer.

## AI and MCP

You don't need an Obsidian MCP server to let an assistant use the vault. Any MCP server for Home Assistant that can call actions can use these:

| Action | Does |
| --- | --- |
| `notes_vault.get_note` | Returns the note of an entity, device or area, with its path and wikilink |
| `notes_vault.set_note` | Replaces or appends to that note |
| `notes_vault.search` | Finds notes containing every word of a query |
| `notes_vault.list_files` | Lists a folder |
| `notes_vault.read_file` | Returns any file in the vault |
| `notes_vault.write_file` | Creates or overwrites any file in the vault |
| `notes_vault.delete_file` | Deletes a file or folder |
| `notes_vault.sync` | Re-reads the vault and regenerates the notes now |

`get_note` is available to every user. The rest need an administrator, because the vault can hold anything, not just notes on entities.

Every write fires a `notes_vault_updated` event with the path and, for generated notes, the entity, device or area ID, whichever way it came in (UI, action or WebDAV).

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

- **Two-way sync can conflict.** If you edit a note in Obsidian while Home Assistant regenerates its frontmatter (after a rename, say), remotely-save sees both sides changed and applies its conflict rule. Home Assistant only writes a note when its metadata really changes, so this is rare, but it can happen.
- **Deleting a generated note doesn't stick.** It comes back, empty, at the next sync. Exclude the entity or device in the options instead.
- **Notes carry metadata, not live state.** Frontmatter holds names, IDs and relationships, never the current state, so the files don't churn with every sensor update.
- **A removed entity keeps its note if it had one.** The file stays and gets `ha_removed: true`, so you don't lose what you wrote. An empty one is deleted.
- **WebDAV needs an administrator token.** Use HTTPS if you reach Home Assistant from outside your network; the token travels with every request.
- **The UI is added to the frontend from outside.** Home Assistant has no extension point for the more-info dialog or the device page, so a frontend update can move things around. If that happens the notes stop showing in that spot, nothing breaks, and the card and actions keep working.

## License

MIT.
