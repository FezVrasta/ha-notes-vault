"""The vault on disk: paths, Markdown frontmatter, search and link rewriting.

Nothing in here imports Home Assistant. Every method is blocking file I/O, so the
integration calls them through the executor.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

#: Characters Obsidian refuses in a file name, plus the path separators.
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
_FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(.*?\r?\n)?(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.DOTALL
)

MARKDOWN_SUFFIX = ".md"

#: Where deleted notes and replaced versions go. The same folder Obsidian moves
#: deleted notes to, and hidden, so nothing else in the vault sees it.
TRASH_FOLDER = ".trash"


class VaultError(Exception):
    """Base error for vault operations."""


class InvalidPathError(VaultError):
    """The path points outside the vault or is otherwise unusable."""


class NotFoundError(VaultError):
    """The file or folder does not exist."""


class ConflictError(VaultError):
    """The operation clashes with what is on disk (missing parent, existing target)."""


class StaleError(VaultError):
    """The file changed since the version a write was based on."""


@dataclass(slots=True)
class Note:
    """A Markdown file split into its frontmatter and body."""

    frontmatter: dict[str, Any]
    body: str
    #: False when the file has a frontmatter block that is not valid YAML. Such a file
    #: is never rewritten by the generator, so a typo in Obsidian cannot cost the note.
    valid: bool = True


@dataclass(slots=True)
class FileInfo:
    """What a directory listing needs to know about one entry."""

    path: str
    is_dir: bool
    size: int
    mtime: float


def safe_name(name: str) -> str:
    """Turn a display name into something usable as an Obsidian file name."""
    cleaned = _UNSAFE_NAME.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or "Unnamed"


def parse_note(text: str) -> Note:
    """Split Markdown into frontmatter and body."""
    match = _FRONTMATTER.match(text)
    if not match:
        return Note({}, text)
    raw = match.group(1) or ""
    body = text[match.end() :]
    try:
        data = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError:
        return Note({}, body, valid=False)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return Note({}, body, valid=False)
    return Note(data, body)


def render_note(frontmatter: dict[str, Any], body: str) -> str:
    """Join frontmatter and body back into Markdown."""
    if not frontmatter:
        return body
    dumped = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    )
    return f"---\n{dumped}---\n{body}"


_LINK_WITH_LABEL = re.compile(r"!?\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def plain_text(line: str) -> str:
    """Reduce one line of Markdown to what a reader sees, for snippets.

    Wikilinks become their label (or the note's name), Markdown links their text, and
    list markers, heading marks, quotes and emphasis go.
    """
    text = _LINK_WITH_LABEL.sub(
        lambda m: m.group(2) or PurePosixPath(m.group(1).split("#")[0]).name, line
    )
    text = _MD_LINK.sub(r"\1", text)
    text = re.sub(r"^\s*(?:[-*+]|\d+\.|>|#{1,6})\s+", "", text)
    text = re.sub(r"^\s*\[[ xX]\]\s+", "", text)
    text = re.sub(r"(\*\*|__|\*|_|`|~~)(.+?)\1", r"\2", text)
    return text.strip()


def link_target(path: str) -> str:
    """Return the vault path without the Markdown suffix, as a wikilink uses it."""
    return path.removesuffix(MARKDOWN_SUFFIX)


def wikilink(path: str, label: str | None = None) -> str:
    """Build an unambiguous wikilink to a vault path."""
    target = link_target(path)
    stem = PurePosixPath(target).name
    if label is None:
        label = stem
    if label == target:
        return f"[[{target}]]"
    return f"[[{target}|{label}]]"


class Vault:
    """A folder of Markdown files, addressed by POSIX paths relative to its root."""

    def __init__(self, root: Path) -> None:
        """Wrap a folder. It is created on first use."""
        self.root = root

    def ensure(self) -> None:
        """Create the root folder if it does not exist."""
        self.root.mkdir(parents=True, exist_ok=True)

    # -- Paths ---------------------------------------------------------------------

    @staticmethod
    def normalize(path: str) -> str:
        """Normalise a relative path, refusing anything that climbs out of the root."""
        parts: list[str] = []
        for part in path.replace("\\", "/").split("/"):
            if part in ("", "."):
                continue
            if part == ".." or "\x00" in part:
                raise InvalidPathError(path)
            parts.append(part)
        return "/".join(parts)

    def resolve(self, path: str) -> Path:
        """Return the absolute path for a vault path, guaranteed to be inside the root."""
        rel = self.normalize(path)
        full = self.root / rel if rel else self.root
        root = self.root.resolve()
        resolved = full.resolve()
        if resolved != root and root not in resolved.parents:
            raise InvalidPathError(path)
        return full

    # -- Plain file operations -----------------------------------------------------

    def exists(self, path: str) -> bool:
        """Return whether the path exists."""
        return self.resolve(path).exists()

    def stat(self, path: str) -> FileInfo:
        """Describe one file or folder."""
        full = self.resolve(path)
        try:
            st = full.stat()
        except FileNotFoundError as err:
            raise NotFoundError(path) from err
        return FileInfo(
            self.normalize(path),
            full.is_dir(),
            0 if full.is_dir() else st.st_size,
            st.st_mtime,
        )

    def list_dir(self, path: str = "") -> list[FileInfo]:
        """List the direct children of a folder."""
        full = self.resolve(path)
        if not full.is_dir():
            raise NotFoundError(path)
        base = self.normalize(path)
        entries: list[FileInfo] = []
        with os.scandir(full) as it:
            for entry in it:
                st = entry.stat()
                is_dir = entry.is_dir()
                entries.append(
                    FileInfo(
                        f"{base}/{entry.name}" if base else entry.name,
                        is_dir,
                        0 if is_dir else st.st_size,
                        st.st_mtime,
                    )
                )
        entries.sort(key=lambda e: (not e.is_dir, e.path.lower()))
        return entries

    def walk(
        self, path: str = "", *, include_hidden: bool = False
    ) -> Iterator[FileInfo]:
        """Yield every file below a folder."""
        stack = [path]
        while stack:
            current = stack.pop()
            for entry in self.list_dir(current):
                name = PurePosixPath(entry.path).name
                if not include_hidden and name.startswith("."):
                    continue
                if entry.is_dir:
                    stack.append(entry.path)
                else:
                    yield entry

    def iter_markdown(self, path: str = "") -> Iterator[str]:
        """Yield the path of every Markdown file below a folder, skipping hidden ones."""
        for entry in self.walk(path):
            if entry.path.endswith(MARKDOWN_SUFFIX):
                yield entry.path

    def read_bytes(self, path: str) -> bytes:
        """Read a file."""
        full = self.resolve(path)
        if not full.is_file():
            raise NotFoundError(path)
        return full.read_bytes()

    def read_text(self, path: str) -> str:
        """Read a text file."""
        return self.read_bytes(path).decode("utf-8", errors="replace")

    def write_bytes(
        self, path: str, data: bytes | bytearray, *, make_parents: bool = True
    ) -> bool:
        """Write a file atomically. Return True if the file did not exist before."""
        full = self.resolve(path)
        if full == self.root.resolve() or full.is_dir():
            raise ConflictError(path)
        if make_parents:
            full.parent.mkdir(parents=True, exist_ok=True)
        elif not full.parent.is_dir():
            raise ConflictError(path)
        created = not full.exists()
        fd, tmp = tempfile.mkstemp(dir=full.parent, prefix=".~", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            Path(tmp).replace(full)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return created

    def write_text(self, path: str, text: str, *, make_parents: bool = True) -> bool:
        """Write a text file atomically. Return True if it was created."""
        return self.write_bytes(path, text.encode("utf-8"), make_parents=make_parents)

    def mkdir(self, path: str, *, parents: bool = False) -> None:
        """Create a folder."""
        full = self.resolve(path)
        if full.exists():
            raise ConflictError(path)
        if not parents and not full.parent.is_dir():
            raise ConflictError(path)
        full.mkdir(parents=parents)

    def check_unchanged(self, path: str, mtime: float | None) -> None:
        """Refuse a write based on a version of the file that is no longer current.

        `mtime` is the modification time the writer read. None means the writer
        believed the file didn't exist yet.
        """
        full = self.resolve(path)
        current = full.stat().st_mtime if full.is_file() else None
        if current != mtime:
            raise StaleError(path)

    def trash(self, path: str) -> str:
        """Move a file or folder to the trash instead of deleting it.

        Returns where it went. Anything already in the trash is deleted for good.
        """
        rel = self.normalize(path)
        if rel == TRASH_FOLDER or rel.startswith(f"{TRASH_FOLDER}/"):
            self.delete(rel)
            return rel
        full = self.resolve(rel)
        if full.resolve() == self.root.resolve():
            raise InvalidPathError(path)
        if not full.exists():
            raise NotFoundError(path)
        dest = self._trash_path(PurePosixPath(rel).name, is_dir=full.is_dir())
        target = self.resolve(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        full.rename(target)
        # The age the trash is emptied by is the time it was thrown away, not the
        # time the file was last edited.
        os.utime(target)
        return dest

    def keep_version(self, path: str) -> str | None:
        """Copy a file to the trash before it's overwritten. Returns the copy's path."""
        full = self.resolve(path)
        if not full.is_file():
            return None
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        name = PurePosixPath(self.normalize(path))
        dest = self._trash_path(f"{name.stem} ({stamp}){name.suffix}", is_dir=False)
        self.write_bytes(dest, full.read_bytes())
        return dest

    def _trash_path(self, name: str, *, is_dir: bool) -> str:
        """Pick a free name in the trash, numbering it when the name is taken."""
        pure = PurePosixPath(name)
        stem, suffix = (name, "") if is_dir else (pure.stem, pure.suffix)
        candidate, n = name, 1
        while self.resolve(f"{TRASH_FOLDER}/{candidate}").exists():
            n += 1
            candidate = f"{stem} {n}{suffix}"
        return f"{TRASH_FOLDER}/{candidate}"

    def empty_trash(self, max_age: float) -> int:
        """Delete what has been in the trash longer than `max_age` seconds."""
        trash = self.resolve(TRASH_FOLDER)
        if not trash.is_dir():
            return 0
        cutoff = time.time() - max_age
        removed = 0
        for entry in trash.iterdir():
            if entry.lstat().st_mtime >= cutoff:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed += 1
        return removed

    def delete(self, path: str) -> None:
        """Delete a file or a folder with everything in it."""
        full = self.resolve(path)
        if full.resolve() == self.root.resolve():
            raise InvalidPathError(path)
        if full.is_dir():
            shutil.rmtree(full)
        elif full.exists():
            full.unlink()
        else:
            raise NotFoundError(path)

    def move(
        self, src: str, dst: str, *, overwrite: bool = True, copy: bool = False
    ) -> bool:
        """Move or copy a file or folder. Return True if the destination was created."""
        source = self.resolve(src)
        target = self.resolve(dst)
        if not source.exists():
            raise NotFoundError(src)
        if (
            source.resolve() == self.root.resolve()
            or target.resolve() == self.root.resolve()
        ):
            raise InvalidPathError(dst)
        if not target.parent.is_dir():
            raise ConflictError(dst)
        created = not target.exists()
        if not created:
            if not overwrite:
                raise ConflictError(dst)
            if source.resolve() == target.resolve():
                return False
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if copy:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        else:
            source.replace(target)
        return created

    # -- Notes ---------------------------------------------------------------------

    def read_note(self, path: str) -> Note:
        """Read and parse a Markdown file."""
        return parse_note(self.read_text(path))

    def read_frontmatter(self, path: str) -> dict[str, Any]:
        """Parse only the frontmatter, reading as little of the file as possible."""
        full = self.resolve(path)
        with full.open("rb") as handle:
            head = handle.read(64 * 1024)
        text = head.decode("utf-8", errors="replace")
        if not text.startswith("---"):
            return {}
        if len(head) == 64 * 1024:
            text = self.read_text(path)
        return parse_note(text).frontmatter

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        folder: str = "",
        skip: frozenset[str] = frozenset(),
    ) -> list[dict[str, Any]]:
        """Find notes whose path or content contains every word of the query."""
        words = [w.lower() for w in query.split() if w]
        if not words:
            return []
        results: list[tuple[int, dict[str, Any]]] = []
        for path in self.iter_markdown(folder):
            if path in skip:
                continue
            try:
                text = self.read_text(path)
            except VaultError:
                continue
            haystack = f"{path}\n{text}".lower()
            if not all(w in haystack for w in words):
                continue
            path_hits = sum(w in path.lower() for w in words)
            snippet = ""
            for line in text.splitlines():
                if any(w in line.lower() for w in words):
                    snippet = line.strip()[:200]
                    break
            results.append((path_hits, {"path": path, "snippet": snippet}))
        results.sort(key=lambda r: (-r[0], r[1]["path"]))
        return [r for _, r in results[:limit]]

    def rewrite_links(self, renames: dict[str, str]) -> list[str]:
        """Point wikilinks at renamed notes. Keys and values are paths without suffix.

        Both the full-path form and the bare file name form are rewritten, so a link
        written as ``[[light.kitchen]]`` and one written as
        ``[[Home Assistant/Entities/light.kitchen]]`` both follow the rename.
        """
        if not renames:
            return []
        targets: dict[str, str] = {}
        for old, new in renames.items():
            targets[old] = new
            targets[PurePosixPath(old).name] = PurePosixPath(new).name
        pattern = re.compile(
            r"\[\[("
            + "|".join(re.escape(t) for t in sorted(targets, key=len, reverse=True))
            + r")(?=[\]|#^])"
        )
        changed: list[str] = []
        for path in self.iter_markdown():
            text = self.read_text(path)
            updated = pattern.sub(lambda m: f"[[{targets[m.group(1)]}", text)
            if updated != text:
                self.write_text(path, updated)
                changed.append(path)
        return changed
