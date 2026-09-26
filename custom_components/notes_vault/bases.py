"""Obsidian Bases: views over the generated notes, and the notes that explain them.

Each view is a `.base` file in the Bases folder, embedded in a note next to the index
that says what it's for. Both are written once, like the templates: Obsidian saves
column widths, sorting and the last view used back into the `.base` file, so
regenerating them would undo every tweak and make every sync a conflict. After the
first write they belong to the user.

The files filter on the properties the generator writes (`ha_type`, `domain`,
`area`) rather than on folders, so they keep working whatever the generated folder
is called. The few paths they need are filled in when they're written:
`{{bases}}`, `{{templates}}` and `{{index}}`.

Nothing in here imports Home Assistant.
"""

from __future__ import annotations

#: Shown instead of a note's file name: its friendly name, still a link to it.
_TITLE = """formulas:
  title: file.asLink(if(name, name, file.basename))
"""

DEFAULT_BASES: dict[str, str] = {
    "Rooms.base": """formulas:
  title: file.asLink(if(name, name, file.basename))
  floor: area.asFile().properties.floor
  devices_in_room: if(area.asFile().properties.devices, area.asFile().properties.devices.length, 0)
  entity_count: if(entities, entities.length, 0)
properties:
  formula.title:
    displayName: Name
  formula.floor:
    displayName: Floor
  formula.devices_in_room:
    displayName: Devices
  formula.entity_count:
    displayName: Entities
views:
  - type: cards
    name: Rooms
    filters:
      and:
        - ha_type == "room"
    order:
      - file.name
      - formula.floor
      - formula.devices_in_room
    sort:
      - property: formula.floor
        direction: ASC
  - type: table
    name: Devices by room
    filters:
      and:
        - ha_type == "device"
        - ha_removed != true
    groupBy:
      property: area
      direction: ASC
    order:
      - formula.title
      - manufacturer
      - model
      - formula.entity_count
""",
    "Devices.base": """filters:
  and:
    - ha_type == "device"
    - ha_removed != true
formulas:
  title: file.asLink(if(name, name, file.basename))
  entity_count: if(entities, entities.length, 0)
properties:
  formula.title:
    displayName: Device
  formula.entity_count:
    displayName: Entities
views:
  - type: table
    name: By room
    groupBy:
      property: area
      direction: ASC
    order:
      - formula.title
      - manufacturer
      - model
      - integration
      - formula.entity_count
    columnSize:
      formula.title: 300
  - type: table
    name: By integration
    groupBy:
      property: integration
      direction: ASC
    order:
      - formula.title
      - area
      - manufacturer
      - model
    columnSize:
      formula.title: 300
  - type: table
    name: All devices
    order:
      - formula.title
      - area
      - manufacturer
      - model
      - integration
      - formula.entity_count
    sort:
      - property: formula.title
        direction: ASC
    columnSize:
      formula.title: 300
""",
    "Room.base": """filters:
  and:
    - file.hasLink(this.area.asFile())
    - ha_type != "room"
"""
    + _TITLE
    + """properties:
  formula.title:
    displayName: Name
views:
  - type: cards
    name: Devices
    filters:
      and:
        - ha_type == "device"
    order:
      - formula.title
      - manufacturer
      - model
  - type: table
    name: Entities
    filters:
      and:
        - ha_type == "entity"
        - domain != "automation"
        - domain != "script"
        - domain != "scene"
    groupBy:
      property: domain
      direction: ASC
    order:
      - formula.title
      - device
  - type: table
    name: Automations, scripts and scenes
    filters:
      and:
        - or:
            - domain == "automation"
            - domain == "script"
            - domain == "scene"
    order:
      - formula.title
      - domain
      - description
""",
    "Automations.base": """filters:
  and:
    - ha_type == "entity"
    - or:
        - domain == "automation"
        - domain == "script"
formulas:
  title: file.asLink(if(name, name, file.basename))
  touches: if(entities, entities.length, 0)
properties:
  formula.title:
    displayName: Name
  formula.touches:
    displayName: Entities it touches
views:
  - type: table
    name: All
    order:
      - formula.title
      - domain
      - description
      - mode
      - formula.touches
    sort:
      - property: formula.title
        direction: ASC
    columnSize:
      formula.title: 360
  - type: table
    name: No description
    filters:
      and:
        - '!file.hasProperty("description")'
    order:
      - formula.title
      - formula.touches
    columnSize:
      formula.title: 360
  - type: table
    name: Most connected
    limit: 15
    order:
      - formula.title
      - formula.touches
      - description
    sort:
      - property: formula.touches
        direction: DESC
    columnSize:
      formula.title: 360
""",
    "Integrations.base": """formulas:
  title: file.asLink(if(name, name, file.basename))
  device_count: if(devices, devices.length, 0)
  loose_entities: if(entities, entities.length, 0)
properties:
  formula.title:
    displayName: Name
  formula.device_count:
    displayName: Devices
  formula.loose_entities:
    displayName: Entities without a device
views:
  - type: table
    name: Entities
    filters:
      and:
        - ha_type == "entity"
        - ha_removed != true
    groupBy:
      property: integration
      direction: ASC
    order:
      - formula.title
      - domain
      - device
      - area
    summaries:
      formula.title: Filled
  - type: table
    name: By size
    filters:
      and:
        - ha_type == "integration"
    order:
      - formula.title
      - formula.device_count
      - formula.loose_entities
    sort:
      - property: formula.device_count
        direction: DESC
""",
    "Batteries.base": """filters:
  and:
    - ha_type == "entity"
    - device_class == "battery"
"""
    + _TITLE
    + """properties:
  formula.title:
    displayName: Name
views:
  - type: table
    name: By room
    groupBy:
      property: area
      direction: ASC
    order:
      - formula.title
      - device
      - integration
""",
    "Recently changed.base": """filters:
  and:
    - file.ext == "md"
    - '!file.inFolder("{{templates}}")'
    - '!file.inFolder("{{bases}}")'
    - file.path != "{{index}}"
formulas:
  title: file.asLink(if(name, name, file.basename))
  changed: file.mtime.relative()
properties:
  formula.title:
    displayName: Name
  formula.changed:
    displayName: Changed
views:
  - type: table
    name: Everything
    limit: 40
    order:
      - formula.title
      - file.folder
      - formula.changed
    sort:
      - property: file.mtime
        direction: DESC
  - type: table
    name: Your own notes
    limit: 40
    filters:
      and:
        - '!file.hasProperty("ha_type")'
    order:
      - formula.title
      - file.folder
      - formula.changed
    sort:
      - property: file.mtime
        direction: DESC
""",
    "Cleanup.base": """filters:
  and:
    - file.hasProperty("ha_type")
"""
    + _TITLE
    + """properties:
  formula.title:
    displayName: Name
views:
  - type: table
    name: Removed from Home Assistant
    filters:
      and:
        - ha_removed == true
    order:
      - formula.title
      - ha_type
      - file.folder
  - type: table
    name: Devices with no room
    filters:
      and:
        - ha_type == "device"
        - '!file.hasProperty("area")'
        - ha_removed != true
    groupBy:
      property: integration
      direction: ASC
    order:
      - formula.title
      - manufacturer
      - model
  - type: table
    name: Helpers
    filters:
      and:
        - ha_type == "entity"
        - domain.startsWith("input_")
    groupBy:
      property: domain
      direction: ASC
    order:
      - formula.title
      - area
""",
}

