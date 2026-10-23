from pathlib import Path

import pytest

from mp3tagger.core.models import TagSet
from mp3tagger.core.patterns import PatternError
from mp3tagger.core.rename import (
    RenameError,
    RenamePlan,
    apply_renames,
    plan_renames,
    remove_empty_folders,
)


def touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def plan(items, pattern="%artist% - %title%"):
    return plan_renames(items, pattern)


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# --- planning --------------------------------------------------------------------------------


def test_plan_builds_new_names_and_keeps_folder_and_extension(tmp_path):
    a = touch(tmp_path / "x" / "old.MP3")
    (result,) = plan([(a, TagSet(artist="Band", title="Song"))])
    assert (result.status, result.target) == ("rename", tmp_path / "x" / "Band - Song.MP3")
    assert a.exists()  # planning never touches disk


def test_plan_marks_files_that_already_have_the_name_as_unchanged(tmp_path):
    a = touch(tmp_path / "Band - Song.mp3")
    (result,) = plan([(a, TagSet(artist="Band", title="Song"))])
    assert result.status == "unchanged" and result.target == a


def test_plan_reports_empty_fields_as_a_hint(tmp_path):
    a = touch(tmp_path / "a.mp3")
    (result,) = plan([(a, TagSet(title="Song"))])
    assert result.status == "rename" and result.message == "empty: artist"
    assert result.target.name == " - Song.mp3".strip()  # leading space trimmed


def test_plan_reports_unbuildable_names_per_file(tmp_path):
    a, b = touch(tmp_path / "a.mp3"), touch(tmp_path / "b.mp3")
    first, second = plan([(a, TagSet()), (b, TagSet(title="ok"))], "%title%")
    assert first.status == "error" and "empty" in first.message and first.target is None
    assert second.status == "rename"


def test_plan_raises_for_an_invalid_pattern(tmp_path):
    with pytest.raises(PatternError):
        plan([(touch(tmp_path / "a.mp3"), TagSet())], "%nope%")
    with pytest.raises(PatternError, match=r"cannot be \. or \.\."):
        plan([(touch(tmp_path / "a.mp3"), TagSet())], "../%title%")


def test_plan_flags_two_files_getting_the_same_name(tmp_path):
    a, b = touch(tmp_path / "a.mp3"), touch(tmp_path / "b.mp3")
    tags = TagSet(artist="X", title="Y")
    results = plan([(a, tags), (b, tags)])
    assert [r.status for r in results] == ["error", "error"]
    assert all("Same name" in r.message for r in results)


def test_plan_treats_names_differing_only_in_case_as_the_same(tmp_path):
    a, b = touch(tmp_path / "a.mp3"), touch(tmp_path / "b.mp3")
    results = plan([(a, TagSet(title="Song")), (b, TagSet(title="SONG"))], "%title%")
    assert [r.status for r in results] == ["error", "error"]


def test_same_name_in_different_folders_is_fine(tmp_path):
    a, b = touch(tmp_path / "one" / "a.mp3"), touch(tmp_path / "two" / "b.mp3")
    results = plan([(a, TagSet(title="S")), (b, TagSet(title="S"))], "%title%")
    assert [r.status for r in results] == ["rename", "rename"]


def test_plan_flags_a_name_taken_by_a_file_that_is_not_part_of_the_batch(tmp_path):
    a = touch(tmp_path / "a.mp3")
    touch(tmp_path / "Taken.mp3")
    (result,) = plan([(a, TagSet(title="Taken"))], "%title%")
    assert result.status == "error" and "exists" in result.message


def test_plan_allows_a_name_that_another_renamed_file_gives_up(tmp_path):
    a, b = touch(tmp_path / "a.mp3"), touch(tmp_path / "b.mp3")
    results = plan([(a, TagSet(title="b")), (b, TagSet(title="c"))], "%title%")  # a->b, b->c
    assert [r.status for r in results] == ["rename", "rename"]


def test_plan_allows_swapping_names(tmp_path):
    a, b = touch(tmp_path / "a.mp3"), touch(tmp_path / "b.mp3")
    results = plan([(a, TagSet(title="b")), (b, TagSet(title="a"))], "%title%")
    assert [r.status for r in results] == ["rename", "rename"]


def test_plan_allows_a_case_only_change(tmp_path):
    a = touch(tmp_path / "song.mp3")
    (result,) = plan([(a, TagSet(title="Song"))], "%title%")
    assert (result.status, result.target.name) == ("rename", "Song.mp3")


