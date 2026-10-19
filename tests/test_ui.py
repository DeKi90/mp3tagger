"""UI smoke tests using NiceGUI's simulated user (no browser)."""

import asyncio
from pathlib import Path

import pytest
from mutagen.id3 import ID3
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

from imagery import jpeg, png
from mp3tagger.config import Config
from mp3tagger.ui.app import build_app
from mp3tagger.ui.file_grid import FileGrid


@pytest.fixture
def music_root(make_mp3, tmp_path):
    root = tmp_path / "music"
    make_mp3(root / "rock" / "b.mp3", title="Beta", artist="Band", year="2001", track="2")
    make_mp3(
        root / "rock" / "a.mp3",
        title="Alpha",
        artist="Band",
        year="2000",
        track="1",
        cover=png(3, 2),
    )
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
    """Open `subfolder` of the music root. "Include subfolders" is ticked by default, so it is
    unticked here unless `recursive`."""
    build_app(Config(roots=(music_root,)))
    await user.open("/")
    if not recursive:
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


async def test_subfolders_are_included_by_default(user: User, music_root):
    build_app(Config(roots=(music_root,)))
    await user.open("/")
    user.find("Open folder…").click()
    await asyncio.sleep(0.1)
    click_folder_entry(user, "rock")
    click_in_dialog(user, ui.button, "Open")  # without touching the checkbox
    await user.should_see(kind=ui.label, content=" files · ", retries=100)
    assert sorted(r["filename"] for r in grid_rows(user)) == ["a.mp3", "b.mp3", "c.mp3"]


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


async def click(user: User, text: str) -> None:
    """Click a toolbar/panel button and give its (possibly async) handler time to finish."""
    UserInteraction(user, {button(user, text)}, text).click()
    await asyncio.sleep(0.05)


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
    await click(user, "Save")
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
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert ID3(editing, load_v1=False).version[:2] == (2, 4)
    assert editing.read_bytes()[-128:-125] == b"TAG"


async def test_undo_reverts_edit(user: User, editing):
    assert not button(user, "Undo").enabled
    type_into(user, "Title", "Edited")
    assert button(user, "Undo").enabled
    await click(user, "Undo")
    assert row_for(user, editing)["title"] == "Alpha"
    assert row_for(user, editing)["dirty"] is False
    assert field(user, "Title").value == "Alpha"


async def test_revert_all_asks_for_confirmation(user: User, editing):
    type_into(user, "Title", "Edited")
    await click(user, "Revert all")
    await user.should_see("Discard unsaved changes in 1 file(s)?")
    await click(user, "Discard")
    await asyncio.sleep(0.1)
    assert row_for(user, editing)["dirty"] is False
    assert field(user, "Title").value == "Alpha"


async def test_opening_folder_with_unsaved_changes_asks_first(user: User, editing):
    type_into(user, "Title", "Edited")
    await click(user, "Open folder")
    await user.should_see("unsaved changes")
    await click(user, "Cancel")
    await asyncio.sleep(0.1)
    assert row_for(user, editing)["dirty"] is True  # nothing was discarded


async def test_invalid_year_fails_save_but_keeps_edit(user: User, editing):
    type_into(user, "Year", "abcd")
    await click(user, "Save")
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
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert ID3(b)["TIT2"].text == ["Beta2"]
    assert row_for(user, a)["dirty"] is True and row_for(user, b)["dirty"] is False


# --- batch editing ---------------------------------------------------------------------------


@pytest.fixture
async def batch(user: User, music_root, monkeypatch):
    """A folder is open and a.mp3 (Alpha, 2000) and b.mp3 (Beta, 2001) are both selected."""
    await open_folder(user, music_root, "rock")
    rock = music_root / "rock"
    a, b = rock / "a.mp3", rock / "b.mp3"
    await select(user, monkeypatch, a, b)
    return a, b


async def test_multi_select_shows_keep_for_differing_fields(user: User, batch):
    await user.should_see("2 files selected")
    assert field(user, "Title").value == "<keep>"
    assert field(user, "Year").value == "<keep>"
    assert field(user, "Artist").value == "Band"  # identical in both files
    assert field(user, "Genre").value == ""


