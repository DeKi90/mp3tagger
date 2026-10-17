"""UI smoke tests using NiceGUI's simulated user (no browser)."""

import asyncio
from pathlib import Path

import pytest
from mutagen.id3 import ID3
from nicegui import ui
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

from mp3tagger.config import Config
from mp3tagger.ui.app import build_app
from mp3tagger.ui.file_grid import FileGrid

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture
def music_root(make_mp3, tmp_path):
    root = tmp_path / "music"
    make_mp3(root / "rock" / "b.mp3", title="Beta", artist="Band", year="2001", track="2")
    make_mp3(root / "rock" / "a.mp3", title="Alpha", artist="Band", year="2000", track="1")
    make_mp3(root / "rock" / "deep" / "c.mp3", title="Gamma")
    (root / "empty").mkdir()
    return root


def click_in_dialog(user: User, kind: type[ui.element], text: str) -> None:
    """The simulated user cannot see into the dialog's scroll area; look elements up directly."""
    matches = {
        e
        for e in user.client.elements.values()
        if isinstance(e, kind) and text in (e.props.get("label"), getattr(e, "text", None))
    }
    assert matches, f"no {kind.__name__} {text!r} found"
    UserInteraction(user, matches, text).click()


def click_folder_entry(user: User, name: str) -> None:
    (label,) = (
        e for e in user.client.elements.values() if isinstance(e, ui.item_label) and e.text == name
    )
    item = label
    while not isinstance(item, ui.item):  # the click handler sits on the enclosing ui.item
        item = item.parent_slot.parent
    UserInteraction(user, {item}, name).click()


async def open_folder(user: User, music_root, subfolder: str, *, recursive: bool = False) -> None:
    build_app(Config(roots=(music_root,)))
    await user.open("/")
    if recursive:
        user.find("Include subfolders").click()
    user.find("Open folder…").click()
    await asyncio.sleep(0.1)
    click_folder_entry(user, subfolder)
    click_in_dialog(user, ui.button, "Open")
    await user.should_see(kind=ui.label, content=" files · ", retries=100)  # scan finished


def grid_rows(user: User) -> list[dict]:
    (grid,) = (e for e in user.client.elements.values() if isinstance(e, ui.aggrid))
    return grid.options["rowData"]


async def test_open_folder_populates_grid(user: User, music_root):
    await open_folder(user, music_root, "rock")
    rows = grid_rows(user)
    assert [r["title"] for r in rows] == ["Alpha", "Beta"]
    assert rows[0]["filename"] == "a.mp3"
    assert 1.0 < rows[0]["duration"] < 1.1  # raw seconds, formatted client-side
    assert rows[0]["bitrate"] == 128_000
    await user.should_see("2 files · 0 selected")


async def test_include_subfolders(user: User, music_root):
    await open_folder(user, music_root, "rock", recursive=True)
    assert sorted(r["filename"] for r in grid_rows(user)) == ["a.mp3", "b.mp3", "c.mp3"]


async def test_empty_folder_warns(user: User, music_root):
    await open_folder(user, music_root, "empty")
    await user.should_see("No MP3 files found")
    assert grid_rows(user) == []


# --- editing ---------------------------------------------------------------------------------


async def select(user: User, monkeypatch, *paths: Path) -> None:
    """Simulate selecting rows. The simulated user has no browser, so fake the grid query."""

    async def selected_paths(_self) -> list[Path]:
        return list(paths)

    monkeypatch.setattr(FileGrid, "selected_paths", selected_paths)
    (grid,) = (e for e in user.client.elements.values() if isinstance(e, ui.aggrid))
    UserInteraction(user, {grid}, None).trigger("selectionChanged")
    await asyncio.sleep(0.1)


def field(user: User, label: str) -> ui.input:
    (element,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.input) and e.props.get("label") == label
    )
    return element


def type_into(user: User, label: str, text: str) -> None:
    field(user, label).set_value(text)


def button(user: User, text: str) -> ui.button:
    (element,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.button) and e.props.get("label", "").startswith(text)
    )
    return element


def click(user: User, text: str) -> None:
    UserInteraction(user, {button(user, text)}, text).click()


def row_for(user: User, path: Path) -> dict:
    return next(r for r in grid_rows(user) if r["id"] == str(path))


@pytest.fixture
async def editing(user: User, music_root, monkeypatch):
    """A folder is open and a.mp3 is selected."""
    await open_folder(user, music_root, "rock")
    a = music_root / "rock" / "a.mp3"
    await select(user, monkeypatch, a)
    return a


