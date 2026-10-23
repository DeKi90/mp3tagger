"""The converters (Filename -> Tag, Tag -> Filename, Tag -> Tag, auto-number) in the page."""

from pathlib import Path

import pytest
from mutagen.id3 import ID3
from nicegui import ui
from nicegui.testing import User

from mp3tagger.core.tagio.id3 import Id3Reader
from mp3tagger.ui.file_grid import FileGrid
from uihelpers import (
    button,
    choose,
    click,
    grid_rows,
    open_folder,
    row_for,
    select,
    table_rows,
    type_into,
)


def convert_button(user: User) -> ui.button:
    return button(user, "Convert")


@pytest.fixture
def pop(make_mp3, music_root):
    """pop/ holds files named like "Artist - Title" with nothing in their tags yet."""
    folder = music_root / "pop"
    for name in ("Cher - Believe.mp3", "Abba - Waterloo.mp3", "NoSeparator.mp3"):
        make_mp3(folder / name)
    return folder


async def open_pop(user: User, music_root, monkeypatch, *names: str) -> list[Path]:
    await open_folder(user, music_root, "pop", recursive=True)
    paths = [music_root / "pop" / n for n in names]
    await select(user, monkeypatch, *paths)
    return paths


# --- the menu --------------------------------------------------------------------------------


async def test_convert_menu_needs_a_selection(user: User, music_root, monkeypatch):
    await open_folder(user, music_root, "rock")
    assert not convert_button(user).enabled
    await select(user, monkeypatch, music_root / "rock" / "a.mp3")
    assert convert_button(user).enabled


# --- Filename -> Tag -------------------------------------------------------------------------


async def test_filename_to_tag_previews_and_applies_as_one_undo_step(
    user: User, music_root, pop, monkeypatch
):
    cher, abba, nosep = await open_pop(
        user,
        music_root,
        monkeypatch,
        "Cher - Believe.mp3",
        "Abba - Waterloo.mp3",
        "NoSeparator.mp3",
    )
    await choose(user, "Filename → Tag…")
    assert table_rows(user) == [
        {"file": "Cher - Believe.mp3", "artist": "Cher", "title": "Believe", "match": ""},
        {"file": "Abba - Waterloo.mp3", "artist": "Abba", "title": "Waterloo", "match": ""},
        {"file": "NoSeparator.mp3", "artist": "", "title": "", "match": "no match"},
    ]
    await user.should_see("2 of 3 files match")
    assert not any(row_for(user, p)["dirty"] for p in (cher, abba, nosep))  # preview only
    await click(user, "Apply to 2")
    await user.should_see("Filename → Tag: 2 file(s) modified")
    assert (row_for(user, cher)["artist"], row_for(user, cher)["title"]) == ("Cher", "Believe")
    assert (row_for(user, abba)["artist"], row_for(user, abba)["title"]) == ("Abba", "Waterloo")
    assert [row_for(user, p)["dirty"] for p in (cher, abba, nosep)] == [True, True, False]
    assert Id3Reader().read(cher).tags.artist == ""  # nothing is written until saved
    await click(user, "Undo")
    assert [row_for(user, p)["dirty"] for p in (cher, abba)] == [
        False,
        False,
    ]  # ONE step undoes all


async def test_filename_to_tag_can_be_saved(user: User, music_root, pop, monkeypatch):
    (cher,) = await open_pop(user, music_root, monkeypatch, "Cher - Believe.mp3")
    await choose(user, "Filename → Tag…")
    await click(user, "Apply to 1")
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    tags = ID3(cher)
    assert (tags["TPE1"].text, tags["TIT2"].text) == (["Cher"], ["Believe"])


async def test_filename_to_tag_with_a_different_pattern_updates_the_preview(
    user: User, music_root, pop, monkeypatch
):
    await open_pop(user, music_root, monkeypatch, "Cher - Believe.mp3")
    await choose(user, "Filename → Tag…")
    type_into(user, "Pattern", "%title% - %artist%")
    assert table_rows(user)[0]["title"] == "Cher" and table_rows(user)[0]["artist"] == "Believe"