async def test_batch_edit_applies_to_all_files_and_keeps_other_fields(user: User, batch):
    a, b = batch
    type_into(user, "Artist", "New Band")
    for path in batch:
        assert row_for(user, path)["artist"] == "New Band"
        assert row_for(user, path)["dirty"] is True
    assert [row_for(user, p)["title"] for p in batch] == ["Alpha", "Beta"]
    await user.should_see("2 modified")
    await click(user, "Save")
    await user.should_see("Saved 2 file(s)")
    for path, title in ((a, "Alpha"), (b, "Beta")):
        tags = ID3(path)
        assert tags["TPE1"].text == ["New Band"]
        assert tags["TIT2"].text == [title]  # <keep> field untouched


async def test_batch_edit_of_a_differing_field_overwrites_all(user: User, batch):
    type_into(user, "Year", "1999")
    assert [row_for(user, p)["year"] for p in batch] == ["1999", "1999"]


async def test_clearing_a_field_in_batch_clears_it_everywhere(user: User, batch):
    type_into(user, "Title", "")
    assert [row_for(user, p)["title"] for p in batch] == ["", ""]
    await click(user, "Save")
    await user.should_see("Saved 2 file(s)")
    assert all("TIT2" not in ID3(p) for p in batch)


async def test_typing_keep_back_restores_the_previous_values(user: User, batch):
    type_into(user, "Title", "Same")
    type_into(user, "Title", "<keep>")
    assert [row_for(user, p)["title"] for p in batch] == ["Alpha", "Beta"]
    assert not any(row_for(user, p)["dirty"] for p in batch)
    assert field(user, "Title").value == "<keep>"


async def test_keep_without_an_edit_in_progress_shows_the_real_value_again(user: User, batch):
    type_into(user, "Artist", "<keep>")  # nothing was edited: keep the files' own value
    assert field(user, "Artist").value == "Band"
    assert not any(row_for(user, p)["dirty"] for p in batch)


async def test_undo_reverts_the_whole_batch_edit(user: User, batch):
    type_into(user, "Artist", "New Band")
    await click(user, "Undo")
    assert [row_for(user, p)["artist"] for p in batch] == ["Band", "Band"]
    assert field(user, "Artist").value == "Band"