async def test_selecting_a_file_fills_the_panel(user: User, editing):
    assert field(user, "Title").value == "Alpha"
    assert field(user, "Artist").value == "Band"
    assert field(user, "Year").value == "2000"
    await user.should_see("a.mp3")
    await user.should_see("ID3v2.3")


async def test_editing_marks_row_dirty_and_enables_save(user: User, editing):
    assert not button(user, "Save").enabled
    type_into(user, "Title", "Edited")
    assert row_for(user, editing)["title"] == "Edited"
    assert row_for(user, editing)["dirty"] is True
    assert button(user, "Save").enabled
    assert button(user, "Save").props["label"] == "Save (1)"
    await user.should_see("1 modified")
    assert ID3(editing)["TIT2"].text == ["Alpha"]  # nothing written until saved


async def test_save_writes_file_and_clears_dirty(user: User, editing):
    type_into(user, "Title", "Edited")
    type_into(user, "Genre", "Jazz")
    click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    tags = ID3(editing)
    assert tags["TIT2"].text == ["Edited"] and tags["TCON"].text == ["Jazz"]
    assert tags["TPE1"].text == ["Band"]  # untouched field preserved
    assert row_for(user, editing)["dirty"] is False
    assert not button(user, "Save").enabled
    await user.should_not_see("modified")


async def test_save_as_v24_and_v1(user: User, editing):
    (select_,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.select) and e.props.get("label") == "Save as"
    )
    (v1,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.checkbox) and e.text == "Also write ID3v1"
    )
    select_.set_value(4)
    v1.set_value(True)
    type_into(user, "Title", "Edited")
    click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert ID3(editing, load_v1=False).version[:2] == (2, 4)
    assert editing.read_bytes()[-128:-125] == b"TAG"


async def test_undo_reverts_edit(user: User, editing):
    assert not button(user, "Undo").enabled
    type_into(user, "Title", "Edited")
    assert button(user, "Undo").enabled
    click(user, "Undo")
    assert row_for(user, editing)["title"] == "Alpha"
    assert row_for(user, editing)["dirty"] is False
    assert field(user, "Title").value == "Alpha"


async def test_revert_all_asks_for_confirmation(user: User, editing):
    type_into(user, "Title", "Edited")
    click(user, "Revert all")
    await user.should_see("Discard unsaved changes in 1 file(s)?")
    click(user, "Discard")
    await asyncio.sleep(0.1)
    assert row_for(user, editing)["dirty"] is False
    assert field(user, "Title").value == "Alpha"


async def test_opening_folder_with_unsaved_changes_asks_first(user: User, editing):
    type_into(user, "Title", "Edited")
    click(user, "Open folder")
    await user.should_see("unsaved changes")
    click(user, "Cancel")
    await asyncio.sleep(0.1)
    assert row_for(user, editing)["dirty"] is True  # nothing was discarded


async def test_invalid_year_fails_save_but_keeps_edit(user: User, editing):
    type_into(user, "Year", "abcd")
    click(user, "Save")
    await user.should_see("Invalid year")
    assert ID3(editing)["TDRC"].text[0].year == 2000
    assert row_for(user, editing)["dirty"] is True


async def test_failure_of_one_file_does_not_block_the_other(user: User, music_root, monkeypatch):
    await open_folder(user, music_root, "rock")
    a, b = music_root / "rock" / "a.mp3", music_root / "rock" / "b.mp3"
    await select(user, monkeypatch, a)
    type_into(user, "Year", "abcd")
    await select(user, monkeypatch, b)
    type_into(user, "Title", "Beta2")
    click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert ID3(b)["TIT2"].text == ["Beta2"]
    assert row_for(user, a)["dirty"] is True and row_for(user, b)["dirty"] is False


async def test_multiple_selected_files_show_hint_instead_of_form(
    user: User, music_root, monkeypatch
):
    await open_folder(user, music_root, "rock")
    rock = music_root / "rock"
    await select(user, monkeypatch, rock / "a.mp3", rock / "b.mp3")
    await user.should_see("2 files selected")
    await user.should_see("2 selected")


async def test_edits_do_not_rebuild_the_grid(user: User, editing, monkeypatch):
    """A rebuild (grid.update) drops the selection, sorting and column state in the browser."""
    rebuilds = []
    monkeypatch.setattr(ui.aggrid, "update", lambda self: rebuilds.append(1))
    type_into(user, "Title", "Edited")
    click(user, "Undo")
    type_into(user, "Title", "Edited again")
    click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert rebuilds == []
