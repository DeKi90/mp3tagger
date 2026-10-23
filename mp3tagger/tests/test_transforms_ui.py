"""Change case and find/replace in the page."""

from nicegui.testing import User

from uihelpers import (
    button,
    checkbox_named,
    choose,
    click,
    row_for,
    select_named,
    table_rows,
    type_into,
)


async def open_case(user: User, style: str = "upper") -> None:
    await choose(user, "Change case…")
    select_named(user, "Style").set_value(style)


# --- change case -----------------------------------------------------------------------------


async def test_change_case_previews_every_changed_value_and_applies_as_one_step(user: User, batch):
    await open_case(user, "upper")
    assert table_rows(user) == [
        {"file": "a.mp3", "field": "Title", "old": "Alpha", "new": "ALPHA"},
        {"file": "a.mp3", "field": "Artist", "old": "Band", "new": "BAND"},
        {"file": "b.mp3", "field": "Title", "old": "Beta", "new": "BETA"},
        {"file": "b.mp3", "field": "Artist", "old": "Band", "new": "BAND"},
    ]  # album is empty in both files: nothing to change
    await user.should_see("4 value(s) change in 2 of 2 files")
    assert not any(row_for(user, p)["dirty"] for p in batch)  # preview only
    await click(user, "Apply to 2")
    await user.should_see("Change case: 2 file(s) modified")
    assert [row_for(user, p)["title"] for p in batch] == ["ALPHA", "BETA"]
    assert [row_for(user, p)["artist"] for p in batch] == ["BAND", "BAND"]
    await click(user, "Undo")  # one step for both files and both fields
    assert [row_for(user, p)["title"] for p in batch] == ["Alpha", "Beta"]
    assert not any(row_for(user, p)["dirty"] for p in batch)


async def test_change_case_only_touches_the_chosen_fields(user: User, batch):
    await open_case(user, "lower")
    select_named(user, "Fields").set_value(["artist"])
    assert {r["field"] for r in table_rows(user)} == {"Artist"}
    await click(user, "Apply")
    assert [row_for(user, p)["artist"] for p in batch] == ["band", "band"]
    assert [row_for(user, p)["title"] for p in batch] == ["Alpha", "Beta"]


async def test_title_case_keeps_small_words_unless_told_otherwise(user: User, batch):
    type_into(user, "Title", "the lord of the rings")
    await open_case(user, "title")
    assert [r["new"] for r in table_rows(user) if r["field"] == "Title"] == [
        "The Lord of the Rings"
    ] * 2
    checkbox_named(user, "small words").set_value(False)
    assert [r["new"] for r in table_rows(user) if r["field"] == "Title"] == [
        "The Lord Of The Rings"
    ] * 2


async def test_small_words_option_only_matters_for_title_case(user: User, batch):
    await open_case(user, "title")
    assert checkbox_named(user, "small words").enabled
    select_named(user, "Style").set_value("upper")
    assert not checkbox_named(user, "small words").enabled


async def test_change_case_cannot_be_applied_when_nothing_changes(user: User, batch):
    await open_case(user, "title")  # Alpha, Beta, Band are in title case already
    await user.should_see("0 value(s) change in 0 of 2 files")
    assert table_rows(user) == [] and not button(user, "Apply").enabled


async def test_change_case_can_be_saved(user: User, batch):
    from mutagen.id3 import ID3

    await open_case(user, "upper")
    await click(user, "Apply to 2")
    await click(user, "Save")
    await user.should_see("Saved 2 file(s)")
    assert [ID3(p)["TIT2"].text for p in batch] == [["ALPHA"], ["BETA"]]


# --- find and replace ------------------------------------------------------------------------


async def open_find(user: User, find: str, replace: str = "", fields=("artist",)) -> None:
    await choose(user, "Find and replace…")
    select_named(user, "Fields").set_value(list(fields))
    type_into(user, "Find", find)
    type_into(user, "Replace with", replace)


async def test_find_and_replace_plain_text(user: User, batch):
    await open_find(user, "band", "The Band")  # case-insensitive by default
    assert table_rows(user) == [
        {"file": "a.mp3", "field": "Artist", "old": "Band", "new": "The Band"},
        {"file": "b.mp3", "field": "Artist", "old": "Band", "new": "The Band"},
    ]
    await click(user, "Apply to 2")
    await user.should_see("Find and replace: 2 file(s) modified")
    assert [row_for(user, p)["artist"] for p in batch] == ["The Band", "The Band"]
    await click(user, "Undo")
    assert [row_for(user, p)["artist"] for p in batch] == ["Band", "Band"]


async def test_find_and_replace_match_case(user: User, batch):
    await open_find(user, "band", "X")
    checkbox_named(user, "Match case").set_value(True)
    assert table_rows(user) == []
    await user.should_see("0 value(s) change")


async def test_find_and_replace_with_regular_expression_and_groups(user: User, batch):
    await open_find(user, r"^(.)(.*)$", r"\2\1", fields=("title",))
    assert table_rows(user) == []  # still literal text: "^(.)(.*)$" is not in any title
    checkbox_named(user, "Regular expression").set_value(True)
    assert [r["new"] for r in table_rows(user)] == ["lphaA", "etaB"]
    await click(user, "Apply")
    assert [row_for(user, p)["title"] for p in batch] == ["lphaA", "etaB"]


async def test_find_and_replace_whole_field(user: User, batch):
    await open_find(user, "ban", "X")
    assert [r["new"] for r in table_rows(user)] == ["Xd", "Xd"]  # a part of the field
    checkbox_named(user, "whole field").set_value(True)
    assert table_rows(user) == []  # "ban" is not the whole field
    type_into(user, "Find", "BAND")
    assert [r["new"] for r in table_rows(user)] == ["X", "X"]


async def test_find_and_replace_removing_text(user: User, batch):
    await open_find(user, "ph", "", fields=("title",))
    assert [r["new"] for r in table_rows(user)] == ["Ala"]  # "Beta" has no "ph"


async def test_invalid_regular_expression_is_explained_and_blocks_apply(user: User, batch):
    await open_find(user, "(oops")
    checkbox_named(user, "Regular expression").set_value(True)
    await user.should_see("Invalid regular expression")
    assert not button(user, "Apply").enabled and table_rows(user) == []
    type_into(user, "Find", r"(o)ops")
    type_into(user, "Replace with", r"\3")
    await user.should_see("Invalid regular expression")  # \3 refers to a group that is not there


async def test_nothing_is_reported_before_the_user_has_typed_anything(user: User, batch):
    await choose(user, "Find and replace…")
    await user.should_not_see("Enter the text to find")
    assert not button(user, "Apply").enabled


async def test_find_and_replace_can_be_saved(user: User, batch):
    from mutagen.id3 import ID3

    await open_find(user, "Band", "Group")
    await click(user, "Apply to 2")
    await click(user, "Save")
    await user.should_see("Saved 2 file(s)")
    assert [ID3(p)["TPE1"].text for p in batch] == [["Group"], ["Group"]]


async def test_transforms_skip_unreadable_files(user: User, music_root, monkeypatch):
    from uihelpers import open_folder, select

    rock = music_root / "rock"
    (rock / "bad.mp3").write_bytes(b"junk")
    await open_folder(user, music_root, "rock")
    await select(user, monkeypatch, rock / "a.mp3", rock / "bad.mp3")
    await open_case(user, "upper")
    assert {r["file"] for r in table_rows(user)} == {"a.mp3"}