async def test_filename_to_tag_reads_folder_names_too(
    user: User, make_mp3, music_root, monkeypatch
):
    track = make_mp3(music_root / "lib" / "Cher" / "Believe" / "03 - Believe.mp3")
    await open_folder(user, music_root, "lib", recursive=True)
    await select(user, monkeypatch, track)
    await choose(user, "Filename → Tag…")
    type_into(user, "Pattern", "%artist%/%album%/%track% - %title%")
    (row,) = table_rows(user)
    assert (row["artist"], row["album"], row["track"], row["title"]) == (
        "Cher",
        "Believe",
        "03",
        "Believe",
    )


async def test_invalid_pattern_shows_the_problem_and_blocks_apply(
    user: User, music_root, pop, monkeypatch
):
    await open_pop(user, music_root, monkeypatch, "Cher - Believe.mp3")
    await choose(user, "Filename → Tag…")
    type_into(user, "Pattern", "%titel%")
    await user.should_see("Unknown field %titel%")
    assert not button(user, "Apply").enabled
    type_into(user, "Pattern", "")
    await user.should_see("The pattern is empty")


async def test_cancel_changes_nothing(user: User, music_root, pop, monkeypatch):
    cher, *_ = await open_pop(user, music_root, monkeypatch, "Cher - Believe.mp3")
    await choose(user, "Filename → Tag…")
    await click(user, "Cancel")
    assert row_for(user, cher)["dirty"] is False


# --- Tag -> Filename -------------------------------------------------------------------------


async def test_tag_to_filename_previews_then_renames_on_disk(user: User, editing, music_root):
    rock = music_root / "rock"
    a = editing
    await choose(user, "Tag → Filename…")
    assert table_rows(user) == [{"old": "a.mp3", "new": "01 - Alpha.mp3", "note": ""}]
    assert a.exists()  # preview only
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    assert not a.exists() and (rock / "01 - Alpha.mp3").exists()
    assert {r["filename"] for r in grid_rows(user)} == {"01 - Alpha.mp3", "b.mp3"}
    await user.should_see("01 - Alpha.mp3")  # the panel still shows the selected file


async def test_rename_uses_unsaved_edits_and_keeps_them_pending(user: User, editing, music_root):
    type_into(user, "Title", "Edited")
    await choose(user, "Tag → Filename…")
    assert table_rows(user)[0]["new"] == "01 - Edited.mp3"  # effective tags, not the file's
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    new = music_root / "rock" / "01 - Edited.mp3"
    assert row_for(user, new)["dirty"] is True and row_for(user, new)["title"] == "Edited"
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert ID3(new)["TIT2"].text == ["Edited"]  # written to the renamed file


async def test_undo_still_works_after_a_rename(user: User, editing, music_root):
    type_into(user, "Title", "Edited")
    await choose(user, "Tag → Filename…")
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    await click(user, "Undo")
    new = music_root / "rock" / "01 - Edited.mp3"
    assert row_for(user, new)["dirty"] is False and row_for(user, new)["title"] == "Alpha"


async def test_rename_skips_conflicts_and_reports_them(
    user: User, make_mp3, music_root, monkeypatch
):
    rock = music_root / "rock"
    make_mp3(rock / "01 - Alpha.mp3")  # already taken, and not part of the selection
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3", rock / "b.mp3")
    await choose(user, "Tag → Filename…")
    rows = {r["old"]: r for r in table_rows(user)}
    assert rows["a.mp3"]["note"].startswith("⚠") and "exists" in rows["a.mp3"]["note"]
    assert rows["b.mp3"]["new"] == "02 - Beta.mp3" and rows["b.mp3"]["note"] == ""
    await user.should_see("1 to rename, 0 unchanged, 1 with problems")
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    assert (rock / "a.mp3").exists() and (rock / "02 - Beta.mp3").exists()


async def test_rename_button_is_disabled_when_nothing_can_be_renamed(
    user: User, music_root, pop, monkeypatch
):
    await open_pop(user, music_root, monkeypatch, "NoSeparator.mp3")  # no title in the tags
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%title%")
    assert not button(user, "Rename").enabled
    assert "⚠" in table_rows(user)[0]["note"]


