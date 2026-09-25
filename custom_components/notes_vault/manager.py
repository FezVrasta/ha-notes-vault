"""Keeps the generated notes in step with Home Assistant's registries.

Every entity, device and area gets a Markdown file whose frontmatter Home Assistant
owns and whose body belongs to the user. The body is the note shown in the Home
Assistant UI; the frontmatter is what makes ``[[light.kitchen]]`` a useful link in
Obsidian.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    floor_registry as fr,
)
from homeassistant.helpers import (
    label_registry as lr,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.loader import Integration, async_get_integrations
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_FOLDER,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_EXCLUDE_LABELS,
    CONF_GENERATE_AREAS,
    CONF_GENERATE_DEVICES,
    CONF_GENERATE_ENTITIES,
    CONF_INCLUDE_CONFIG,
    CONF_INCLUDE_DIAGNOSTIC,
    CONF_INCLUDE_DISABLED,
    CONF_INCLUDE_HIDDEN,
    DEFAULT_OPTIONS,
    DOMAIN,
    DOMAIN_FOLDERS,
    EVENT_NOTE_UPDATED,
    KIND_AREA,
    KIND_DEVICE,
    KIND_ENTITY,
    KIND_FOLDERS,
    SYNC_DEBOUNCE,
)
from .templates import (
    DEFAULT_TEMPLATES,
    Template,
    best_template,
    parse_template,
    render,
)
from .vault import (
    MARKDOWN_SUFFIX,
    InvalidPathError,
    Note,
    NotFoundError,
    Vault,
    VaultError,
    link_target,
    parse_note,
    plain_text,
    render_note,
    safe_name,
    wikilink,
)

_LOGGER = logging.getLogger(__name__)

#: Frontmatter keys the generator owns. Anything else a user adds is left alone.
MANAGED_KEYS: frozenset[str] = frozenset(
    {
        "ha_type",
        "ha_id",
        "entity_id",
        "device_id",
        "area_id",
        "name",
        "domain",
        "integration",
        "device",
        "area",
        "floor",
        "labels",
        "device_class",
        "unit",
        "entity_category",
        "manufacturer",
        "model",
        "via_device",
        "entities",
        "devices",
        "areas",
        "description",
        "mode",
        "ha_url",
        "ha_removed",
    }
)
#: Keys the generator adds to without taking over: users keep their own values.
ADDITIVE_KEYS = ("aliases", "tags")

type DocKey = tuple[str, str]
#: A template and the placeholder values to render it with, for one note.
type Plan = tuple[Template, dict[str, Any]]


def _all_devices(dev_reg: dr.DeviceRegistry) -> list[dr.DeviceEntry]:
    """List every device without the mapping access 2026.9 deprecated.

    From 2026.9, iterating `devices` yields the entries and `.values()` is reported
    as deprecated; before that, iterating it yields device IDs.
    """
    return [
        item if isinstance(item, dr.DeviceEntry) else dev_reg.devices[item]
        for item in dev_reg.devices
    ]


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()


def _prefill_key(key: DocKey) -> str:
    return f"{key[0]}:{key[1]}"


#: The target of a wikilink: `[[target]]`, `[[target|label]]`, `[[target#heading]]`.
_WIKILINK = re.compile(r"\[\[([^\]|#^]+)")


class LockedFolderError(VaultError):
    """The folder belongs to the generator and can't be moved or deleted by hand."""


@dataclass(slots=True)
class Doc:
    """The generated part of one note."""

    kind: str
    ha_id: str
    name: str
    #: Path the note gets when it is first created, and the base name used to decide
    #: whether an existing file needs renaming.
    folder: str
    stem: str
    #: False when the filters exclude it. An excluded object keeps its file only while
    #: the file holds a note.
    wanted: bool
    managed: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> DocKey:
        """Identify the doc across renames."""
        return (self.kind, self.ha_id)


def _user_keys(frontmatter: Mapping[str, Any]) -> set[str]:
    return set(frontmatter) - MANAGED_KEYS - set(ADDITIVE_KEYS)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _plain(value: Any) -> Any:
    """Reduce a value to types the YAML safe dumper accepts.

    Enums and other str subclasses (entity names are often one) are refused by
    `yaml.safe_dump`, and state attributes can hold anything.
    """
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


#: Every tag the generator writes lives under this, and is rewritten on each sync.
TAG_ROOT = "Home-Assistant"
#: Written by versions before 0.1.0 and removed on sync.
_LEGACY_TAG_ROOT = "ha/"


def _is_generated_tag(tag: Any) -> bool:
    return isinstance(tag, str) and (
        tag == TAG_ROOT or tag.startswith((f"{TAG_ROOT}/", _LEGACY_TAG_ROOT))
    )


def tag_part(name: str) -> str:
    """Turn a display name into one level of an Obsidian tag.

    Tags cannot hold spaces or most punctuation, so "Air Quality" becomes
    "Air-Quality" and "FRITZ!Box" becomes "FRITZ-Box".
    """
    return re.sub(r"[^\w]+", "-", name, flags=re.UNICODE).strip("-") or "Other"


def _stem_matches(stem: str, base: str) -> bool:
    """Return whether an existing file name still fits the object's name."""
    return (
        stem == base
        or re.fullmatch(re.escape(base) + r" \([0-9a-f]{6,}\)", stem) is not None
    )


def merge_frontmatter(
    current: dict[str, Any], doc: Doc, previous_name: str | None
) -> dict[str, Any]:
    """Merge the generated keys into a note's frontmatter, keeping the user's keys."""
    merged: dict[str, Any] = {
        key: _plain(value)
        for key, value in doc.managed.items()
        if value is not None and value not in ([], "")
    }
    aliases = [a for a in _as_list(current.get("aliases")) if a != previous_name]
    for alias in map(_plain, doc.aliases):
        if alias not in aliases:
            aliases.append(alias)
    if aliases:
        merged["aliases"] = aliases
    # Tags under the generated namespace are replaced; the user's own are kept.
    tags = [t for t in _as_list(current.get("tags")) if not _is_generated_tag(t)]
    for tag in doc.tags:
        if tag not in tags:
            tags.append(tag)
    if tags:
        merged["tags"] = tags
    merged.update(
        (key, value)
        for key, value in current.items()
        if key not in MANAGED_KEYS and key not in ADDITIVE_KEYS
    )
    return merged


