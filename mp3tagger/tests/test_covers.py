from pathlib import Path

import pytest
from mutagen.id3 import APIC, ID3, ID3NoHeaderError

from imagery import jpeg, png
from mp3tagger.core.batch import merge_covers
from mp3tagger.core.editing import EditBuffer
from mp3tagger.core.models import UNCHANGED, CoverArt, TagSet, Track
from mp3tagger.core.tagio.base import SaveOptions
from mp3tagger.core.tagio.id3 import Id3Reader, Id3Writer

PNG = CoverArt(png(3, 2), "image/png")
JPG = CoverArt(jpeg(), "image/jpeg")


def write(path, cover, **options):
    Id3Writer().write(path, {}, SaveOptions(**options), cover)


def add_picture(path, *, type_, desc, data=b"x", mime="image/png"):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(APIC(encoding=3, mime=mime, type=type_, desc=desc, data=data))
    tags.save(path, v2_version=3)


# --- reader / writer -------------------------------------------------------------------------


def test_read_cover_without_tag_or_picture_is_none(make_mp3, tmp_path):
    assert Id3Reader().read_cover(make_mp3(tmp_path / "a.mp3")) is None
    assert Id3Reader().read_cover(make_mp3(tmp_path / "b.mp3", title="T")) is None


def test_add_cover_to_file_without_tag(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    write(path, PNG)
    assert Id3Reader().read_cover(path) == PNG
    assert Id3Reader().read(path).has_cover
    assert ID3(path).getall("APIC")[0].type == 3  # stored as front cover


def test_replace_cover_keeps_a_single_picture(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", cover="x")
    write(path, JPG)
    assert len(ID3(path).getall("APIC")) == 1
    assert Id3Reader().read_cover(path) == JPG


def test_remove_cover(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T", cover="x")
    write(path, None)
    assert Id3Reader().read_cover(path) is None
    assert not Id3Reader().read(path).has_cover
    assert Id3Reader().read(path).tags.title == "T"


def test_unchanged_cover_is_left_alone(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", cover="x")
    Id3Writer().write(path, {"title": "New"}, SaveOptions(), UNCHANGED)
    assert Id3Reader().read(path).has_cover


def test_front_cover_is_preferred_and_other_pictures_survive(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    add_picture(path, type_=4, desc="back", data=b"BACK")
    add_picture(path, type_=3, desc="front", data=png(1, 1))
    assert Id3Reader().read_cover(path).data == png(1, 1)
    write(path, JPG)  # replaces the front cover only
    assert Id3Reader().read_cover(path) == JPG
    assert [f.data for f in ID3(path).getall("APIC") if f.type == 4] == [b"BACK"]
    write(path, None)  # removes the displayed (front) one; the back picture remains
    assert [f.type for f in ID3(path).getall("APIC")] == [4]
    assert Id3Reader().read_cover(path).data == b"BACK"  # now it is the displayed picture


def test_new_cover_does_not_overwrite_a_picture_with_the_same_description(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    add_picture(path, type_=4, desc="", data=b"BACK")
    add_picture(path, type_=3, desc="front", data=png(1, 1))
    write(path, PNG)
    assert sorted(f.data for f in ID3(path).getall("APIC")) == sorted([b"BACK", PNG.data])


def test_cover_survives_version_change_and_tag_edits(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    write(path, PNG, version=4)
    Id3Writer().write(path, {"title": "T"}, SaveOptions(version=3))
    assert Id3Reader().read_cover(path) == PNG


def test_unsupported_cover_type_is_rejected_and_file_untouched(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Unsupported"):
        write(path, CoverArt(b"GIF89a", "image/gif"))
    assert path.read_bytes() == before


# --- edit buffer -----------------------------------------------------------------------------

A, B = Path("/m/a.mp3"), Path("/m/b.mp3")


def buffer():
    buf = EditBuffer()
    buf.load([Track(A, TagSet(title="A"), has_cover=True), Track(B, TagSet(title="B"))])
    return buf


def test_cover_change_makes_track_dirty_and_updates_effective_has_cover():
    buf = buffer()
    assert buf.set_cover([A, B], PNG) == [A, B]
    assert buf.dirty_paths() == [A, B]
    assert buf.pending_cover(A) == PNG
    assert buf.effective_has_cover(B) and buf.pending_edit(B).cover == PNG
    assert not buf.track(B).has_cover  # disk state untouched


def test_removing_cover_only_counts_where_there_is_one():
    buf = buffer()
    assert buf.set_cover([A, B], None) == [A]  # B has no cover: nothing to remove
    assert buf.pending_cover(A) is None and buf.pending_cover(B) is UNCHANGED
    assert not buf.effective_has_cover(A)


def test_adding_then_removing_cover_on_coverless_track_is_no_change():
    buf = buffer()
    buf.set_cover([B], PNG)
    buf.set_cover([B], None)
    assert not buf.is_dirty(B) and buf.pending_cover(B) is UNCHANGED


def test_setting_the_same_cover_twice_is_a_noop():
    buf = buffer()
    buf.set_cover([A], PNG)
    assert buf.set_cover([A], PNG) == []


def test_cover_and_field_edits_undo_independently():
    buf = buffer()
    buf.set_field([A], "title", "New")
    buf.set_cover([A], PNG)
    buf.undo()  # the cover
    assert buf.pending_cover(A) is UNCHANGED and buf.pending(A) == {"title": "New"}
    buf.undo()  # the title
    assert not buf.is_dirty(A)


def test_undo_restores_a_replaced_cover():
    buf = buffer()
    buf.set_cover([A], PNG)
    buf.set_cover([A], JPG)
    buf.undo()
    assert buf.pending_cover(A) == PNG


def test_cover_edit_ends_the_typing_coalescing():
    buf = buffer()
    buf.set_field([A], "title", "N")
    buf.set_cover([A], PNG)
    buf.set_field([A], "title", "Ne")  # a new undo step, not merged into the earlier one
    buf.undo()
    assert buf.pending(A) == {"title": "N"} and buf.pending_cover(A) == PNG


def test_discard_and_apply_saved_clear_cover_changes():
    buf = buffer()
    buf.set_cover([A, B], PNG)
    assert buf.discard([A]) == [A]
    assert buf.pending_cover(A) is UNCHANGED and buf.pending_cover(B) == PNG
    buf.apply_saved([Track(B, TagSet(title="B"), has_cover=True)])
    assert not buf.is_dirty(B) and buf.effective_has_cover(B)


# --- merging ---------------------------------------------------------------------------------


def test_merge_covers():
    from mp3tagger.core.batch import ShownCover

    png_, jpg_ = ShownCover(PNG), ShownCover(JPG)
    assert merge_covers([None, None]).state == "none"
    merged = merge_covers([png_, png_])
    assert (merged.state, merged.cover) == ("single", PNG)
    assert merge_covers([png_, jpg_]).state == "mixed"
    assert merge_covers([png_, None]).state == "mixed"
    assert merge_covers([png_]).state == "single"


def test_embedded_and_folder_versions_of_the_same_picture_are_not_merged():
    from mp3tagger.core.batch import ShownCover

    embedded, from_folder = ShownCover(PNG), ShownCover(PNG, "cover.png")
    assert merge_covers([embedded, from_folder]).state == "mixed"
    merged = merge_covers([from_folder, ShownCover(PNG, "cover.png")])
    assert (merged.state, merged.shown.folder_file) == ("single", "cover.png")


# --- moving the cover into the album folder --------------------------------------------------


def test_move_cover_is_pending_and_counts_as_removed_from_the_file():
    from mp3tagger.core.models import MoveCoverToFolder

    buf = buffer()
    move = MoveCoverToFolder(PNG, "cover.png")
    assert buf.set_cover([A], move) == [A]
    assert buf.is_dirty(A) and not buf.effective_has_cover(A)
    assert buf.pending_cover(A) == move
    assert buf.track(A).has_cover  # the file on disk is untouched until saved
    buf.undo()
    assert not buf.is_dirty(A) and buf.effective_has_cover(A)


def test_writer_refuses_an_unresolved_move(make_mp3, tmp_path):
    from mp3tagger.core.models import MoveCoverToFolder

    path = make_mp3(tmp_path / "a.mp3", cover="x")
    with pytest.raises(ValueError, match="resolved before"):
        write(path, MoveCoverToFolder(PNG, "cover.png"))
