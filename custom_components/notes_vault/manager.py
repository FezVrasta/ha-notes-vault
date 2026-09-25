"""Keeps the generated notes in step with Home Assistant's registries.

Every entity, device and area gets a Markdown file whose frontmatter Home Assistant
owns and whose body belongs to the user. The body is the note shown in the Home
Assistant UI; the frontmatter is what makes ``[[light.kitchen]]`` a useful link in
Obsidian.
"""

from __future__ import annotations

import asyncio
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
    EVENT_NOTE_UPDATED,
    KIND_AREA,
    KIND_DEVICE,
    KIND_ENTITY,
    SYNC_DEBOUNCE,
)
from .vault import (
    MARKDOWN_SUFFIX,
    Note,
    NotFoundError,
    Vault,
    VaultError,
    link_target,
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
        "title",
        # Written by versions before 0.1.0, removed on the next sync.
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
        "ha_url",
        "ha_removed",
    }
)
#: Keys the generator adds to without taking over: users keep their own values.
ADDITIVE_KEYS = ("aliases", "tags")

type DocKey = tuple[str, str]


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


def _is_blank(note: Note) -> bool:
    return not note.body.strip()


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
    tags = list(_as_list(current.get("tags")))
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
        self._written: dict[DocKey, tuple[float, dict[str, Any]]] = {}
        self.lock = asyncio.Lock()
        self._unsubs: list[Callable[[], None]] = []
        self._debouncer: Debouncer | None = None
        self.last_sync: dict[str, int] = {}
        self._base_url: str | None = None

    # -- Lifecycle -----------------------------------------------------------------

    async def async_start(self) -> None:
        """Scan the vault, generate the notes and start following registry changes."""
        await self.hass.async_add_executor_job(self.vault.ensure)
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

    def _folder(self, kind: str) -> str:
        sub = {KIND_ENTITY: "Entities", KIND_DEVICE: "Devices", KIND_AREA: "Areas"}[
            kind
        ]
        return f"{self.base}/{sub}" if self.base else sub

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
                tags=["ha/area"],
            )
            doc.managed = {
                "ha_type": KIND_AREA,
                "ha_id": area.id,
                "area_id": area.id,
                "title": area.name,
                "floor": floor.name if floor else None,
                "labels": label_names(area.labels),
                "ha_url": self._url(f"/config/areas/area/{area.id}"),
            }
            docs[doc.key] = doc

        for device in dev_reg.devices.values():
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
                tags=["ha/device"],
            )
            doc.managed = {
                "ha_type": KIND_DEVICE,
                "ha_id": device.id,
                "device_id": device.id,
                "title": name,
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

        return docs

    def _entity_doc(
        self, *, ha_id: str, entity_id: str, name: str, wanted: bool
    ) -> Doc:
        domain = entity_id.split(".", 1)[0]
        doc = Doc(
            kind=KIND_ENTITY,
            ha_id=ha_id,
            name=name,
            folder=self._folder(KIND_ENTITY),
            stem=entity_id,
            wanted=wanted,
            aliases=[name] if name and name != entity_id else [],
            tags=["ha/entity", f"ha/{domain}"],
        )
        doc.managed = {
            "ha_type": KIND_ENTITY,
            "ha_id": ha_id,
            "entity_id": entity_id,
            "title": name,
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
        for key, doc in docs.items():
            current = self.index.get(key)
            if current is None:
                pending.append(doc)
                continue
            current_stem = PurePosixPath(link_target(current)).name
            in_folder = PurePosixPath(current).parent.as_posix() == doc.folder
            # Only rename files still where the generator put them: a note the user
            # moved or renamed in Obsidian stays where they put it.
            if in_folder and not _stem_matches(current_stem, doc.stem):
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
        for doc in docs.values():
            if doc.kind == KIND_DEVICE:
                doc.managed["entities"] = sorted(entities_by_device.get(doc.ha_id, []))
            elif doc.kind == KIND_AREA:
                doc.managed["devices"] = sorted(devices_by_area.get(doc.ha_id, []))

    def _read_existing(
        self, key: DocKey, path: str
    ) -> tuple[Note | None, float | None]:
        try:
            info = self.vault.stat(path)
        except NotFoundError:
            return None, None
        return self.vault.read_note(path), info.mtime

    def _write_doc(self, key: DocKey, doc: Doc, path: str) -> str:
        """Write one note's frontmatter if it changed. Return the stats bucket."""
        cached = self._written.get(key)
        try:
            mtime: float | None = self.vault.stat(path).mtime
        except NotFoundError:
            mtime = None
        note: Note | None = None
        if cached and mtime is not None and cached[0] == mtime:
            current_fm = cached[1]
        else:
            note = self.vault.read_note(path) if mtime is not None else None
            current_fm = note.frontmatter if note else {}
            if note and not note.valid:
                _LOGGER.warning("Skipping %s: its frontmatter is not valid YAML", path)
                return "unchanged"
        merged = merge_frontmatter(current_fm, doc, current_fm.get("title"))
        if mtime is not None and merged == current_fm:
            return "unchanged"
        if note is None and mtime is not None:
            note = self.vault.read_note(path)
        body = note.body if note else ""
        created = self.vault.write_text(path, render_note(merged, body))
        self._written[key] = (self.vault.stat(path).mtime, merged)
        return "created" if created else "updated"

    def _apply(self, docs: dict[DocKey, Doc]) -> dict[str, int]:
        """Bring the files on disk in line with the docs. Runs in the executor."""
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
            note, _ = self._read_existing(key, path)
            if note is None:
                continue
            if not _is_blank(note) or _user_keys(note.frontmatter) or not note.valid:
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
                stats[self._write_doc(key, doc, path)] += 1
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
            if _is_blank(note) and not _user_keys(note.frontmatter) and note.valid:
                self.vault.delete(path)
                self.index.pop(key)
                self._written.pop(key, None)
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
        async with self.lock:
            docs = self.build_docs()
            stats = await self.hass.async_add_executor_job(self._apply, docs)
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
                self._read_existing, key, path
            )
        if note is None:
            docs = self.build_docs()
            doc = docs.get(key)
            path = path or (
                f"{doc.folder}/{doc.stem}{MARKDOWN_SUFFIX}" if doc else None
            )
        return {
            "path": path,
            "link": wikilink(path, PurePosixPath(link_target(path)).name)
            if path
            else None,
            "exists": note is not None,
            "note": note.body.strip("\n") if note else "",
            "frontmatter": note.frontmatter if note else {},
            "mtime": mtime,
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
            note, _ = self._read_existing(key, path)
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

    # -- Anything else in the vault ------------------------------------------------

    @callback
    def fire_updated(self, path: str, source: str, key: DocKey | None = None) -> None:
        """Tell listeners that a note changed."""
        if key is None:
            key = next((k for k, p in self.index.items() if p == path), None)
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