async def test_unreadable_files_are_skipped_in_a_batch(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    (rock / "bad.mp3").write_bytes(b"junk")
    await open_folder(user, music_root, "rock")
    paths = [rock / "a.mp3", rock / "b.mp3", rock / "bad.mp3"]
    await select(user, monkeypatch, *paths)
    await user.should_see("3 files selected")
    await user.should_see("1 unreadable file(s) are skipped")
    type_into(user, "Artist", "New Band")
    assert [row_for(user, p)["dirty"] for p in paths] == [True, True, False]


async def test_selecting_only_unreadable_files_shows_message(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    (rock / "bad.mp3").write_bytes(b"junk")
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "bad.mp3")
    await user.should_see("bad.mp3 cannot be edited")


async def test_edits_do_not_rebuild_the_grid(user: User, editing, monkeypatch):
    """A rebuild (grid.update) drops the selection, sorting and column state in the browser."""
    rebuilds = []
    monkeypatch.setattr(ui.aggrid, "update", lambda self: rebuilds.append(1))
    type_into(user, "Title", "Edited")
    await click(user, "Undo")
    type_into(user, "Title", "Edited again")
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert rebuilds == []


# --- cover art -------------------------------------------------------------------------------

NEW_COVER = png(5, 4)


async def upload_cover(user: User, name: str, data: bytes) -> None:
    (upload,) = (e for e in user.client.elements.values() if isinstance(e, ui.upload))
    await upload.handle_uploads([SmallFileUpload(name, "application/octet-stream", data)])
    await asyncio.sleep(0.1)


def cover_buttons(user: User) -> dict[str, bool]:
    """Enabled state of the cover buttons (the first one's label changes with the state)."""
    labels = (
        "Add cover",
        "Replace",
        "Replace all",
        "Set cover",
        "Extract",
        "To folder",
        "From folder",
        "Remove",
    )
    return {
        b.props["label"]: b.enabled
        for b in user.client.elements.values()
        if isinstance(b, ui.button) and b.props.get("label") in labels
    }


async def test_cover_is_shown_for_single_mixed_and_missing(user: User, music_root, monkeypatch):
    await open_folder(user, music_root, "rock")
    rock = music_root / "rock"
    await select(user, monkeypatch, rock / "a.mp3")
    await user.should_see("PNG · 3×2")
    assert cover_buttons(user) == {
        "Replace": True,
        "Extract": True,
        "To folder": True,
        "Remove": True,
    }
    await select(user, monkeypatch, rock / "b.mp3")
    await user.should_see("No embedded cover")
    assert cover_buttons(user) == {
        "Add cover": True,
        "Extract": False,
        "To folder": False,
        "Remove": False,
    }
    await select(user, monkeypatch, rock / "a.mp3", rock / "b.mp3")
    await user.should_see("Covers differ between the files")
    assert cover_buttons(user) == {
        "Replace all": True,
        "Extract": False,
        "To folder": False,
        "Remove": True,
    }


async def test_added_cover_is_pending_until_saved(user: User, music_root, monkeypatch):
    await open_folder(user, music_root, "rock")
    b = music_root / "rock" / "b.mp3"
    await select(user, monkeypatch, b)
    await upload_cover(user, "front.png", NEW_COVER)
    await user.should_see("PNG · 5×4")
    await user.should_see("modified")
    assert row_for(user, b)["cover"] == "✓" and row_for(user, b)["dirty"] is True
    assert not ID3(b).getall("APIC")  # not written yet
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert [f.data for f in ID3(b).getall("APIC")] == [NEW_COVER]
    assert row_for(user, b)["dirty"] is False
    await user.should_see("PNG · 5×4")


async def test_cover_is_judged_by_content_not_file_name(user: User, editing):
    await upload_cover(user, "photo.jpg", NEW_COVER)  # a PNG called .jpg
    await user.should_see("PNG · 5×4")


async def test_non_image_upload_is_rejected(user: User, editing):
    await upload_cover(user, "notes.png", b"definitely not an image")
    await user.should_see("Unsupported image format")
    assert row_for(user, editing)["dirty"] is False
    await user.should_see("PNG · 3×2")  # the old cover is still shown


async def test_remove_cover_and_save(user: User, editing):
    await click(user, "Remove")
    await user.should_see("No embedded cover")
    assert row_for(user, editing)["cover"] == "" and row_for(user, editing)["dirty"] is True
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert not ID3(editing).getall("APIC")


async def test_undo_restores_the_cover(user: User, editing):
    await upload_cover(user, "x.png", NEW_COVER)
    await user.should_see("PNG · 5×4")
    await click(user, "Undo")
    await user.should_see("PNG · 3×2")
    assert row_for(user, editing)["dirty"] is False


async def test_revert_all_restores_the_cover(user: User, editing):
    await click(user, "Remove")
    await click(user, "Revert all")
    await click(user, "Discard")
    await user.should_see("PNG · 3×2")
    assert row_for(user, editing)["dirty"] is False


async def test_replace_cover_of_all_selected_files(user: User, batch):
    a, b = batch
    await upload_cover(user, "x.png", NEW_COVER)
    await user.should_see("PNG · 5×4")
    assert [row_for(user, p)["cover"] for p in batch] == ["✓", "✓"]
    await click(user, "Save")
    await user.should_see("Saved 2 file(s)")
    assert [[f.data for f in ID3(p).getall("APIC")] for p in (a, b)] == [[NEW_COVER], [NEW_COVER]]


def capture_downloads(monkeypatch) -> list[tuple[bytes, str | None, str]]:
    downloads = []

    def content(data, filename=None, media_type=""):
        downloads.append((data, filename, media_type))

    monkeypatch.setattr(ui.download, "content", content)
    return downloads


async def test_extract_downloads_the_shown_cover(user: User, editing, monkeypatch):
    downloads = capture_downloads(monkeypatch)
    await user.should_see("PNG · 3×2")
    await click(user, "Extract")
    assert downloads == [(png(3, 2), "a.png", "image/png")]


async def test_extract_shows_a_pending_cover(user: User, editing, monkeypatch):
    downloads = capture_downloads(monkeypatch)
    await upload_cover(user, "x.png", NEW_COVER)
    await user.should_see("PNG · 5×4")
    await click(user, "Extract")
    assert [data for data, _, _ in downloads] == [NEW_COVER]


async def test_cover_column_reflects_files(user: User, music_root):
    await open_folder(user, music_root, "rock")
    rows = {r["filename"]: r["cover"] for r in grid_rows(user)}
    assert rows == {"a.mp3": "✓", "b.mp3": ""}


async def test_jpeg_cover_is_stored_with_its_mime_type(user: User, music_root, monkeypatch):
    await open_folder(user, music_root, "rock")
    b = music_root / "rock" / "b.mp3"
    await select(user, monkeypatch, b)
    await upload_cover(user, "x.jpg", jpeg(40, 30))
    await user.should_see("JPEG · 40×30")
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    (apic,) = ID3(b).getall("APIC")
    assert (apic.mime, apic.type) == ("image/jpeg", 3)


# --- moving the cover into the album folder --------------------------------------------------


async def test_move_cover_to_folder_is_pending_until_saved(user: User, editing, music_root):
    folder_image = music_root / "rock" / "cover.png"
    await click(user, "To folder")
    await user.should_see("cover.png is written on save")
    assert row_for(user, editing)["cover"] == "" and row_for(user, editing)["dirty"] is True
    assert not folder_image.exists()
    assert ID3(editing).getall("APIC")  # the file is untouched until saved
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert folder_image.read_bytes() == png(3, 2)
    assert not ID3(editing).getall("APIC")
    # The file now has no embedded picture; the panel shows the folder image it was moved to.
    await user.should_see("PNG · 3×2")
    await user.should_see("folder image (cover.png)")
    assert row_for(user, editing)["dirty"] is False


async def test_move_cover_can_be_undone(user: User, editing, music_root):
    await click(user, "To folder")
    await click(user, "Undo")
    await user.should_see("PNG · 3×2")
    assert row_for(user, editing)["dirty"] is False
    assert not (music_root / "rock" / "cover.png").exists()


async def test_move_cover_skips_a_folder_with_a_different_image(user: User, editing, music_root):
    (music_root / "rock" / "cover.png").write_bytes(b"another image")
    await click(user, "To folder")
    await user.should_see("already exists with other content")
    assert row_for(user, editing)["dirty"] is False
    assert ID3(editing).getall("APIC")
    assert (music_root / "rock" / "cover.png").read_bytes() == b"another image"


async def test_move_cover_of_a_whole_album_writes_one_image(
    user: User, make_mp3, music_root, monkeypatch
):
    rock = music_root / "rock"
    a, b = rock / "a.mp3", rock / "b.mp3"
    make_mp3(b, title="Beta", cover=png(3, 2))  # same cover as a.mp3
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, a, b)
    await user.should_see("PNG · 3×2")
    await click(user, "To folder")
    assert [row_for(user, p)["dirty"] for p in (a, b)] == [True, True]
    await click(user, "Save")
    await user.should_see("Saved 2 file(s)")
    assert (rock / "cover.png").read_bytes() == png(3, 2)
    assert not ID3(a).getall("APIC") and not ID3(b).getall("APIC")