async def test_rename_warns_about_empty_fields_but_allows_it(user: User, editing):
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%composer% - %title%")  # composer is empty in the tags
    (row,) = table_rows(user)
    assert row["new"] == "- Alpha.mp3" and row["note"] == "empty: composer"
    await user.should_see("1 with an empty field")
    assert button(user, "Rename").enabled


async def test_rename_pattern_with_a_folder_separator_is_refused(user: User, editing, music_root):
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "../%title%")
    await user.should_see("A folder name cannot be . or ..")
    assert not button(user, "Rename").enabled
    assert editing.exists()


async def test_rename_of_several_files_swapping_names(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3", rock / "b.mp3")
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%track:2%")  # a.mp3 -> 01.mp3, b.mp3 -> 02.mp3
    await click(user, "Rename 2")
    await user.should_see("Renamed 2 file(s)")
    assert sorted(p.name for p in rock.glob("*.mp3")) == ["01.mp3", "02.mp3"]
    assert ID3(rock / "01.mp3")["TIT2"].text == ["Alpha"]  # content followed the rename


# --- Tag -> Tag ------------------------------------------------------------------------------


async def test_tag_to_tag_copies_a_formatted_value_into_a_field(user: User, batch):
    await choose(user, "Tag → Tag…")
    assert [r["new"] for r in table_rows(user)] == [
        "Band",
        "Band",
    ]  # default: artist -> album artist
    await user.should_see("2 of 2 files change")
    await click(user, "Apply")
    assert [row_for(user, p)["album_artist"] for p in batch] == ["Band", "Band"]
    assert all(row_for(user, p)["dirty"] for p in batch)
    await click(user, "Undo")
    assert [row_for(user, p)["album_artist"] for p in batch] == ["", ""]


async def test_tag_to_tag_with_a_combined_format_and_another_field(user: User, batch):
    await choose(user, "Tag → Tag…")
    (target,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.select) and e.props.get("label") == "Set field"
    )
    target.set_value("comment")
    type_into(user, "Pattern", "%title% (%year%)")
    assert [r["new"] for r in table_rows(user)] == ["Alpha (2000)", "Beta (2001)"]
    await click(user, "Apply")
    assert [row_for(user, p)["comment"] for p in batch] == ["Alpha (2000)", "Beta (2001)"]


async def test_tag_to_tag_only_enables_apply_when_something_changes(user: User, batch):
    await choose(user, "Tag → Tag…")
    (target,) = (
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.select) and e.props.get("label") == "Set field"
    )
    target.set_value("artist")  # artist <- %artist%: no change at all
    await user.should_see("0 of 2 files change")
    assert not button(user, "Apply").enabled


# --- Auto-number -----------------------------------------------------------------------------


async def test_auto_number_follows_the_displayed_order_and_restarts_per_folder(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    a, b, c = rock / "a.mp3", rock / "b.mp3", rock / "deep" / "c.mp3"
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, a, b, c)

    async def displayed(_self) -> list[Path]:
        return [c, b, a]  # as if the user sorted the grid that way

    monkeypatch.setattr(FileGrid, "displayed_paths", displayed)
    await choose(user, "Auto-number tracks…")
    # restart per folder is the default: deep/ restarts, rock/ counts b then a
    assert [(r["file"], r["track"]) for r in table_rows(user)] == [
        ("c.mp3", "1"),
        ("b.mp3", "1"),
        ("a.mp3", "2"),
    ]
    await click(user, "Apply")
    assert [row_for(user, p)["track"] for p in (c, b, a)] == ["1", "1", "2"]
    await click(user, "Undo")  # one step
    assert [row_for(user, p)["track"] for p in (a, b)] == ["1", "2"]  # the original tags