class NotesVault:
    """Owns the vault for one config entry."""

    def __init__(
        self, hass: HomeAssistant, vault: Vault, options: Mapping[str, Any]
    ) -> None:
        """Set up the manager. Nothing touches the disk until `async_start`."""
        self.hass = hass
        self.vault = vault
        self.options = {**DEFAULT_OPTIONS, **options}
        self.base = Vault.normalize(self.options[CONF_BASE_FOLDER])
        #: Where each generated note currently lives. Rebuilt from the frontmatter on
        #: start, so a note moved in Obsidian is followed rather than duplicated.
        self.index: dict[DocKey, str] = {}
        #: Frontmatter last written or read per key, to skip unchanged files.
        self._written: dict[DocKey, tuple[float, dict[str, Any], str]] = {}
        #: The template body each generated note was pre-filled with, by key, so a note
        #: still holding exactly that body counts as empty. Kept in .storage rather
        #: than in the note, so nothing shows up in Obsidian's properties.
        self._prefill: dict[str, dict[str, str]] = {}
        self._templates_store: Store[dict[str, list[str]]] = Store(
            hass, 1, f"{DOMAIN}.templates"
        )
        self._store: Store[dict[str, dict[str, str]]] = Store(
            hass, 1, f"{DOMAIN}.prefill"
        )
        self.lock = asyncio.Lock()
        self._unsubs: list[Callable[[], None]] = []
        self._debouncer: Debouncer | None = None
        self.last_sync: dict[str, int] = {}
        self._base_url: str | None = None
        #: Display names of integrations and entity domains ("air_quality" is
        #: "Air Quality"), used for readable tags. Filled before each sync.
        self._integration_names: dict[str, str] = {}

    # -- Lifecycle -----------------------------------------------------------------

    async def async_start(self) -> None:
        """Scan the vault, generate the notes and start following registry changes."""
        self._prefill = await self._store.async_load() or {}
        await self.hass.async_add_executor_job(self.vault.ensure)
        stored = await self._templates_store.async_load() or {}
        seeded = await self.hass.async_add_executor_job(
            self._seed_templates, set(stored.get("seeded", []))
        )
        await self._templates_store.async_save({"seeded": sorted(seeded)})
        await self.hass.async_add_executor_job(self._scan)
        self._debouncer = Debouncer(
            self.hass,
            _LOGGER,
            cooldown=SYNC_DEBOUNCE,
            immediate=False,
            function=self.async_sync,
        )
        for event_type in (
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            ar.EVENT_AREA_REGISTRY_UPDATED,
            fr.EVENT_FLOOR_REGISTRY_UPDATED,
            lr.EVENT_LABEL_REGISTRY_UPDATED,
        ):
            self._unsubs.append(self.hass.bus.async_listen(event_type, self._schedule))
        # Entities without a unique ID live only in the state machine. Their arrival
        # and removal are the only state changes worth a sync.
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                self._schedule,
                event_filter=self._is_add_or_remove,
            )
        )
        await self.async_sync()

    async def async_stop(self) -> None:
        """Stop following changes."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._debouncer:
            self._debouncer.async_cancel()

    @callback
    def _is_add_or_remove(self, data: Mapping[str, Any]) -> bool:
        if (data["old_state"] is None) == (data["new_state"] is None):
            return False
        return er.async_get(self.hass).async_get(data["entity_id"]) is None

    @callback
    def _schedule(self, _event: Event | None = None) -> None:
        if self._debouncer:
            self._debouncer.async_schedule_call()

    # -- Building the docs ---------------------------------------------------------

    def _integration_name(self, domain: str) -> str:
        return self._integration_names.get(domain) or domain.replace("_", " ").title()

    async def _async_load_integration_names(self) -> None:
        """Look up the display name of every domain and integration in use."""
        domains = {e.domain for e in er.async_get(self.hass).entities.values()}
        domains |= {e.platform for e in er.async_get(self.hass).entities.values()}
        domains |= {s.domain for s in self.hass.states.async_all()}
        domains |= {e.domain for e in self.hass.config_entries.async_entries()}
        missing = domains - set(self._integration_names)
        if not missing:
            return
        found = await async_get_integrations(self.hass, missing)
        for domain, integration in found.items():
            if isinstance(integration, Integration):
                self._integration_names[domain] = integration.name

    def _folder(self, kind: str, domain: str | None = None) -> str:
        """Return the generated folder for a kind of note.

        Automations, scripts and scenes get folders of their own rather than sitting
        among thousands of sensors.
        """
        sub = DOMAIN_FOLDERS.get(domain or "") or KIND_FOLDERS[kind]
        return f"{self.base}/{sub}" if self.base else sub

    @property
    def generated_folders(self) -> set[str]:
        """Every folder the generator writes notes to."""
        return {self._folder(k) for k in KIND_FOLDERS} | {
            self._folder(KIND_ENTITY, d) for d in DOMAIN_FOLDERS
        }

    @callback
    def _logic_details(self, domain: str, entity_id: str) -> dict[str, Any]:
        """Describe an automation, script or scene: what it's for and what it touches.

        The referenced entities, devices and areas become links, so in Obsidian a
        light's backlinks show every automation that controls it.
        """
        # Imported here: these integrations may not be loaded, and a custom
        # integration shouldn't import them at module level just for this.
        from homeassistant.components import (  # noqa: PLC0415
            automation,
            script,
        )
        from homeassistant.components.homeassistant import (  # noqa: PLC0415
            scene,
        )

        details: dict[str, Any] = {}
        if domain == "automation":
            details["entities"] = automation.entities_in_automation(
                self.hass, entity_id
            )
            details["devices"] = automation.devices_in_automation(self.hass, entity_id)
            details["areas"] = automation.areas_in_automation(self.hass, entity_id)
            component = self.hass.data.get(automation.DATA_COMPONENT)
        elif domain == "script":
            details["entities"] = script.entities_in_script(self.hass, entity_id)
            details["devices"] = script.devices_in_script(self.hass, entity_id)
            details["areas"] = script.areas_in_script(self.hass, entity_id)
            component = self.hass.data.get(script.DOMAIN)
        else:
            details["entities"] = scene.entities_in_scene(self.hass, entity_id)
            component = None
        entity = component.get_entity(entity_id) if component else None
        config = getattr(entity, "raw_config", None) or {}
        details["description"] = config.get("description") or None
        details["mode"] = config.get("mode")
        return details

    def _url(self, path: str) -> str | None:
        return f"{self._base_url}{path}" if self._base_url else None

    @callback
    def build_docs(self) -> dict[DocKey, Doc]:
        """Describe every entity, device and area as it should appear in the vault."""
        opts = self.options
        try:
            self._base_url = get_url(self.hass, prefer_external=True)
        except NoURLAvailableError:
            self._base_url = None
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        floor_reg = fr.async_get(self.hass)
        label_reg = lr.async_get(self.hass)

        def label_names(ids: set[str]) -> list[str]:
            names = [lbl.name for i in ids if (lbl := label_reg.async_get_label(i))]
            return sorted(names)

        exclude_labels = set(opts[CONF_EXCLUDE_LABELS])
        exclude_devices = set(opts[CONF_EXCLUDE_DEVICES])
        exclude_entities = set(opts[CONF_EXCLUDE_ENTITIES])
        exclude_domains = set(opts[CONF_EXCLUDE_DOMAINS])
        exclude_integrations = set(opts[CONF_EXCLUDE_INTEGRATIONS])

        docs: dict[DocKey, Doc] = {}

        # Areas first: their stems are needed for links from devices and entities.
        for area in area_reg.areas.values():
            floor = floor_reg.async_get_floor(area.floor_id) if area.floor_id else None
            doc = Doc(
                kind=KIND_AREA,
                ha_id=area.id,
                name=area.name,
                folder=self._folder(KIND_AREA),
                stem=safe_name(area.name),
                wanted=opts[CONF_GENERATE_AREAS] and not (area.labels & exclude_labels),
                aliases=sorted({area.name, *area.aliases}),
                tags=[f"{TAG_ROOT}/Area"],
            )
            doc.managed = {
                "ha_type": KIND_AREA,
                "ha_id": area.id,
                "area_id": area.id,
                "name": area.name,
                "floor": floor.name if floor else None,
                "labels": label_names(area.labels),
                "ha_url": self._url(f"/config/areas/area/{area.id}"),
            }
            docs[doc.key] = doc

        for device in _all_devices(dev_reg):
            name = device.name_by_user or device.name or device.model or device.id
            integrations = sorted(
                {
                    entry.domain
                    for entry_id in device.config_entries
                    if (entry := self.hass.config_entries.async_get_entry(entry_id))
                }
            )
            wanted = (
                opts[CONF_GENERATE_DEVICES]
                and device.id not in exclude_devices
                and not (device.labels & exclude_labels)
                and not (integrations and set(integrations) <= exclude_integrations)
                and (opts[CONF_INCLUDE_DISABLED] or device.disabled_by is None)
            )
            doc = Doc(
                kind=KIND_DEVICE,
                ha_id=device.id,
                name=name,
                folder=self._folder(KIND_DEVICE),
                stem=safe_name(name),
                wanted=bool(wanted),
                aliases=[name],
                tags=[
                    f"{TAG_ROOT}/Device",
                    *(
                        f"{TAG_ROOT}/Device/{tag_part(self._integration_name(d))}"
                        for d in integrations
                    ),
                ],
            )
            doc.managed = {
                "ha_type": KIND_DEVICE,
                "ha_id": device.id,
                "device_id": device.id,
                "name": name,
                "manufacturer": device.manufacturer,
                "model": device.model,
                "integration": integrations,
                "labels": label_names(device.labels),
                "ha_url": self._url(f"/config/devices/device/{device.id}"),
                # Filled in once every path is known.
                "area": device.area_id,
                "via_device": device.via_device_id,
            }
            docs[doc.key] = doc

        seen_entity_ids: set[str] = set()
        for entry in ent_reg.entities.values():
            seen_entity_ids.add(entry.entity_id)
            device = dev_reg.async_get(entry.device_id) if entry.device_id else None
            state = self.hass.states.get(entry.entity_id)
            # The registry name, not the state's friendly name: a sync triggered by a
            # rename runs before the entity has written its new state.
            name = (
                er.async_get_full_entity_name(self.hass, entry)
                or (state.name if state else None)
                or entry.entity_id
            )
            wanted = (
                opts[CONF_GENERATE_ENTITIES]
                and entry.entity_id not in exclude_entities
                and entry.domain not in exclude_domains
                and entry.platform not in exclude_integrations
                and not (entry.labels & exclude_labels)
                and not (device and device.id in exclude_devices)
                and (opts[CONF_INCLUDE_HIDDEN] or entry.hidden_by is None)
                and (opts[CONF_INCLUDE_DISABLED] or entry.disabled_by is None)
                and (
                    entry.entity_category is None
                    or (
                        entry.entity_category == "diagnostic"
                        and opts[CONF_INCLUDE_DIAGNOSTIC]
                    )
                    or (entry.entity_category == "config" and opts[CONF_INCLUDE_CONFIG])
                )
            )
            doc = self._entity_doc(
                ha_id=entry.id,
                entity_id=entry.entity_id,
                name=name,
                wanted=bool(wanted),
            )
            doc.managed.update(
                {
                    "integration": entry.platform,
                    "device": entry.device_id,
                    "area": entry.area_id or (device.area_id if device else None),
                    "labels": label_names(entry.labels),
                    "device_class": entry.device_class or entry.original_device_class,
                    "unit": entry.unit_of_measurement,
                    "entity_category": (
                        str(entry.entity_category) if entry.entity_category else None
                    ),
                }
            )
            docs[doc.key] = doc

        for state in self.hass.states.async_all():
            if state.entity_id in seen_entity_ids:
                continue
            doc = self._entity_doc(
                ha_id=state.entity_id,
                entity_id=state.entity_id,
                name=state.name,
                wanted=bool(
                    opts[CONF_GENERATE_ENTITIES]
                    and state.entity_id not in exclude_entities
                    and state.domain not in exclude_domains
                    and (
                        opts[CONF_INCLUDE_HIDDEN] or not state.attributes.get("hidden")
                    )
                ),
            )
            doc.managed["device_class"] = state.attributes.get("device_class")
            doc.managed["unit"] = state.attributes.get("unit_of_measurement")
            docs[doc.key] = doc

        for doc in docs.values():
            if doc.kind == KIND_ENTITY and doc.managed["domain"] in DOMAIN_FOLDERS:
                doc.managed.update(
                    self._logic_details(doc.managed["domain"], doc.managed["entity_id"])
                )
        return docs

    def _entity_doc(
        self, *, ha_id: str, entity_id: str, name: str, wanted: bool
    ) -> Doc:
        domain = entity_id.split(".", 1)[0]
        doc = Doc(
            kind=KIND_ENTITY,
            ha_id=ha_id,
            name=name,
            folder=self._folder(KIND_ENTITY, domain),
            stem=entity_id,
            wanted=wanted,
            aliases=[name] if name and name != entity_id else [],
            tags=[
                f"{TAG_ROOT}/Entity",
                f"{TAG_ROOT}/Entity/{tag_part(self._integration_name(domain))}",
            ],
        )
        doc.managed = {
            "ha_type": KIND_ENTITY,
            "ha_id": ha_id,
            "entity_id": entity_id,
            "name": name,
            "domain": domain,
            "ha_url": self._url(f"/history?entity_id={entity_id}"),
        }
        return doc

    # -- Applying them to disk ------------------------------------------------------

    def _scan(self) -> None:
        """Rebuild the index from the frontmatter of every note in the vault."""
        index: dict[DocKey, str] = {}
        for path in self.vault.iter_markdown():
            try:
                fm = self.vault.read_frontmatter(path)
            except (OSError, VaultError):
                continue
            kind, ha_id = fm.get("ha_type"), fm.get("ha_id")
            if kind in (KIND_ENTITY, KIND_DEVICE, KIND_AREA) and isinstance(ha_id, str):
                key = (kind, ha_id)
                # Two files claiming one object: keep the one in the generated folder.
                if key in index and index[key].startswith(self._folder(kind) + "/"):
                    continue
                index[key] = path
        self.index = index
        self._written.clear()

    def _plan_paths(self, docs: dict[DocKey, Doc]) -> dict[DocKey, str]:
        """Decide the path of every note that should exist, following renames."""
        taken: set[str] = set()
        planned: dict[DocKey, str] = {}
        pending: list[Doc] = []
        generated = self.generated_folders
        for key, doc in docs.items():
            current = self.index.get(key)
            if current is None:
                pending.append(doc)
                continue
            current_stem = PurePosixPath(link_target(current)).name
            parent = PurePosixPath(current).parent.as_posix()
            # Only move files still where the generator put them: a note the user
            # moved or renamed in Obsidian stays where they put it. A note in the
            # wrong generated folder (an automation among the entities) moves.
            if parent in generated and (
                parent != doc.folder or not _stem_matches(current_stem, doc.stem)
            ):
                pending.append(doc)
                continue
            planned[key] = current
            taken.add(current.lower())
        for doc in sorted(pending, key=lambda d: d.ha_id):
            path = f"{doc.folder}/{doc.stem}{MARKDOWN_SUFFIX}"
            if path.lower() in taken:
                path = f"{doc.folder}/{doc.stem} ({doc.ha_id[:6]}){MARKDOWN_SUFFIX}"
            planned[doc.key] = path
            taken.add(path.lower())
        return planned

    def _resolve_links(self, docs: dict[DocKey, Doc], paths: dict[DocKey, str]) -> None:
        """Replace the raw IDs held in link fields with wikilinks."""

        def link(kind: str, ha_id: str | None) -> str | None:
            if not ha_id or (kind, ha_id) not in paths:
                return None
            doc = docs[(kind, ha_id)]
            return wikilink(paths[(kind, ha_id)], doc.name)

        devices_by_area: dict[str, list[str]] = {}
        entities_by_device: dict[str, list[str]] = {}
        for doc in docs.values():
            m = doc.managed
            if doc.kind == KIND_ENTITY:
                device_id = m.get("device")
                m["device"] = link(KIND_DEVICE, device_id)
                m["area"] = link(KIND_AREA, m.get("area"))
                if device_id and doc.key in paths:
                    entities_by_device.setdefault(device_id, []).append(
                        wikilink(paths[doc.key], doc.name)
                    )
            elif doc.kind == KIND_DEVICE:
                area_id = m.get("area")
                m["area"] = link(KIND_AREA, area_id)
                m["via_device"] = link(KIND_DEVICE, m.get("via_device"))
                if area_id and doc.key in paths:
                    devices_by_area.setdefault(area_id, []).append(
                        wikilink(paths[doc.key], doc.name)
                    )
        by_entity_id = {
            d.managed["entity_id"]: k for k, d in docs.items() if d.kind == KIND_ENTITY
        }

        def links(kind: str, ids: list[str]) -> list[str]:
            keys = (
                [by_entity_id.get(i) for i in ids]
                if kind == KIND_ENTITY
                else [(kind, i) for i in ids]
            )
            return sorted(
                wikilink(paths[k], docs[k].name) for k in keys if k and k in paths
            )

        for doc in docs.values():
            m = doc.managed
            if doc.kind == KIND_ENTITY and m["domain"] in DOMAIN_FOLDERS:
                m["entities"] = links(KIND_ENTITY, m.get("entities") or [])
                m["devices"] = links(KIND_DEVICE, m.get("devices") or [])
                m["areas"] = links(KIND_AREA, m.get("areas") or [])
        for doc in docs.values():
            if doc.kind == KIND_DEVICE:
                doc.managed["entities"] = sorted(entities_by_device.get(doc.ha_id, []))
            elif doc.kind == KIND_AREA:
                doc.managed["devices"] = sorted(devices_by_area.get(doc.ha_id, []))

    def _read_existing(self, path: str) -> tuple[Note | None, float | None]:
        try:
            info = self.vault.stat(path)
        except NotFoundError:
            return None, None
        return self.vault.read_note(path), info.mtime

    def _render_plan(self, key: DocKey, plan: Plan | None) -> str | None:
        """Render the template a note is pre-filled with."""
        if plan is None:
            return None
        template, values = plan
        record = self._prefill.get(_prefill_key(key))
        # The date the note was first filled in, so it doesn't change every day.
        date = record.get("date") if record else None
        return render(template.body, {**values, "date": date or values.get("date")})

    def _is_untouched(
        self, key: DocKey, body: str, rendered: str | None = None
    ) -> bool:
        """Return whether a note body is empty or still exactly its template."""
        if not body.strip():
            return True
        record = self._prefill.get(_prefill_key(key))
        if record and record.get("hash") == _digest(body):
            return True
        return rendered is not None and body == rendered

    def _write_doc(self, key: DocKey, doc: Doc, path: str, plan: Plan | None) -> str:
        """Write one note if its frontmatter or pre-filled body changed.

        Returns the stats bucket. An untouched body (empty, or exactly its template)
        is re-rendered from the current template; anything the user wrote is kept.
        """
        cached = self._written.get(key)
        try:
            mtime: float | None = self.vault.stat(path).mtime
        except NotFoundError:
            mtime = None
        if cached and mtime is not None and cached[0] == mtime:
            current_fm, body = cached[1], cached[2]
        elif mtime is not None:
            note = self.vault.read_note(path)
            if not note.valid:
                _LOGGER.warning("Skipping %s: its frontmatter is not valid YAML", path)
                return "unchanged"
            current_fm, body = note.frontmatter, note.body
        else:
            current_fm, body = {}, ""
        merged = merge_frontmatter(current_fm, doc, current_fm.get("name"))
        rendered = self._render_plan(key, plan)
        new_body = body
        if rendered is not None and self._is_untouched(key, body, rendered):
            new_body = rendered
            record = self._prefill.get(_prefill_key(key)) or {}
            self._prefill[_prefill_key(key)] = {
                "hash": _digest(rendered),
                "date": record.get("date") or plan[1].get("date"),
                "template": plan[0].name,
            }
        if mtime is not None and merged == current_fm and new_body == body:
            self._written[key] = (mtime, merged, body)
            return "unchanged"
        created = self.vault.write_text(path, render_note(merged, new_body))
        self._written[key] = (self.vault.stat(path).mtime, merged, new_body)
        return "created" if created else "updated"

    def _apply(
        self, docs: dict[DocKey, Doc], plans: dict[DocKey, Plan] | None = None
    ) -> dict[str, int]:
        """Bring the files on disk in line with the docs. Runs in the executor."""
        plans = plans or {}
        stats = {"created": 0, "updated": 0, "renamed": 0, "deleted": 0, "unchanged": 0}

        # Which excluded objects still have a note worth keeping?
        keep: dict[DocKey, Doc] = {}
        for key, doc in docs.items():
            if doc.wanted:
                keep[key] = doc
                continue
            path = self.index.get(key)
            if path is None:
                continue
            note, _ = self._read_existing(path)
            if note is None:
                continue
            if (
                not self._is_untouched(
                    key, note.body, self._render_plan(key, plans.get(key))
                )
                or _user_keys(note.frontmatter)
                or not note.valid
            ):
                keep[key] = doc
            else:
                self.vault.delete(path)
                self.index.pop(key, None)
                self._written.pop(key, None)
                stats["deleted"] += 1

        paths = self._plan_paths(keep)
        self._resolve_links(keep, paths)

        renames: dict[str, str] = {}
        for key, doc in keep.items():
            path = paths[key]
            old = self.index.get(key)
            if old and old != path:
                try:
                    self.vault.resolve(path).parent.mkdir(parents=True, exist_ok=True)
                    self.vault.move(old, path, overwrite=False)
                    renames[link_target(old)] = link_target(path)
                    stats["renamed"] += 1
                except NotFoundError:
                    pass
                except VaultError:
                    _LOGGER.warning("Could not rename %s to %s", old, path)
                    path = old
                    paths[key] = old
            self.index[key] = path

            try:
                stats[self._write_doc(key, doc, path, plans.get(key))] += 1
            except (OSError, VaultError, yaml.YAMLError):
                # One unwritable note must not stop the rest of the vault.
                _LOGGER.exception("Could not update %s", path)

        # Objects that no longer exist in Home Assistant.
        for key in [k for k in self.index if k not in docs]:
            path = self.index[key]
            try:
                note = self.vault.read_note(path)
            except NotFoundError:
                self.index.pop(key)
                continue
            if (
                self._is_untouched(key, note.body)
                and not _user_keys(note.frontmatter)
                and note.valid
            ):
                self.vault.delete(path)
                self.index.pop(key)
                self._written.pop(key, None)
                self._prefill.pop(_prefill_key(key), None)
                stats["deleted"] += 1
            elif note.valid and not note.frontmatter.get("ha_removed"):
                note.frontmatter["ha_removed"] = True
                self.vault.write_text(path, render_note(note.frontmatter, note.body))
                stats["updated"] += 1

        if renames:
            self.vault.rewrite_links(renames)
            self._written.clear()
        return stats

    async def async_sync(self) -> dict[str, int]:
        """Regenerate the notes now."""
        await self._async_load_integration_names()
        templates = await self.hass.async_add_executor_job(self._load_templates)
        async with self.lock:
            docs = self.build_docs()
            plans = self._plan_templates(docs, templates)
            stats = await self.hass.async_add_executor_job(self._apply, docs, plans)
        self._store.async_delay_save(lambda: self._prefill, 5)
        self.last_sync = stats
        if any(stats[k] for k in ("created", "updated", "renamed", "deleted")):
            _LOGGER.debug("Vault sync: %s", stats)
        return stats

    async def async_rescan(self) -> dict[str, int]:
        """Forget the index, re-read the vault and regenerate."""
        async with self.lock:
            await self.hass.async_add_executor_job(self._scan)
        return await self.async_sync()

    # -- Notes on objects ----------------------------------------------------------

    @callback
    def resolve_target(
        self,
        *,
        entity_id: str | None = None,
        device_id: str | None = None,
        area_id: str | None = None,
    ) -> DocKey:
        """Turn an entity, device or area ID into the key of its note."""
        if entity_id:
            entry = er.async_get(self.hass).async_get(entity_id)
            if entry:
                return (KIND_ENTITY, entry.id)
            if self.hass.states.get(entity_id) is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_entity",
                    translation_placeholders={"target": entity_id},
                )
            return (KIND_ENTITY, entity_id)
        if device_id:
            if dr.async_get(self.hass).async_get(device_id) is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_device",
                    translation_placeholders={"target": device_id},
                )
            return (KIND_DEVICE, device_id)
        if area_id:
            if ar.async_get(self.hass).async_get_area(area_id) is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_area",
                    translation_placeholders={"target": area_id},
                )
            return (KIND_AREA, area_id)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_target")

    async def async_get_note(self, key: DocKey) -> dict[str, Any]:
        """Return the note attached to an object."""
        path = self.index.get(key)
        note: Note | None = None
        mtime: float | None = None
        if path:
            note, mtime = await self.hass.async_add_executor_job(
                self._read_existing, path
            )
        if note is None:
            docs = self.build_docs()
            doc = docs.get(key)
            path = path or (
                f"{doc.folder}/{doc.stem}{MARKDOWN_SUFFIX}" if doc else None
            )
        # An empty note comes with the template that fits it, so the UI can offer it
        # and an assistant knows what shape of note is expected. A note still holding
        # exactly the template it was pre-filled with counts as empty.
        template = None
        if (
            note is not None
            and note.body.strip()
            and self._is_untouched(key, note.body)
        ):
            record = self._prefill.get(_prefill_key(key), {})
            template = {"name": record.get("template"), "body": note.body.strip("\n")}
            note = Note(note.frontmatter, "")
        elif note is None or not note.body.strip():
            template = await self.async_template(key)
        return {
            "template": template,
            "path": path,
            "link": wikilink(path, PurePosixPath(link_target(path)).name)
            if path
            else None,
            "exists": note is not None,
            "note": note.body.strip("\n") if note else "",
            "frontmatter": note.frontmatter if note else {},
            "links": await self.async_resolve_links(note.body) if note else {},
            "mtime": mtime,
        }

    def _markdown_paths(self) -> list[str]:
        """List every note in the vault. Runs in the executor."""
        return sorted(self.vault.iter_markdown())

    @callback
    def key_for_path(self, path: str) -> DocKey | None:
        """Return the entity, device or area a generated note at `path` is about."""
        path = self.vault.normalize(path)
        return next((k for k, p in self.index.items() if p == path), None)

    @callback
    def ha_target(self, path: str) -> dict[str, str] | None:
        """Return the entity, device or area a generated note belongs to."""
        key = self.key_for_path(path)
        if key is None:
            return None
        kind, ha_id = key
        if kind == KIND_ENTITY:
            entry = er.async_get(self.hass).async_get(ha_id)
            return {"type": kind, "id": entry.entity_id if entry else ha_id}
        return {"type": kind, "id": ha_id}

    async def async_resolve_links(self, text: str) -> dict[str, dict[str, str]]:
        """Map each wikilink target in the text to the note and object behind it.

        Targets resolve the way Obsidian resolves them: by full path, or by file name
        alone. Each resolved link has the note's `path`, and for generated notes the
        `type` and `id` of the entity, device or area. Unresolved links are left out.
        """
        targets = {m.group(1).strip() for m in _WIKILINK.finditer(text)}
        if not targets:
            return {}
        paths = await self.hass.async_add_executor_job(self._markdown_paths)
        by_target: dict[str, str] = {}
        for path in paths:
            full = link_target(path)
            by_target.setdefault(full, path)
            by_target.setdefault(PurePosixPath(full).name, path)
        links: dict[str, dict[str, str]] = {}
        for target in targets:
            if (path := by_target.get(target)) is None:
                continue
            links[target] = {"path": path, **(self.ha_target(path) or {})}
        return links

    def _backlinks(self, path: str) -> list[dict[str, str]]:
        """Find the notes linking to a path, and how. Runs in the executor.

        The snippet is readable text, not source: a link from a property reads
        `device: Back Garden`, a link in the body is its line with links reduced to
        their labels.
        """
        full = link_target(path)
        stem = PurePosixPath(full).name
        pattern = re.compile(
            r"\[\[(?:" + re.escape(full) + "|" + re.escape(stem) + r")(?=[\]|#^])"
        )
        found: list[dict[str, str]] = []
        for other in self.vault.iter_markdown():
            if other == path:
                continue
            try:
                text = self.vault.read_text(other)
            except (OSError, VaultError):
                continue
            if not pattern.search(text):
                continue
            note = parse_note(text)
            snippet = next(
                (
                    f"{key}: {plain_text(value)}"
                    for key, raw in note.frontmatter.items()
                    for value in _as_list(raw)
                    if isinstance(value, str) and pattern.search(value)
                ),
                None,
            )
            if snippet is None:
                line = next(
                    (ln for ln in note.body.splitlines() if pattern.search(ln)), ""
                )
                snippet = plain_text(line)
            found.append({"path": other, "snippet": snippet[:200]})
        return found

    async def async_get_file(self, path: str) -> dict[str, Any]:
        """Return any note in the vault, with its resolved links and backlinks."""
        path = self.vault.normalize(path)
        try:
            note, mtime = await self.hass.async_add_executor_job(
                self._read_existing, path
            )
        except VaultError:
            note, mtime = None, None
        # A generated note still holding its untouched template is an empty note.
        template = None
        key = self.key_for_path(path)
        if note is not None and key is not None and self._is_untouched(key, note.body):
            if note.body.strip():
                record = self._prefill.get(_prefill_key(key), {})
                template = {
                    "name": record.get("template"),
                    "body": note.body.strip("\n"),
                }
                note = Note(note.frontmatter, "")
            else:
                template = await self.async_template(key)
        backlinks = await self.hass.async_add_executor_job(self._backlinks, path)
        names = self._display_names()
        for backlink in backlinks:
            backlink["name"] = names.get(backlink["path"])
        return {
            "path": path,
            "exists": note is not None,
            "note": note.body.strip("\n") if note else "",
            "frontmatter": note.frontmatter if note else {},
            "links": await self.async_resolve_links(note.body) if note else {},
            "backlinks": backlinks,
            "template": template,
            "ha": self.ha_target(path),
            "mtime": mtime,
        }

    async def async_set_file(
        self, path: str, body: str, *, source: str = "ui"
    ) -> dict[str, Any]:
        """Replace the body of any note, keeping its frontmatter. Creates it if missing."""
        path = self.vault.normalize(path)
        if not path.endswith(MARKDOWN_SUFFIX):
            path += MARKDOWN_SUFFIX

        def _write() -> None:
            note = (
                self.vault.read_note(path) if self.vault.exists(path) else Note({}, "")
            )
            text = body.strip("\n")
            self.vault.write_text(
                path, render_note(note.frontmatter, text + "\n" if text else "")
            )

        async with self.lock:
            await self.hass.async_add_executor_job(_write)
            await self.hass.async_add_executor_job(self.index_file, path)
        self.file_changed(path, source)
        return await self.async_get_file(path)

    async def async_tree(self) -> dict[str, Any]:
        """List every note and folder in the vault.

        Generated notes carry the display name of what they are about. Folders are
        listed on their own so an empty one still shows up.
        """
        paths = await self.hass.async_add_executor_job(self._markdown_paths)
        folders = await self.hass.async_add_executor_job(self._folders)
        names = self._display_names()
        return {
            "notes": [{"path": p, "name": names.get(p)} for p in paths],
            "folders": folders,
            "locked": sorted(self.locked_folders),
        }

    def _folders(self) -> list[str]:
        """List every folder in the vault, skipping hidden ones. Runs in the executor."""
        found: list[str] = []
        stack = [""]
        while stack:
            for entry in self.vault.list_dir(stack.pop()):
                if entry.is_dir and not PurePosixPath(entry.path).name.startswith("."):
                    found.append(entry.path)
                    stack.append(entry.path)
        return sorted(found)

    @property
    def locked_folders(self) -> set[str]:
        """Folders the generator owns, which can't be renamed or deleted by hand."""
        folders = self.generated_folders
        folders.add(self.templates_folder)
        if self.base:
            folders.add(self.base)
        return folders

    def _check_unlocked(self, path: str) -> None:
        for locked in self.locked_folders:
            if path == locked or locked.startswith(f"{path}/"):
                raise LockedFolderError(path)

    async def async_mkdir(self, path: str) -> str:
        """Create a folder, and any missing parents."""
        path = self.vault.normalize(path)
        if not path:
            raise InvalidPathError(path)
        await self.hass.async_add_executor_job(
            lambda: self.vault.mkdir(path, parents=True)
        )
        return path

    async def async_move(self, src: str, dst: str) -> str:
        """Rename or move a note or folder, and point every link at the new place."""
        src = self.vault.normalize(src)
        dst = self.vault.normalize(dst)
        if not src or not dst:
            raise InvalidPathError(dst)
        self._check_unlocked(src)
        if dst == src or dst.startswith(f"{src}/"):
            raise InvalidPathError(dst)

        def _move() -> None:
            is_dir = self.vault.stat(src).is_dir
            moved = list(self.vault.iter_markdown(src)) if is_dir else [src]
            self.vault.resolve(dst).parent.mkdir(parents=True, exist_ok=True)
            self.vault.move(src, dst, overwrite=False)
            renames = {}
            for old in moved:
                new = dst + old[len(src) :] if is_dir else dst
                renames[link_target(old)] = link_target(new)
            self.vault.rewrite_links(renames)

        async with self.lock:
            await self.hass.async_add_executor_job(_move)
            self._written.clear()
        self.file_moved(src, dst)
        return dst

    async def async_delete(self, path: str) -> None:
        """Delete a note, or a folder with everything in it."""
        path = self.vault.normalize(path)
        self._check_unlocked(path)
        async with self.lock:
            await self.hass.async_add_executor_job(self.vault.delete, path)
        self.file_removed(path)

    @callback
    def _display_names(self) -> dict[str, str]:
        """Map the path of each generated note to the name of what it is about."""
        return {
            self.index[key]: doc.name
            for key, doc in self.build_docs().items()
            if key in self.index
        }

    async def async_set_note(
        self, key: DocKey, content: str, *, append: bool = False, source: str = "ui"
    ) -> dict[str, Any]:
        """Replace (or append to) the note attached to an object."""
        async with self.lock:
            docs = self.build_docs()
            if key not in docs:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="no_target"
                )
            path = await self.hass.async_add_executor_job(
                self._write_body, docs, key, content, append
            )
        self.fire_updated(path, source, key)
        return await self.async_get_note(key)

    def _write_body(
        self, docs: dict[DocKey, Doc], key: DocKey, content: str, append: bool
    ) -> str:
        path = self.index.get(key)
        note = None
        if path:
            note, _ = self._read_existing(path)
        if note is None:
            # Create the file even if the filters exclude it: a note always wins.
            docs[key].wanted = True
            wanted = {k: d for k, d in docs.items() if d.wanted or k in self.index}
            paths = self._plan_paths(wanted)
            self._resolve_links(wanted, paths)
            path = paths[key]
            note = Note(merge_frontmatter({}, docs[key], None), "")
            self.index[key] = path
        body = content.strip("\n")
        if append and note.body.strip():
            body = note.body.rstrip("\n") + "\n\n" + body
        text = render_note(note.frontmatter, body + "\n" if body else "")
        self.vault.write_text(path, text)
        self._written.pop(key, None)
        return path

    # -- Templates -----------------------------------------------------------------

    @property
    def templates_folder(self) -> str:
        """Folder holding the note templates."""
        return f"{self.base}/Templates" if self.base else "Templates"

    def _seed_templates(self, seeded: set[str]) -> set[str]:
        """Write the default templates not written before. Runs in the executor.

        `seeded` is every default already written once, so a default added in an
        update reaches existing vaults while one the user deleted stays deleted.
        Removing the whole folder starts over and brings them all back.
        """
        if not self.vault.exists(self.templates_folder):
            seeded = set()
        for name, text in DEFAULT_TEMPLATES.items():
            path = f"{self.templates_folder}/{name}{MARKDOWN_SUFFIX}"
            if name not in seeded and not self.vault.exists(path):
                self.vault.write_text(path, text)
            seeded.add(name)
        return seeded

    def _load_templates(self) -> list[Template]:
        """Read every template in the folder. Runs in the executor."""
        if not self.vault.exists(self.templates_folder):
            return []
        templates: list[Template] = []
        for path in self.vault.iter_markdown(self.templates_folder):
            try:
                note = self.vault.read_note(path)
            except (OSError, VaultError):
                continue
            name = PurePosixPath(link_target(path)).name
            if template := parse_template(name, path, note):
                templates.append(template)
        return sorted(templates, key=lambda t: t.name)

    @staticmethod
    def _entities_by_device(docs: dict[DocKey, Doc]) -> dict[str, list[Doc]]:
        grouped: dict[str, list[Doc]] = {}
        for doc in docs.values():
            if doc.kind == KIND_ENTITY and (device_id := doc.managed.get("device")):
                grouped.setdefault(device_id, []).append(doc)
        return grouped

    @callback
    def _template_context(
        self,
        docs: dict[DocKey, Doc],
        key: DocKey,
        entities_by_device: dict[str, list[Doc]] | None = None,
    ) -> tuple[dict[str, list[str]], dict[str, Any]]:
        """Return what a template can match on, and the placeholder values."""
        doc = docs[key]
        m = doc.managed
        facts: dict[str, list[str]] = {}
        values: dict[str, Any] = {
            "name": doc.name,
            "date": dt_util.now().date().isoformat(),
        }
        device_doc = None
        if doc.kind == KIND_ENTITY:
            facts = {
                "domains": [m["domain"]],
                "device_classes": [m["device_class"]] if m.get("device_class") else [],
                "integrations": [m["integration"]] if m.get("integration") else [],
            }
            values["entity_id"] = m["entity_id"]
            values["integration"] = m.get("integration")
            if m.get("device"):
                device_doc = docs.get((KIND_DEVICE, m["device"]))
        elif doc.kind == KIND_DEVICE:
            device_doc = doc
            if entities_by_device is None:
                entities_by_device = self._entities_by_device(docs)
            entities = entities_by_device.get(doc.ha_id, [])
            facts = {
                "integrations": list(m.get("integration") or []),
                "entity_domains": sorted({d.managed["domain"] for d in entities}),
                "entity_device_classes": sorted(
                    {c for d in entities if (c := d.managed.get("device_class"))}
                ),
            }
            values["integration"] = ", ".join(m.get("integration") or [])
        if device_doc:
            values["device"] = device_doc.name
            values["manufacturer"] = device_doc.managed.get("manufacturer")
            values["model"] = device_doc.managed.get("model")
        area_id = m.get("area_id") if doc.kind == KIND_AREA else m.get("area")
        if area_id and (area_doc := docs.get((KIND_AREA, area_id))):
            values["area"] = area_doc.name
        return facts, values

    @callback
    def _plan_templates(
        self, docs: dict[DocKey, Doc], templates: list[Template]
    ) -> dict[DocKey, Plan]:
        """Pick the template each note is pre-filled with.

        Runs before the links are resolved, while the docs still hold raw IDs.
        Entities are grouped by device once, so this stays linear in the registry.
        """
        if not templates:
            return {}
        plans: dict[DocKey, Plan] = {}
        by_device = self._entities_by_device(docs)
        for key, doc in docs.items():
            if not doc.wanted and key not in self.index:
                continue
            facts, values = self._template_context(docs, key, by_device)
            if template := best_template(templates, key[0], facts):
                plans[key] = (template, values)
        return plans

    async def async_templates(self, kind: str | None = None) -> list[dict[str, Any]]:
        """List the templates, optionally only those for one kind of object."""
        templates = await self.hass.async_add_executor_job(self._load_templates)
        return [
            {
                "name": t.name,
                "path": t.path,
                "applies_to": t.applies_to,
                "criteria": {k: sorted(v) for k, v in t.criteria.items()},
            }
            for t in templates
            if kind is None or t.applies_to == kind
        ]

    async def async_template(
        self, key: DocKey, name: str | None = None
    ) -> dict[str, Any] | None:
        """Render the named template, or the best match, for an object."""
        templates = await self.hass.async_add_executor_job(self._load_templates)
        docs = self.build_docs()
        if key not in docs:
            return None
        facts, values = self._template_context(docs, key)
        if name is None:
            template = best_template(templates, key[0], facts)
        else:
            template = next((t for t in templates if t.name == name), None)
        if template is None:
            return None
        return {"name": template.name, "body": render(template.body, values)}

    # -- Anything else in the vault ------------------------------------------------

    @callback
    def fire_updated(self, path: str, source: str, key: DocKey | None = None) -> None:
        """Tell listeners that a note changed."""
        if key is None:
            key = self.key_for_path(path)
        data: dict[str, Any] = {"path": path, "source": source}
        if key:
            kind, ha_id = key
            if kind == KIND_ENTITY:
                entry = er.async_get(self.hass).async_get(ha_id)
                data["entity_id"] = entry.entity_id if entry else ha_id
            elif kind == KIND_DEVICE:
                data["device_id"] = ha_id
            else:
                data["area_id"] = ha_id
        self.hass.bus.async_fire(EVENT_NOTE_UPDATED, data)

    @callback
    def file_changed(self, path: str, source: str) -> None:
        """Record a change made to a file outside the note API (WebDAV, services)."""
        if not path.endswith(MARKDOWN_SUFFIX):
            return
        for key, indexed in list(self.index.items()):
            if indexed == path:
                self._written.pop(key, None)
        self.fire_updated(path, source)

    @callback
    def file_removed(self, path: str) -> None:
        """Forget files deleted or moved away from outside."""
        prefix = path.rstrip("/") + "/"
        for key, indexed in list(self.index.items()):
            if indexed == path or indexed.startswith(prefix):
                self.index.pop(key)
                self._written.pop(key, None)
        # A generated note deleted in Obsidian comes back empty on the next sync.
        self._schedule()

    @callback
    def file_moved(self, src: str, dst: str) -> None:
        """Follow a note (or a folder of notes) moved from outside."""
        prefix = src.rstrip("/") + "/"
        for key, indexed in list(self.index.items()):
            if indexed == src:
                self.index[key] = dst
            elif indexed.startswith(prefix):
                self.index[key] = dst.rstrip("/") + "/" + indexed[len(prefix) :]
            else:
                continue
            self._written.pop(key, None)
        self.fire_updated(dst, "webdav")

    def index_file(self, path: str) -> None:
        """Pick up a generated note written from outside. Runs in the executor."""
        if not path.endswith(MARKDOWN_SUFFIX):
            return
        try:
            fm = self.vault.read_frontmatter(path)
        except (OSError, VaultError):
            return
        kind, ha_id = fm.get("ha_type"), fm.get("ha_id")
        if kind in (KIND_ENTITY, KIND_DEVICE, KIND_AREA) and isinstance(ha_id, str):
            self.index.setdefault((kind, ha_id), path)


@callback
def loaded_manager(hass: HomeAssistant) -> NotesVault | None:
    """Return the manager of the loaded config entry, if there is one."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    return None
