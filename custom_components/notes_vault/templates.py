"""Note templates: which one fits an object, and filling in its placeholders.

A template is a Markdown file in the vault's Templates folder. Its frontmatter says
what it is for:

    ---
    ha_template:
      applies_to: entity        # entity, device or area
      domains: [light]          # optional, entity domains
      device_classes: [battery] # optional
      integrations: [hue]       # optional
      entity_domains: [climate] # devices only: the device has an entity of this domain
      entity_device_classes: [battery]  # devices only, the same for device classes
    ---

The most specific template that matches wins; one with no criteria is the fallback
for its kind. Placeholders use Obsidian's `{{name}}` syntax so the same files work
with Obsidian's own Templates plugin.

Nothing in here imports Home Assistant.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .vault import Note

#: Criteria a template can narrow itself by, and whether each applies to entities,
#: devices or both.
CRITERIA = (
    "domains",
    "device_classes",
    "integrations",
    "entity_domains",
    "entity_device_classes",
)

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


@dataclass(slots=True)
class Template:
    """A parsed template file."""

    name: str
    path: str
    applies_to: str
    body: str
    criteria: dict[str, frozenset[str]] = field(default_factory=dict)

    def matches(self, facts: Mapping[str, Iterable[str]]) -> int | None:
        """Return how specific the match is, or None if the template does not apply.

        Every criterion the template sets must match at least one of the object's
        values. The score is the number of criteria, so a template for battery lights
        beats one for lights, which beats the fallback.
        """
        for key, wanted in self.criteria.items():
            if not wanted & set(facts.get(key, ())):
                return None
        return len(self.criteria)


def parse_template(name: str, path: str, note: Note) -> Template | None:
    """Turn a note into a template, or None if it is not one."""
    spec = note.frontmatter.get("ha_template")
    if not isinstance(spec, dict):
        return None
    applies_to = spec.get("applies_to")
    if applies_to not in ("entity", "device", "area"):
        return None
    criteria: dict[str, frozenset[str]] = {}
    for key in CRITERIA:
        value = spec.get(key)
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        criteria[key] = frozenset(str(v) for v in values)
    return Template(name, path, applies_to, note.body.lstrip("\n"), criteria)


def best_template(
    templates: Iterable[Template], kind: str, facts: Mapping[str, Iterable[str]]
) -> Template | None:
    """Pick the most specific template for an object; ties go to the name."""
    best: tuple[int, str, Template] | None = None
    for template in templates:
        if template.applies_to != kind:
            continue
        score = template.matches(facts)
        if score is None:
            continue
        rank = (-score, template.name)
        if best is None or rank < best[:2]:
            best = (*rank, template)
    return best[2] if best else None


def render(body: str, values: Mapping[str, Any]) -> str:
    """Fill in `{{placeholder}}`s. Unknown ones are left for Obsidian to handle."""

    def sub(match: re.Match[str]) -> str:
        value = values.get(match.group(1))
        return match.group(0) if value is None else str(value)

    return _PLACEHOLDER.sub(sub, body)


#: Written to the Templates folder the first time the integration starts. Each is
#: a starting point: headings to fill in, not text to keep.
DEFAULT_TEMPLATES: dict[str, str] = {
    "Device": """\
---
ha_template:
  applies_to: device
---
## Where it is

## Purchase
- Bought:
- From:
- Price:
- Warranty until:

## Manual and links

## Maintenance log

## Quirks
""",
    "Appliance": """\
---
ha_template:
  applies_to: device
  entity_domains: [climate, water_heater, vacuum, fan, humidifier, lawn_mower]
---
## Where it is

## Purchase
- Model: {{manufacturer}} {{model}}
- Bought:
- Warranty until:
- Installer or service contact:

## Consumables
- Filter or part:
- Replace every:
- Last replaced:

## Maintenance log

## Manual and links

## Quirks
""",
    "Battery device": """\
---
ha_template:
  applies_to: device
  entity_device_classes: [battery]
---
## Where it is

## Battery
- Type:
- Count:

## Battery log

## Quirks
""",
    "Network device": """\
---
ha_template:
  applies_to: device
  integrations: [unifi, fritz, tplink_omada, openwrt, asuswrt, netgear, mikrotik, synology_dsm]
---
## Where it is

## Network
- IP address:
- VLAN:
- Uplink:

## Access
- Admin URL:
- Credentials stored in:

## Firmware log

## Quirks
""",
    "Entity": """\
---
ha_template:
  applies_to: entity
---
## What it's for

## Quirks
""",
    "Light": """\
---
ha_template:
  applies_to: entity
  domains: [light]
---
## Fixture
- Bulb:
- Socket:
- Wattage and color temperature:
- Wall switch:
- Circuit breaker:

## Replacement log

## Quirks
""",
    "Sensor": """\
---
ha_template:
  applies_to: entity
  domains: [sensor, binary_sensor]
---
## Placement

## What it measures and how reliable it is

## Calibration
- Offset:
- Last checked:

## Quirks
""",
    "Automation": """\
---
ha_template:
  applies_to: entity
  domains: [automation, script]
---
## Why it exists

## How it works

## Decisions

## Known issues
""",
    "Scene": """\
---
ha_template:
  applies_to: entity
  domains: [scene]
---
## When it's used

## What it sets

## Known issues
""",
    "Lock and security": """\
---
ha_template:
  applies_to: entity
  domains: [lock, alarm_control_panel]
---
## Where it is

## Keys and access
Where codes and spare keys are kept, never the codes themselves.

## Battery
- Type:
- Last replaced:

## Service contact

## Quirks
""",
    "Area": """\
---
ha_template:
  applies_to: area
---
## Layout

## Electrical
- Circuit breakers:
- Sockets on UPS:

## Network
- Access point:
- Wired ports:

## Things to remember
""",
}