async def test_a_jpeg_cover_becomes_cover_jpg(user: User, music_root, monkeypatch):
    await open_folder(user, music_root, "rock")
    b = music_root / "rock" / "b.mp3"
    await select(user, monkeypatch, b)
    data = jpeg(40, 30)
    await upload_cover(user, "x.jpg", data)
    await user.should_see("JPEG · 40×30")
    await click(user, "To folder")
    await user.should_see("cover.jpg is written on save")
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert (music_root / "rock" / "cover.jpg").read_bytes() == data
    assert not ID3(b).getall("APIC")


async def test_failed_move_keeps_the_pending_change_and_the_embedded_cover(
    user: User, editing, music_root
):
    await click(user, "To folder")
    await user.should_see("cover.png is written on save")  # planned: nothing in the way yet
    (music_root / "rock" / "cover.png").write_bytes(b"appeared meanwhile")
    await click(user, "Save")
    await user.should_see("already exists with other content")
    assert row_for(user, editing)["dirty"] is True
    assert ID3(editing).getall("APIC")


# --- folder image fallback -------------------------------------------------------------------


async def test_a_file_without_embedded_cover_shows_the_folder_image(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    (rock / "cover.jpg").write_bytes(jpeg(40, 30))
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "b.mp3")  # b.mp3 has no embedded cover
    await user.should_see("JPEG · 40×30")
    await user.should_see("folder image (cover.jpg)")
    # Nothing is embedded, so it cannot be removed; it can be embedded instead of moved.
    assert cover_buttons(user) == {
        "Add cover": True,
        "Extract": True,
        "From folder": True,
        "Remove": False,
    }
    assert row_for(user, rock / "b.mp3")["cover"] == ""  # the Cover column is about embedded art