#: The notes that embed the views, next to the index. Keyed by file name.
DEFAULT_VIEW_NOTES: dict[str, str] = {
    "Devices.md": """Every device, by room, by integration, or all together, with how many entities each one has.

![[{{bases}}/Devices.base]]
""",
    "Rooms.md": """The house by room. Each card opens that room's page: its devices, its entities and the automations, scripts and scenes that touch it. The pages are generated, one per area, and follow the areas in Home Assistant.

![[{{bases}}/Rooms.base]]
""",
    "Automations.md": """Every automation and script: what it's for, how it runs, and how many entities it touches. **No description** is the list of ones worth documenting next, and **Most connected** the ones that break the most when something they use changes.

![[{{bases}}/Automations.base]]
""",
    "Integrations.md": """Every entity, grouped by the integration providing it, and every integration by how many devices it brings. An integration's own note lists only its entities without a device; the rest are reached through their device, and this is where they all show up together.

![[{{bases}}/Integrations.base]]
""",
    "Batteries.md": """Every battery sensor, by room, with the device it's in. The notes don't carry live state, so this is the list of what runs on batteries, not of what's low: the battery type and replacement log live in each device's note.

![[{{bases}}/Batteries.base]]
""",
    "Recently changed.md": """What changed in the vault lately, newest first, whether you, an assistant or Home Assistant wrote it. **Your own notes** leaves out the generated ones.

![[{{bases}}/Recently changed.base]]
""",
    "Cleanup.md": """Things in the vault that are probably stale, or that point at something worth tidying up in Home Assistant. Nothing here changes by itself: it's a list to go through now and then.

## Removed from Home Assistant

When something is deleted from Home Assistant, its note stays if anything was written in it, marked `ha_removed: true`, so nothing you wrote is lost. Move what's worth keeping to another note, then delete it. Notes nobody wrote in are deleted with their entity and never show up here.

![[{{bases}}/Cleanup.base#Removed from Home Assistant]]

## Devices with no room

Devices without an area in Home Assistant, grouped by integration. Some really have no room, like a phone or a network client that moves around. The rest never got one: assign it in Home Assistant and the note follows at the next sync.

![[{{bases}}/Cleanup.base#Devices with no room]]

## Helpers

Every helper, by type. Check each one's backlinks to find the ones nothing uses: a helper no automation, script or template links to is probably left over.

![[{{bases}}/Cleanup.base#Helpers]]
""",
}

#: The body of a generated room page: the room base, pointed at its area.
ROOM_PAGE_BODY = """> [!note] Generated by Notes Vault
> Kept in step with the {{area}} area and rewritten on every sync, so edits here are lost. Write about the room in its own note, {{area}}.

![[{{bases}}/Room.base]]
"""


def render_view(
    text: str, *, bases: str, templates: str, index: str, area: str = ""
) -> str:
    """Fill in the vault paths a view or view note refers to."""
    return (
        text.replace("{{area}}", area)
        .replace("{{bases}}", bases)
        .replace("{{templates}}", templates)
        .replace("{{index}}", index)
    )