def test_unchanged_file_still_blocks_a_name(tmp_path):
    a, b = touch(tmp_path / "Y.mp3"), touch(tmp_path / "b.mp3")
    keep, move = plan([(a, TagSet(title="Y")), (b, TagSet(title="Y"))], "%title%")
    assert keep.status == "unchanged" and move.status == "error"


# --- executing -------------------------------------------------------------------------------


def run(items, pattern="%title%"):
    return apply_renames(plan_renames(items, pattern))


def test_apply_renames_files_and_returns_the_mapping(tmp_path):
    a = touch(tmp_path / "a.mp3", b"AAA")
    b = touch(tmp_path / "b.mp3", b"BBB")
    mapping = run([(a, TagSet(title="One")), (b, TagSet(title="Two"))])
    assert mapping == {a: tmp_path / "One.mp3", b: tmp_path / "Two.mp3"}
    assert names(tmp_path) == ["One.mp3", "Two.mp3"]
    assert (tmp_path / "One.mp3").read_bytes() == b"AAA"


def test_apply_handles_swaps_and_chains(tmp_path):
    a, b, c = (touch(tmp_path / f"{n}.mp3", n.encode()) for n in "abc")
    run([(a, TagSet(title="b")), (b, TagSet(title="a")), (c, TagSet(title="c"))])  # swap a/b
    assert (tmp_path / "a.mp3").read_bytes() == b"b" and (tmp_path / "b.mp3").read_bytes() == b"a"
    assert names(tmp_path) == ["a.mp3", "b.mp3", "c.mp3"]
    x, y = touch(tmp_path / "x.mp3", b"x"), touch(tmp_path / "y.mp3", b"y")
    run([(x, TagSet(title="y")), (y, TagSet(title="z"))])  # chain x->y, y->z
    assert (tmp_path / "y.mp3").read_bytes() == b"x" and (tmp_path / "z.mp3").read_bytes() == b"y"


def test_apply_case_only_change(tmp_path):
    a = touch(tmp_path / "song.mp3", b"S")
    run([(a, TagSet(title="Song"))])
    assert names(tmp_path) == ["Song.mp3"]


def test_apply_skips_unchanged_and_error_plans(tmp_path):
    a = touch(tmp_path / "Keep.mp3")
    b = touch(tmp_path / "b.mp3")
    mapping = run([(a, TagSet(title="Keep")), (b, TagSet())])  # b cannot be named
    assert mapping == {} and names(tmp_path) == ["Keep.mp3", "b.mp3"]


def test_apply_leaves_no_temporary_files(tmp_path):
    a, b = touch(tmp_path / "a.mp3"), touch(tmp_path / "b.mp3")
    run([(a, TagSet(title="b")), (b, TagSet(title="a"))])
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]


def test_apply_rolls_everything_back_when_a_step_fails(tmp_path):
    a = touch(tmp_path / "a.mp3", b"A")
    b = touch(tmp_path / "b.mp3", b"B")
    plans = plan_renames([(a, TagSet(title="One")), (b, TagSet(title="Two"))], "%title%")
    touch(tmp_path / "Two.mp3", b"intruder")  # appears after planning
    with pytest.raises(RenameError, match="No files were renamed"):
        apply_renames(plans)
    assert names(tmp_path) == ["Two.mp3", "a.mp3", "b.mp3"]
    assert (tmp_path / "a.mp3").read_bytes() == b"A" and (tmp_path / "b.mp3").read_bytes() == b"B"
    assert (tmp_path / "Two.mp3").read_bytes() == b"intruder"  # never overwritten


def test_apply_reports_a_vanished_source_and_restores_the_rest(tmp_path):
    a = touch(tmp_path / "a.mp3", b"A")
    b = touch(tmp_path / "b.mp3", b"B")
    plans = plan_renames([(a, TagSet(title="One")), (b, TagSet(title="Two"))], "%title%")
    b.unlink()  # gone after planning
    with pytest.raises(RenameError, match="No files were renamed"):
        apply_renames(plans)
    assert names(tmp_path) == ["a.mp3"]


def test_apply_with_nothing_to_do(tmp_path):
    assert apply_renames([RenamePlan(tmp_path / "a.mp3")]) == {}


# --- sorting into folders --------------------------------------------------------------------

