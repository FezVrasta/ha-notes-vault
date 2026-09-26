"""The file layer: paths, frontmatter, search and link rewriting."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.notes_vault.vault import (
    ConflictError,
    InvalidPathError,
    Vault,
    parse_note,
    plain_text,
    render_note,
    safe_name,
    wikilink,
)


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    """Return an empty vault."""
    v = Vault(tmp_path / "vault")
    v.ensure()
    return v


@pytest.mark.parametrize("path", ["../x.md", "a/../../x.md", "a/\x00.md"])
def test_paths_cannot_escape(vault: Vault, path: str) -> None:
    """Nothing reaches outside the root, however the path is spelled."""
    with pytest.raises(InvalidPathError):
        vault.resolve(path)


def test_symlink_out_of_vault_is_refused(vault: Vault, tmp_path: Path) -> None:
    """A symlink pointing outside is treated as outside."""
    (tmp_path / "secret").mkdir()
    (vault.root / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(InvalidPathError):
        vault.resolve("link/file.md")


def test_frontmatter_round_trip() -> None:
    """Frontmatter and body split apart and join back without losing either."""
    text = "---\nname: Kitchen\ntags:\n- a\n---\nHello [[light.kitchen]]\n"
    note = parse_note(text)
    assert note.frontmatter == {"name": "Kitchen", "tags": ["a"]}
    assert note.body == "Hello [[light.kitchen]]\n"
    assert parse_note(render_note(note.frontmatter, note.body)) == note


def test_invalid_frontmatter_is_flagged() -> None:
    """Broken YAML is reported rather than silently dropped."""
    note = parse_note("---\nname: [unclosed\n---\nbody\n")
    assert not note.valid
    assert note.body == "body\n"


def test_no_frontmatter() -> None:
    """A plain Markdown file is all body."""
    note = parse_note("# Title\n")
    assert note.frontmatter == {}
    assert note.body == "# Title\n"


def test_safe_name() -> None:
    """Characters Obsidian rejects in file names are replaced."""
    assert safe_name("Living room: lamp #2 [left]") == "Living room lamp 2 left"
    assert safe_name("...") == "Unnamed"


def test_wikilink() -> None:
    """Links use the full path and keep a readable label."""
    assert wikilink("HA/Devices/Lamp.md") == "[[HA/Devices/Lamp|Lamp]]"
    assert wikilink("Lamp.md") == "[[Lamp]]"


def test_write_needs_parent_when_asked(vault: Vault) -> None:
    """WebDAV writes refuse missing parents; everything else creates them."""
    with pytest.raises(ConflictError):
        vault.write_text("missing/x.md", "x", make_parents=False)
    assert vault.write_text("missing/x.md", "x") is True
    assert vault.write_text("missing/x.md", "y") is False
    assert vault.read_text("missing/x.md") == "y"


def test_search_ranks_path_matches_first(vault: Vault) -> None:
    """A hit in the file name beats one in the text."""
    vault.write_text("Boiler.md", "Serviced in March")
    vault.write_text("Log.md", "The boiler was serviced")
    vault.write_text(".obsidian/boiler.md", "hidden")
    results = vault.search("boiler serviced")
    assert [r["path"] for r in results] == ["Boiler.md", "Log.md"]
    assert results[1]["snippet"] == "The boiler was serviced"


def test_rewrite_links(vault: Vault) -> None:
    """Both link spellings follow a rename; similar names are left alone."""
    vault.write_text(
        "Note.md",
        "[[light.a]] [[light.a|A]] [[HA/Entities/light.a#x]] [[light.ab]]",
    )
    changed = vault.rewrite_links({"HA/Entities/light.a": "HA/Entities/light.b"})
    assert changed == ["Note.md"]
    assert vault.read_text("Note.md") == (
        "[[light.b]] [[light.b|A]] [[HA/Entities/light.b#x]] [[light.ab]]"
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- See [[Home Assistant/Areas/Bedroom|Bedroom]]", "See Bedroom"),
        ("Swap [[light.kitchen]] soon", "Swap light.kitchen soon"),
        ("## **Bold** and _it_ with [a link](https://x)", "Bold and it with a link"),
        ("- [ ] check [[Notes/Boiler#Service]]", "check Boiler"),
    ],
)
def test_plain_text(line: str, expected: str) -> None:
    """Snippets read like the rendered note, not its source."""
    assert plain_text(line) == expected


def test_listing_skips_files_that_vanish(tmp_path: Path) -> None:
    """A temporary file renamed away mid-listing is skipped, not an error."""
    vault = Vault(tmp_path)
    vault.ensure()
    vault.write_text("note.md", "x")
    (tmp_path / ".~gone.tmp").write_text("")
    real_scandir = os.scandir

    class Vanished:
        def __init__(self, entry: os.DirEntry) -> None:
            self._entry = entry
            self.name = entry.name
            self.path = entry.path

        def stat(self):
            if self.name == ".~gone.tmp":
                raise FileNotFoundError(self.path)
            return self._entry.stat()

        def is_dir(self):
            return self._entry.is_dir()

    @contextmanager
    def scandir(path):
        with real_scandir(path) as it:
            yield [Vanished(e) for e in it]

    with patch("custom_components.notes_vault.vault.os.scandir", scandir):
        assert [e.path for e in vault.list_dir()] == ["note.md"]