async def test_auto_number_options(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    a, b, c = rock / "a.mp3", rock / "b.mp3", rock / "deep" / "c.mp3"
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, a, b, c)

    async def displayed(_self) -> list[Path]:
        return [a, b, c]

    monkeypatch.setattr(FileGrid, "displayed_paths", displayed)
    await choose(user, "Auto-number tracks…")
    elements = list(user.client.elements.values())
    restart = next(e for e in elements if isinstance(e, ui.checkbox) and "again" in e.text)
    total = next(e for e in elements if isinstance(e, ui.checkbox) and "total" in e.text)
    start = next(e for e in elements if isinstance(e, ui.number))
    width = next(
        e for e in elements if isinstance(e, ui.select) and e.props.get("label") == "Digits"
    )
    restart.set_value(False)
    start.set_value(8)
    width.set_value(2)
    total.set_value(True)
    assert [r["track"] for r in table_rows(user)] == ["08/03", "09/03", "10/03"]
    await click(user, "Apply")
    assert [row_for(user, p)["track"] for p in (a, b, c)] == ["08/03", "09/03", "10/03"]


async def test_auto_number_ignores_unselected_files(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    a, b = rock / "a.mp3", rock / "b.mp3"
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, b)

    async def displayed(_self) -> list[Path]:
        return [a, b, rock / "deep" / "c.mp3"]  # everything shown, only b selected

    monkeypatch.setattr(FileGrid, "displayed_paths", displayed)
    await choose(user, "Auto-number tracks…")
    assert [r["file"] for r in table_rows(user)] == ["b.mp3"]


# --- sorting into folders --------------------------------------------------------------------


