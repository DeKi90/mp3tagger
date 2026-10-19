from pathlib import Path

import pytest

from mp3tagger.core.models import TagSet
from mp3tagger.core.patterns import PatternError
from mp3tagger.core.rename import RenameError, RenamePlan, apply_renames, plan_renames


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
    with pytest.raises(PatternError, match="cannot contain"):
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