TAGS = TagSet(artist="Band", album="LP", track="3", title="Song")
SORT = "%artist%/%album%/%track:2% - %title%"


def sort(items, base: Path, pattern: str = SORT, **kwargs):
    return plan_renames(items, pattern, base, **kwargs)


def test_folders_are_created_below_the_open_folder_not_below_the_files_folder(tmp_path):
    base = tmp_path / "library"
    file = touch(base / "inbox" / "new" / "a.mp3")
    (result,) = sort([(file, TAGS)], base)
    assert result.status == "rename"
    assert result.target == base / "Band" / "LP" / "03 - Song.mp3"
    assert not (base / "Band").exists()  # planning creates nothing


def test_a_pattern_without_folders_keeps_the_file_where_it_is(tmp_path):
    base = tmp_path / "library"
    file = touch(base / "inbox" / "a.mp3")
    (result,) = plan_renames([(file, TAGS)], "%track:2% - %title%", base)
    assert result.target == base / "inbox" / "03 - Song.mp3"


def test_a_file_already_in_the_right_place_is_unchanged(tmp_path):
    base = tmp_path / "library"
    file = touch(base / "Band" / "LP" / "03 - Song.mp3")
    (result,) = sort([(file, TAGS)], base)
    assert result.status == "unchanged"


def test_folder_patterns_need_a_base_folder(tmp_path):
    with pytest.raises(PatternError, match="Open a folder first"):
        plan_renames([(touch(tmp_path / "a.mp3"), TAGS)], SORT)
    (result,) = plan_renames([(touch(tmp_path / "b.mp3"), TAGS)], "%title%")  # in place: fine
    assert result.status == "rename"


def test_a_missing_tag_for_a_folder_is_a_problem_of_that_file_only(tmp_path):
    base = tmp_path / "lib"
    ok, missing = touch(base / "a.mp3"), touch(base / "b.mp3")
    plans = sort([(ok, TAGS), (missing, TagSet(artist="Band", title="T", track="1"))], base)
    assert plans[0].status == "rename"
    assert plans[1].status == "error" and "folder name would be empty" in plans[1].message


def test_two_files_that_would_land_on_the_same_path_are_both_flagged(tmp_path):
    base = tmp_path / "lib"
    a, b = touch(base / "x" / "a.mp3"), touch(base / "y" / "a.mp3")
    plans = sort([(a, TAGS), (b, TAGS)], base)
    assert [p.status for p in plans] == ["error", "error"]


def test_the_same_name_in_different_new_folders_is_fine(tmp_path):
    base = tmp_path / "lib"
    a, b = touch(base / "a.mp3"), touch(base / "b.mp3")
    plans = sort([(a, TAGS), (b, replace_tags(TAGS, album="Other"))], base)
    assert [p.status for p in plans] == ["rename", "rename"]


def replace_tags(tags: TagSet, **changes) -> TagSet:
    from dataclasses import replace

    return replace(tags, **changes)


def test_a_file_where_a_folder_should_go_is_reported(tmp_path):
    base = tmp_path / "lib"
    file = touch(base / "a.mp3")
    touch(base / "Band")  # a FILE called Band
    (result,) = sort([(file, TAGS)], base)
    assert result.status == "error" and "Band is a file, not a folder" in result.message


def test_a_file_in_the_way_deeper_down_is_found_too(tmp_path):
    base = tmp_path / "lib"
    file = touch(base / "a.mp3")
    touch(base / "Band" / "LP")  # Band is a folder, LP a file
    (result,) = sort([(file, TAGS)], base)
    assert result.status == "error" and "LP is a file" in result.message


def test_the_allowed_check_can_forbid_folders(tmp_path):
    base = tmp_path / "lib"
    file = touch(base / "a.mp3")
    (result,) = sort([(file, TAGS)], base, allowed=lambda folder: False)
    assert result.status == "error" and "outside the music folders" in result.message
    seen = []
    sort([(file, TAGS)], base, allowed=lambda folder: seen.append(folder) or True)
    assert seen == [base / "Band" / "LP"]


def test_an_existing_file_at_the_new_path_is_not_overwritten(tmp_path):
    base = tmp_path / "lib"
    file = touch(base / "a.mp3")
    touch(base / "Band" / "LP" / "03 - Song.mp3")
    (result,) = sort([(file, TAGS)], base)
    assert result.status == "error" and "exists" in result.message


