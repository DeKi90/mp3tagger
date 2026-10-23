from imagery import png
from mp3tagger.core.models import CoverArt, Edit
from mp3tagger.core.saving import write_changes
from mp3tagger.core.tagio.base import SaveOptions
from mp3tagger.core.tagio.id3 import Id3Reader, Id3Writer


def test_writes_and_rereads_every_file(make_mp3, tmp_path):
    a = make_mp3(tmp_path / "a.mp3", title="A")
    b = make_mp3(tmp_path / "b.mp3", title="B")
    results = write_changes(
        {a: Edit({"title": "A2"}), b: Edit({"artist": "Art"})},
        Id3Writer(),
        Id3Reader(),
        SaveOptions(),
    )
    assert [r.error for r in results] == [None, None]
    assert results[0].track.tags.title == "A2"
    assert (results[1].track.tags.title, results[1].track.tags.artist) == ("B", "Art")


def test_one_failure_does_not_stop_the_others(make_mp3, tmp_path):
    good = make_mp3(tmp_path / "good.mp3")
    missing = tmp_path / "missing.mp3"
    bad_year = make_mp3(tmp_path / "bad.mp3")
    results = write_changes(
        {
            missing: Edit({"title": "x"}),
            bad_year: Edit({"year": "nope"}),
            good: Edit({"title": "ok"}),
        },
        Id3Writer(),
        Id3Reader(),
    )
    by_name = {r.path.name: r for r in results}
    assert by_name["missing.mp3"].error and by_name["missing.mp3"].track is None
    assert "Invalid year" in by_name["bad.mp3"].error
    assert by_name["good.mp3"].error is None
    assert by_name["good.mp3"].track.tags.title == "ok"


def test_cover_edit_is_written_and_read_back(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T")
    cover = CoverArt(png(), "image/png")
    (result,) = write_changes({path: Edit(cover=cover)}, Id3Writer(), Id3Reader())
    assert result.error is None and result.track.has_cover
    assert Id3Reader().read_cover(path) == cover
    assert result.track.tags.title == "T"


# --- moving the cover into the album folder --------------------------------------------------


def move_edit(cover=None, name="cover.png"):
    from mp3tagger.core.models import MoveCoverToFolder

    return Edit(cover=MoveCoverToFolder(cover or CoverArt(png(3, 2), "image/png"), name))


def save(path, edit):
    return write_changes({path: edit}, Id3Writer(), Id3Reader())[0]


def test_move_writes_the_image_next_to_the_file_and_removes_the_embedded_cover(make_mp3, tmp_path):
    cover = CoverArt(png(3, 2), "image/png")
    path = make_mp3(tmp_path / "album" / "a.mp3", title="T", cover=cover.data)
    result = save(path, move_edit(cover))
    assert result.error is None
    assert (tmp_path / "album" / "cover.png").read_bytes() == cover.data
    assert Id3Reader().read_cover(path) is None
    assert not result.track.has_cover and result.track.tags.title == "T"
    assert [p.name for p in (tmp_path / "album").iterdir()] == sorted(["a.mp3", "cover.png"])


def test_move_keeps_embedded_cover_when_a_different_file_is_in_the_way(make_mp3, tmp_path):
    cover = CoverArt(png(3, 2), "image/png")
    path = make_mp3(tmp_path / "a.mp3", cover=cover.data)
    (tmp_path / "cover.png").write_bytes(b"someone else's image")
    result = save(path, move_edit(cover))
    assert "already exists" in result.error and result.track is None
    assert (tmp_path / "cover.png").read_bytes() == b"someone else's image"
    assert Id3Reader().read_cover(path) == cover  # nothing was lost


def test_move_accepts_an_identical_existing_file(make_mp3, tmp_path):
    cover = CoverArt(png(3, 2), "image/png")
    path = make_mp3(tmp_path / "a.mp3", cover=cover.data)
    (tmp_path / "cover.png").write_bytes(cover.data)
    assert save(path, move_edit(cover)).error is None
    assert Id3Reader().read_cover(path) is None


def test_tracks_of_one_album_share_the_folder_image(make_mp3, tmp_path):
    cover = CoverArt(png(3, 2), "image/png")
    a = make_mp3(tmp_path / "a.mp3", cover=cover.data)
    b = make_mp3(tmp_path / "b.mp3", cover=cover.data)
    results = write_changes({a: move_edit(cover), b: move_edit(cover)}, Id3Writer(), Id3Reader())
    assert [r.error for r in results] == [None, None]
    assert (tmp_path / "cover.png").read_bytes() == cover.data
    assert Id3Reader().read_cover(a) is None and Id3Reader().read_cover(b) is None


def test_move_to_a_missing_folder_fails_cleanly(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", cover="x")
    result = save(path, move_edit(name="sub/cover.png"))  # parent folder does not exist
    assert result.error and Id3Reader().read(path).has_cover


def test_find_folder_cover_conflicts(make_mp3, tmp_path):
    from mp3tagger.core.saving import find_folder_cover_conflicts

    cover = CoverArt(png(3, 2), "image/png")
    free = make_mp3(tmp_path / "free" / "a.mp3")
    same = make_mp3(tmp_path / "same" / "a.mp3")
    other = make_mp3(tmp_path / "other" / "a.mp3")
    (tmp_path / "same" / "cover.png").write_bytes(cover.data)
    (tmp_path / "other" / "cover.png").write_bytes(b"different")
    conflicts = find_folder_cover_conflicts([free, same, other], "cover.png", cover)
    assert list(conflicts) == [other.parent]
    assert "other/cover.png" in conflicts[other.parent]