async def test_embedded_cover_wins_over_the_folder_image(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    (rock / "cover.jpg").write_bytes(jpeg(40, 30))
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3")  # a.mp3 has an embedded 3×2 PNG
    await user.should_see("PNG · 3×2")
    await user.should_not_see("folder image")


async def test_embedded_and_folder_covers_in_one_selection_differ(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    (rock / "cover.png").write_bytes(png(3, 2))  # the very same picture as a.mp3 embeds
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3", rock / "b.mp3")
    await user.should_see("Covers differ between the files")


async def test_removing_the_embedded_cover_reveals_the_folder_image(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    (rock / "folder.jpg").write_bytes(jpeg(40, 30))
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3")
    await click(user, "Remove")
    await user.should_see("folder image (folder.jpg)")
    await user.should_see("modified")
    assert cover_buttons(user)["Remove"] is False


async def test_adding_a_cover_to_a_file_with_a_folder_image_embeds_it(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    (rock / "cover.jpg").write_bytes(jpeg(40, 30))
    await open_folder(user, music_root, "rock")
    b = rock / "b.mp3"
    await select(user, monkeypatch, b)
    await upload_cover(user, "x.png", NEW_COVER)
    await user.should_see("PNG · 5×4")
    await user.should_not_see("folder image")
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert [f.data for f in ID3(b).getall("APIC")] == [NEW_COVER]
    assert (rock / "cover.jpg").read_bytes() == jpeg(40, 30)  # the folder image is untouched


async def test_extract_downloads_the_folder_image(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    (rock / "cover.jpg").write_bytes(jpeg(40, 30))
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "b.mp3")
    await user.should_see("folder image (cover.jpg)")
    downloads = capture_downloads(monkeypatch)
    await click(user, "Extract")
    assert downloads == [(jpeg(40, 30), "b.jpg", "image/jpeg")]


async def test_no_cover_anywhere(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "b.mp3")
    await user.should_see("No embedded cover or folder image")


async def test_each_file_uses_the_image_of_its_own_folder(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    (rock / "deep" / "cover.jpg").write_bytes(jpeg(40, 30))
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, rock / "deep" / "c.mp3")
    await user.should_see("folder image (cover.jpg)")
    await select(user, monkeypatch, rock / "b.mp3")  # its folder has no image
    await user.should_see("No embedded cover or folder image")


async def test_embed_the_folder_image_into_a_file(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    data = jpeg(40, 30)
    (rock / "cover.jpg").write_bytes(data)
    await open_folder(user, music_root, "rock")
    b = rock / "b.mp3"
    await select(user, monkeypatch, b)
    await user.should_see("folder image (cover.jpg)")
    await click(user, "From folder")
    await user.should_see("modified")
    await user.should_not_see("folder image")  # it is the embedded cover now
    assert row_for(user, b)["cover"] == "✓" and row_for(user, b)["dirty"] is True
    assert cover_buttons(user)["To folder"] is True  # an embedded cover again
    assert not ID3(b).getall("APIC")  # pending until saved
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    (apic,) = ID3(b).getall("APIC")
    assert (apic.data, apic.mime, apic.type) == (data, "image/jpeg", 3)
    assert (rock / "cover.jpg").read_bytes() == data  # the folder image stays


async def test_embed_the_folder_image_into_all_selected_files(
    user: User, make_mp3, music_root, monkeypatch
):
    rock = music_root / "rock"
    a, b = rock / "a.mp3", rock / "b.mp3"
    make_mp3(a, title="Alpha")  # no embedded cover any more
    (rock / "cover.png").write_bytes(NEW_COVER)
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, a, b)
    await user.should_see("folder image (cover.png)")
    await click(user, "From folder")
    assert [row_for(user, p)["cover"] for p in (a, b)] == ["✓", "✓"]
    await click(user, "Save")
    await user.should_see("Saved 2 file(s)")
    assert [[f.data for f in ID3(p).getall("APIC")] for p in (a, b)] == [[NEW_COVER], [NEW_COVER]]


async def test_embedding_the_folder_image_can_be_undone(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    (rock / "cover.jpg").write_bytes(jpeg(40, 30))
    await open_folder(user, music_root, "rock")
    b = rock / "b.mp3"
    await select(user, monkeypatch, b)
    await user.should_see("folder image (cover.jpg)")
    await click(user, "From folder")
    await click(user, "Undo")
    await user.should_see("folder image (cover.jpg)")
    assert row_for(user, b)["dirty"] is False