def test_overlong_paths_are_refused(tmp_path):
    base = tmp_path / "lib"
    file = touch(base / "a.mp3")
    big = "x" * 250  # each level is fine on its own (255 bytes at most) but five add up
    long = TagSet(artist=big, album=big, title=big, comment=big, composer=big)
    pattern = "%artist%/%album%/%title%/%comment%/%composer%"
    (result,) = sort([(file, long)], base, pattern)
    assert result.status == "error" and "too long" in result.message


def test_apply_creates_the_folders_and_moves_the_files(tmp_path):
    base = tmp_path / "lib"
    a = touch(base / "inbox" / "a.mp3", b"A")
    b = touch(base / "inbox" / "b.mp3", b"B")
    items = [(a, TAGS), (b, replace_tags(TAGS, track="4", title="Other"))]
    mapping = apply_renames(sort(items, base))
    assert mapping == {
        a: base / "Band" / "LP" / "03 - Song.mp3",
        b: base / "Band" / "LP" / "04 - Other.mp3",
    }
    assert (base / "Band" / "LP" / "03 - Song.mp3").read_bytes() == b"A"
    assert names(base / "inbox") == []  # nothing left behind, not even temporary files


def test_apply_works_when_the_new_folder_already_exists(tmp_path):
    base = tmp_path / "lib"
    (base / "Band" / "LP").mkdir(parents=True)
    a = touch(base / "a.mp3", b"A")
    apply_renames(sort([(a, TAGS)], base))
    assert (base / "Band" / "LP" / "03 - Song.mp3").read_bytes() == b"A"


def test_a_failure_rolls_back_moves_and_removes_the_folders_it_created(tmp_path):
    base = tmp_path / "lib"
    a = touch(base / "a.mp3", b"A")
    b = touch(base / "b.mp3", b"B")
    second = replace_tags(TAGS, album="Second", title="Other")
    plans = sort([(a, TAGS), (b, second)], base)
    touch(base / "Band" / "Second" / "03 - Other.mp3", b"intruder")  # blocks the second move
    # (the intruder's folders existed before; the first file's folder is created by the call)
    with pytest.raises(RenameError, match="No files were renamed"):
        apply_renames(plans)
    assert (base / "a.mp3").read_bytes() == b"A" and (base / "b.mp3").read_bytes() == b"B"
    assert not (base / "Band" / "LP").exists()  # created during the attempt, removed again
    assert (base / "Band" / "Second" / "03 - Other.mp3").read_bytes() == b"intruder"


# --- removing the folders that were emptied --------------------------------------------------


def test_emptied_folders_are_removed_up_to_but_not_including_the_root(tmp_path):
    root = tmp_path / "lib"
    deep = root / "old" / "album"
    deep.mkdir(parents=True)
    assert remove_empty_folders([deep], root) == [deep, root / "old"]
    assert root.exists() and not (root / "old").exists()


def test_a_folder_that_still_holds_something_is_kept_with_its_parents(tmp_path):
    root = tmp_path / "lib"
    keep = touch(root / "old" / "album" / "cover.jpg")
    (root / "old" / "empty").mkdir()
    removed = remove_empty_folders([keep.parent, root / "old" / "empty"], root)
    assert removed == [root / "old" / "empty"]
    assert keep.exists() and (root / "old").exists()


def test_finder_leftovers_do_not_keep_a_folder_alive_but_real_files_do(tmp_path):
    root = tmp_path / "lib"
    touch(root / "a" / ".DS_Store")
    touch(root / "b" / ".DS_Store")
    touch(root / "b" / "notes.txt")
    removed = remove_empty_folders([root / "a", root / "b"], root)
    assert removed == [root / "a"]
    assert (root / "b" / "notes.txt").exists() and (root / "b" / ".DS_Store").exists()


def test_the_root_and_anything_outside_it_are_never_touched(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert remove_empty_folders([root, outside], root) == []
    assert root.exists() and outside.exists()


def test_a_folder_with_a_subfolder_is_not_empty(tmp_path):
    root = tmp_path / "lib"
    (root / "a" / "b").mkdir(parents=True)
    assert remove_empty_folders([root / "a"], root) == []
    assert (root / "a" / "b").exists()


def test_folders_that_are_already_gone_are_skipped(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    assert remove_empty_folders([root / "never-existed"], root) == []
