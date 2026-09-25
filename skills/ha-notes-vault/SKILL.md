---
name: ha-notes-vault
description: Read and write the Notes Vault in Home Assistant, the Markdown notes kept on every entity, device, area, automation, script and scene, so what you learn about a house survives into the next session. Load this at the start of any task on a Home Assistant instance that has the notes_vault integration (the notes_vault.* actions exist), before investigating or changing anything, not after. The notes may already hold the answer, and anything you learn or change afterwards belongs in them.
---

# Notes Vault

Notes Vault keeps a Markdown note on every entity, device and area in Home Assistant, plus any other notes the user writes, as an Obsidian-format vault. It's the house's memory: where a device physically is, which breaker it's on, why an automation has a delay, what was already tried and didn't work. Home Assistant's registries and states don't hold any of that, and you start every session without it.

You reach it through Home Assistant actions (services) in the `notes_vault` domain. Every read returns response data, so call them with response data enabled.

## The loop

1. **Before working on something, read its note.** Do this first, before investigating logs, history or config: the note may already explain the problem or say what was tried. `notes_vault.get_note` with its `entity_id`, `device_id` or `area_id`. For an automation, script or scene, pass its `entity_id` (`automation.leak_alert`). Read the device's note too when you're about to work on one of its entities: quirks usually live there.
2. **Before asking the user about the house, search.** `notes_vault.search` with a few words. The answer may already be written down.
3. **After you learn something, write it down.** Append to the note with `notes_vault.set_note` and `append: true`. Do it when you learn it, not at the end of the session.
4. **Anything that isn't about one entity, device or area** (the network layout, an ongoing project, a debugging log that spans devices) goes in its own file with `notes_vault.write_file`, and gets linked from the notes it touches.

### What's worth writing

Write what Home Assistant doesn't already know and the next person (or agent) would need:

- Physical facts: location, wiring, breaker, bulb type, battery type, model and firmware when they matter.
- Decisions and their reasons: why the automation waits 40 seconds, why this sensor is ignored at night.
- What you tried that didn't work, and what finally did.
- Maintenance: dated entries, like `- 2026-09-25: replaced the CR2032`.

Don't write current state (it's stale in a minute and Home Assistant already has it), don't restate the frontmatter, and **never write secrets**: no alarm codes, lock PINs, passwords, tokens or Wi-Fi keys. Write where they're kept instead ("code is in the family password manager").

## Calling the actions

| Action | Use it to | Needs admin |
| --- | --- | --- |
| `get_note` | Read the note of one entity, device or area | no |
| `set_note` | Replace, or append to (`append: true`), that note | yes |
| `search` | Find notes containing **every** word of `query` (in path or content). `limit` (default 20), `folder` | yes |
| `read_file` | Read any file by `path` | yes |
| `write_file` | Create or overwrite a file (`append: true` to add to it). Missing folders are created | yes |
| `list_files` | List a `folder` (empty for the top), `recursive: true` for everything below | yes |
| `delete_file` | Delete a file or folder | yes |
| `get_template` | Get a template filled in for an entity, device or area, best fit or by `template` name | no |
| `list_templates` | List templates and what they apply to | no |
| `sync` | Rescan the vault and regenerate notes now | yes |

Target fields (`entity_id`, `device_id`, `area_id`) are mutually exclusive; pass exactly one. `device_id` is the device registry ID (32 hex characters), never the device's name: if you only have the name, `search` for it and take `device_id` from the frontmatter of its note, or get it from the entity registry. `area_id` is the area's ID (`living_room`), not its display name. Paths are relative to the vault root and include `.md`.

How you call an action depends on your tools:

- **An MCP server for Home Assistant** that can call actions with response data (for example a generic "call service" tool): domain `notes_vault`, the action name, the fields as data, and response data on. Home Assistant's built-in MCP Server integration only exposes Assist tools, not arbitrary actions, so it can't reach these.
- **The REST API**, with a long-lived access token of an administrator:

  ```bash
  curl -s -X POST "$HA_URL/api/services/notes_vault/get_note?return_response" \
    -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
    -d '{"entity_id": "light.kitchen_ceiling"}'
  ```

  The result is under `service_response`.

If `notes_vault` actions don't exist, the integration isn't installed or isn't loaded. Say so rather than working around it by writing files on the host.

## Reading a note

`get_note` returns:

