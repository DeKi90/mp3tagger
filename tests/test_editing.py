from pathlib import Path

import pytest

from mp3tagger.core.editing import EditBuffer
from mp3tagger.core.models import UNCHANGED, TagSet, Track

A, B = Path("/m/a.mp3"), Path("/m/b.mp3")


@pytest.fixture
def buf():
    buffer = EditBuffer()
    buffer.load(
        [
            Track(A, TagSet(title="Alpha", artist="X")),
            Track(B, TagSet(title="Beta", artist="X")),
        ]
    )
    return buffer


def test_edit_marks_dirty_and_shows_effective_value(buf):
    assert buf.set_field([A], "title", "New") == [A]
    assert buf.is_dirty(A) and not buf.is_dirty(B)
    assert buf.effective_tags(A).title == "New"
    assert buf.track(A).tags.title == "Alpha"  # original untouched
    assert buf.dirty_paths() == [A]


def test_setting_same_value_is_a_noop(buf):
    assert buf.set_field([A, B], "artist", "X") == []
    assert not buf.can_undo


def test_editing_back_to_original_clears_dirty(buf):
    buf.set_field([A], "title", "New")
    buf.set_field([A], "title", "Alpha")
    assert not buf.is_dirty(A)
    assert buf.pending(A) == {}


def test_unknown_field_rejected(buf):
    with pytest.raises(KeyError):
        buf.set_field([A], "bogus", "x")


def test_batch_edit_only_reports_changed_paths(buf):
    assert buf.set_field([A, B], "title", "Beta") == [A]


def test_typing_is_coalesced_into_one_undo_step(buf):
    for text in ("N", "Ne", "New"):
        buf.set_field([A], "title", text)
    assert buf.undo() == [A]
    assert buf.effective_tags(A).title == "Alpha"
    assert not buf.can_undo


def test_different_fields_are_separate_undo_steps(buf):
    buf.set_field([A], "title", "T")
    buf.set_field([A], "artist", "Y")
    buf.undo()
    assert buf.pending(A) == {"title": "T"}
    buf.undo()
    assert not buf.is_dirty(A)


def test_break_edit_starts_new_undo_step(buf):
    buf.set_field([A], "title", "T1")
    buf.break_edit()
    buf.set_field([A], "title", "T2")
    buf.undo()
    assert buf.effective_tags(A).title == "T1"


def test_undo_batch_edit_restores_every_track(buf):
    buf.set_field([A, B], "artist", "Z")
    assert set(buf.undo()) == {A, B}
    assert buf.dirty_paths() == []


def test_undo_with_nothing_to_undo(buf):
    assert buf.undo() == []


def test_discard_selected_and_all(buf):
    buf.set_field([A], "title", "1")
    buf.set_field([B], "title", "2")
    assert buf.discard([A]) == [A]
    assert buf.dirty_paths() == [B]
    assert not buf.can_undo  # snapshots would be stale
    assert buf.discard() == [B]
    assert buf.dirty_paths() == []


def test_apply_saved_replaces_track_and_clears_pending(buf):
    buf.set_field([A], "title", "New")
    buf.set_field([B], "title", "Other")
    buf.apply_saved([Track(A, TagSet(title="New", artist="X"))])
    assert not buf.is_dirty(A)
    assert buf.track(A).tags.title == "New"
    assert buf.is_dirty(B)
    assert not buf.can_undo


def test_load_resets_everything(buf):
    buf.set_field([A], "title", "New")
    buf.load([Track(B, TagSet())])
    assert buf.paths == [B]
    assert buf.dirty_paths() == [] and not buf.can_undo


def test_undo_open_edit_only_for_the_edited_field(buf):
    buf.set_field([A, B], "artist", "Z")
    assert buf.undo_open_edit("title") == []  # a different field is not the open edit
    assert buf.dirty_paths() == [A, B]
    assert set(buf.undo_open_edit("artist")) == {A, B}
    assert buf.dirty_paths() == []


def test_undo_open_edit_after_edit_was_broken_does_nothing(buf):
    buf.set_field([A], "title", "T")
    buf.break_edit()
    assert buf.undo_open_edit("title") == []
    assert buf.is_dirty(A)


# --- converters: batch edits and renames -----------------------------------------------------


def test_set_fields_is_one_undo_step_for_many_tracks_and_fields(buf):
    assert buf.set_fields({A: {"title": "T1", "artist": "Y"}, B: {"title": "T2"}}) == [A, B]
    assert buf.pending(A) == {"title": "T1", "artist": "Y"} and buf.pending(B) == {"title": "T2"}
    assert set(buf.undo()) == {A, B}
    assert buf.dirty_paths() == [] and not buf.can_undo


def test_set_fields_skips_unchanged_values_and_tracks(buf):
    assert buf.set_fields({A: {"title": "Alpha"}, B: {"title": "New"}}) == [B]
    assert buf.dirty_paths() == [B]
    assert buf.set_fields({B: {"title": "New"}}) == []  # nothing to do: no undo step either
    assert buf.undo() == [B] and not buf.can_undo


def test_set_fields_rejects_unknown_fields_without_changing_anything(buf):
    with pytest.raises(KeyError):
        buf.set_fields({A: {"title": "x"}, B: {"bogus": "y"}})
    assert buf.dirty_paths() == []


def test_set_fields_does_not_coalesce_with_typing(buf):
    buf.set_field([A], "title", "T")
    buf.set_fields({A: {"title": "Converted"}})
    buf.undo()
    assert buf.pending(A) == {"title": "T"}


def test_rename_paths_moves_everything_with_the_file(buf):
    from mp3tagger.core.models import CoverArt

    cover = CoverArt(b"x", "image/png")
    buf.set_field([A], "title", "Edited")
    buf.set_cover([B], cover)
    new_a, new_b = Path("/m/renamed-a.mp3"), Path("/m/b2.mp3")
    buf.rename_paths({A: new_a, B: new_b})
    assert buf.paths == [new_a, new_b]  # order is kept
    assert buf.track(new_a).path == new_a and buf.track(new_a).filename == "renamed-a.mp3"
    assert buf.pending(new_a) == {"title": "Edited"} and buf.pending_cover(new_b) == cover
    assert buf.dirty_paths() == [new_a, new_b]
    buf.undo()  # the undo history follows the files too
    assert buf.pending_cover(new_b) is UNCHANGED and buf.pending(new_a) == {"title": "Edited"}
    buf.undo()
    assert buf.dirty_paths() == []


def test_rename_paths_keeps_typing_coalesced(buf):
    buf.set_field([A], "title", "T")
    new_a = Path("/m/x.mp3")
    buf.rename_paths({A: new_a})
    buf.set_field([new_a], "title", "Ti")  # still the same edit in progress
    buf.undo()
    assert not buf.is_dirty(new_a)


def test_rename_paths_ignores_unknown_paths(buf):
    buf.rename_paths({Path("/elsewhere.mp3"): Path("/x.mp3")})
    assert buf.paths == [A, B]