async def test_a_folder_pattern_sorts_files_into_folders_below_the_open_folder(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock")
    a, b = rock / "a.mp3", rock / "b.mp3"
    await select(user, monkeypatch, a, b)
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%artist%/%year%/%track:2% - %title%")
    assert table_rows(user) == [
        {"old": "a.mp3", "new": "Band/2000/01 - Alpha.mp3", "note": ""},
        {"old": "b.mp3", "new": "Band/2001/02 - Beta.mp3", "note": ""},
    ]  # paths below the open folder
    assert not (rock / "Band").exists()  # preview only
    await click(user, "Rename 2")
    await user.should_see("Renamed 2 file(s)")
    assert (rock / "Band" / "2000" / "01 - Alpha.mp3").exists()
    assert (rock / "Band" / "2001" / "02 - Beta.mp3").exists()
    assert not a.exists() and not b.exists()
    moved = rock / "Band" / "2000" / "01 - Alpha.mp3"
    assert row_for(user, moved)["path"] == "Band/2000"  # the Folder column, below the open folder
    assert ID3(moved)["TIT2"].text == ["Alpha"]  # the content moved with the file


async def test_the_selection_and_pending_edits_survive_a_move_into_folders(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3")
    type_into(user, "Title", "Edited")
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%artist%/%title%")
    assert table_rows(user)[0]["new"] == "Band/Edited.mp3"  # from the unsaved edit
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    new = rock / "Band" / "Edited.mp3"
    assert row_for(user, new)["dirty"] is True
    await user.should_see("Edited.mp3")  # the panel still shows the selected file
    await click(user, "Save")
    await user.should_see("Saved 1 file(s)")
    assert ID3(new)["TIT2"].text == ["Edited"]


async def test_folders_left_empty_by_the_move_are_removed(user: User, music_root, monkeypatch):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock", recursive=True)
    c = rock / "deep" / "c.mp3"
    await select(user, monkeypatch, c)
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "Sorted/%title%")
    assert table_rows(user)[0]["old"] == "deep/c.mp3"  # nested files show their folder
    assert table_rows(user)[0]["new"] == "Sorted/Gamma.mp3"
    await click(user, "Rename 1")
    await user.should_see("removed 1 empty folder(s)")
    assert (rock / "Sorted" / "Gamma.mp3").exists() and not (rock / "deep").exists()
    assert (rock / "a.mp3").exists()  # the rest of the open folder is untouched


async def test_a_pattern_without_folders_renames_in_place_even_in_subfolders(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, rock / "deep" / "c.mp3")
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%title%")
    assert table_rows(user)[0]["new"] == "deep/Gamma.mp3"  # still in deep/
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    assert (rock / "deep" / "Gamma.mp3").exists() and not (rock / "Gamma.mp3").exists()


async def test_a_missing_tag_for_a_folder_blocks_just_that_file(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, rock / "a.mp3", rock / "deep" / "c.mp3")  # c has no artist
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%artist%/%title%")
    rows = {r["old"]: r for r in table_rows(user)}
    assert rows["a.mp3"]["new"] == "Band/Alpha.mp3" and rows["a.mp3"]["note"] == ""
    assert "A folder name would be empty" in rows["deep/c.mp3"]["note"]
    await user.should_see("1 to rename, 0 unchanged, 1 with problems")
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    assert (rock / "Band" / "Alpha.mp3").exists() and (rock / "deep" / "c.mp3").exists()


async def test_a_file_where_a_folder_should_go_is_reported(
    user: User, make_mp3, music_root, monkeypatch
):
    rock = music_root / "rock"
    (rock / "Band").write_bytes(b"a file, not a folder")
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3")
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%artist%/%title%")
    assert "Band is a file, not a folder" in table_rows(user)[0]["note"]
    assert not button(user, "Rename").enabled


async def test_a_folder_pattern_needs_no_slash_tricks_to_stay_inside(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3")
    type_into(user, "Title", "../../escape")
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", "%artist%/%title%")
    assert table_rows(user)[0]["new"] == "Band/_._.._escape.mp3"  # separators in values are tamed
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    assert (rock / "Band" / "_._.._escape.mp3").exists()
    assert not (music_root / "escape.mp3").exists()


# --- reading tags from paths below the open folder -------------------------------------------


async def test_filename_to_tag_shows_and_reads_the_path_below_the_open_folder(
    user: User, make_mp3, music_root, monkeypatch
):
    rock = music_root / "rock"
    track = make_mp3(rock / "Band" / "LP" / "07 - Song.mp3")
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, track)
    await choose(user, "Filename → Tag…")
    type_into(user, "Pattern", "%artist%/%album%/%track% - %title%")
    (row,) = table_rows(user)
    assert row["file"] == "Band/LP/07 - Song.mp3"  # the relative path, not just the name
    assert (row["artist"], row["album"], row["track"], row["title"]) == ("Band", "LP", "07", "Song")
    await click(user, "Apply to 1")
    assert (row_for(user, track)["artist"], row_for(user, track)["album"]) == ("Band", "LP")


async def test_a_folder_pattern_must_fit_the_depth_below_the_open_folder(
    user: User, make_mp3, music_root, monkeypatch
):
    rock = music_root / "rock"
    deep = make_mp3(rock / "Band" / "LP" / "Disc 1" / "07 - Song.mp3")
    await open_folder(user, music_root, "rock", recursive=True)
    await select(user, monkeypatch, deep)
    await choose(user, "Filename → Tag…")
    type_into(user, "Pattern", "%artist%/%album%/%title%")  # one level short: no guessing
    assert table_rows(user)[0]["match"] == "no match"
    type_into(user, "Pattern", "%track% - %title%")  # the file name alone matches at any depth
    assert table_rows(user)[0]["title"] == "Song"


async def test_the_same_pattern_reads_back_what_the_rename_wrote(
    user: User, music_root, monkeypatch
):
    rock = music_root / "rock"
    pattern = "%artist%/%year%/%track:2% - %title%"
    await open_folder(user, music_root, "rock")
    a = rock / "a.mp3"
    await select(user, monkeypatch, a)
    await choose(user, "Tag → Filename…")
    type_into(user, "Pattern", pattern)
    await click(user, "Rename 1")
    await user.should_see("Renamed 1 file(s)")
    moved = rock / "Band" / "2000" / "01 - Alpha.mp3"
    await choose(user, "Filename → Tag…")
    type_into(user, "Pattern", "%artist%/%year%/%track% - %title%")
    (row,) = table_rows(user)
    assert (row["file"], row["artist"], row["year"], row["track"], row["title"]) == (
        "Band/2000/01 - Alpha.mp3",
        "Band",
        "2000",
        "01",
        "Alpha",
    )
    assert moved.exists()