```json
{
  "path": "Home Assistant/Devices/Heat pump.md",
  "link": "[[Home Assistant/Devices/Heat pump|Heat pump]]",
  "exists": true,
  "note": "## Where it is\nUtility room, outdoor unit behind the [[Garden]] shed. ...",
  "frontmatter": {"ha_type": "device", "name": "Heat pump", "area": "[[Home Assistant/Areas/Utility room|Utility room]]", "...": "..."},
  "links": {"Garden": {"path": "Home Assistant/Areas/Garden.md", "type": "area", "id": "garden"}},
  "template": null,
  "mtime": 1790326657.1
}
```

- `note` is the body only. The frontmatter is Home Assistant's and comes back separately.
- `links` resolves every wikilink in the body to a path and, for entities, devices and areas, their type and ID. Follow the ones that look relevant (`get_note` for an entity, device or area, `read_file` for anything else).
- For automations and scripts, the frontmatter lists the `entities`, `devices` and `areas` they touch. For entities, it has the `device` and `area`, and for helpers (groups, template sensors, utility meters) the `entities` they're built from. An integration's note lists its devices and the entities without a device; read it with `read_file`, since the actions only target entities, devices and areas.
- **An empty `note` with a `template`** means nobody has written anything yet. `template.body` is the structure the user expects for this kind of thing (see below).

## Writing a note

**First note on something:** take `template.body` from `get_note` (or call `get_template`), fill in the sections you know, drop nothing, leave the ones you don't know empty, and write it with `set_note` and `append: false`. Following the template keeps your notes looking like the user's.

**Note that already has content:** `set_note` with `append: true` adds your text at the end, after a blank line. Add under a short heading or as a dated bullet so it reads well there. Only replace (`append: false`) when you mean to restructure the whole note, and then start from the current `note` so nothing the user wrote is lost.

`set_note` keeps the generated frontmatter. Always use it for entity, device and area notes, not `write_file`: `write_file` replaces the whole file, frontmatter included.

### Links

Link with wikilinks, the way the user does. Bare names resolve: `[[light.kitchen_ceiling]]` for an entity, `[[Heat pump]]` for a device or area by name, `[[Yearly maintenance]]` for any other note. The `link` field from `get_note` and `search` is always safe to use. A link to an entity opens its more-info dialog in Home Assistant; to a device or area, its page. Links are how backlinks and the Obsidian graph connect things, so link the devices, areas and notes you mention.

## The vault layout

```
Home Assistant/            generated, one note per object
  Areas/  Devices/  Entities/  Integrations/  Automations/  Scripts/  Scenes/
  Templates/               the note templates, editable Markdown
  Index.md                 every note with something written in it
anything else              the user's own notes (Maintenance/, Projects/, ...)
```

The folder name `Home Assistant` is the default and can be changed in the integration's options; take real paths from `get_note`, `search` and `list_files` rather than assuming it.

- **`Index.md`** is the quickest way to see what's actually been written. It's regenerated; never edit it.
- **Generated notes can't be deleted for good.** They come back, with their template, at the next sync. The generated folder itself can't be deleted at all.
- A note with `ha_removed: true` in its frontmatter is about something that no longer exists in Home Assistant. Its content was kept on purpose. Leave it unless the user asks.
- **Frontmatter keys Home Assistant writes are its own.** Don't edit them; they're rewritten. Keys the user added are kept.
- Entity notes are named after the entity ID, so renaming an entity ID renames its note and rewrites links to it. You don't need to fix links after a rename.

## Templates

Templates live in `Home Assistant/Templates/` and say in their frontmatter what they apply to (`applies_to`, plus criteria like `domains`, `device_classes`, `integrations`, `entity_domains`, `entity_device_classes`). The most specific match wins. `get_template` renders one for a target with placeholders such as `{{name}}` and `{{area}}` filled in; `list_templates` shows what exists.

If the user asks for a new kind of template, write it with `write_file` into the templates folder. A template's frontmatter looks like:

```markdown
---
ha_template:
  applies_to: device
  entity_device_classes: [battery]
---
## Battery
- Type:

## Battery log
```

## Permissions and events

Only `get_note`, `get_template` and `list_templates` work for non-admin users. Everything else fails with an authorization error for them; tell the user their token needs an administrator.

Every write fires a `notes_vault_updated` event with the `path`, the `source` and, for generated notes, the `entity_id`, `device_id` or `area_id`. The user may have automations on it, so don't write in a loop.
