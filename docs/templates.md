# Writing templates

Templates are Markdown files in `Home Assistant/Templates/`. Each default is written once and never overwritten, so your edits stick and a template you delete stays deleted. New defaults from an update are added. Delete the folder to get all the defaults back.

A note whose body is still exactly its template counts as empty: Home Assistant shows **No notes yet**, filters can remove it, and it's deleted along with its entity. Edit a template and every note still holding the old one is updated to match, and none of the others. Obsidian's own Templates plugin can use the same folder.

## What a template applies to

A template says what it's for in its frontmatter:

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

Every criterion a template sets has to match, and the template setting the most criteria wins. One with none is the fallback for its kind.

## Placeholders

`{{name}}`, `{{entity_id}}`, `{{device}}`, `{{area}}`, `{{manufacturer}}`, `{{model}}`, `{{integration}}` and `{{date}}`, the day the note was first filled in, so it doesn't change on its own. Anything else in double braces is left as is, for your notes app to fill.
