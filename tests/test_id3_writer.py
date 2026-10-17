import pytest
from mutagen.id3 import COMM, ID3, PRIV, TBPM, TXXX

from mp3tagger.core.models import FIELD_NAMES, TagSet
from mp3tagger.core.tagio.base import SaveOptions
from mp3tagger.core.tagio.id3 import Id3Reader, Id3Writer

ALL = {
    "title": "Süße Träume – Ünï",
    "artist": "Artist One",
    "album": "Album",
    "album_artist": "Various",
    "year": "2024",
    "track": "3/12",
    "disc": "1/2",
    "genre": "Rock",
    "comment": "häi",
    "composer": "Bach",
}


def write(path, changes, **options):
    Id3Writer().write(path, changes, SaveOptions(**options))
    return Id3Reader().read(path)


@pytest.mark.parametrize("version", [3, 4])
def test_round_trip_all_fields_in_both_versions(make_mp3, tmp_path, version):
    assert set(ALL) == set(FIELD_NAMES)
    path = make_mp3(tmp_path / "a.mp3")
    track = write(path, ALL, version=version)
    assert track.tags == TagSet(**ALL)
    assert track.tag_version == f"ID3v2.{version}"


def test_new_file_defaults_to_v23(make_mp3, tmp_path):
    track = write(make_mp3(tmp_path / "a.mp3"), {"title": "T"})
    assert track.tag_version == "ID3v2.3"


def test_keeps_existing_version_when_unspecified(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    write(path, {"title": "T"}, version=4)
    assert write(path, {"artist": "A"}).tag_version == "ID3v2.4"


@pytest.mark.parametrize(("start", "target"), [(3, 4), (4, 3)])
def test_converts_between_versions_keeping_content(make_mp3, tmp_path, start, target):
    path = make_mp3(tmp_path / "a.mp3")
    write(path, ALL, version=start)
    track = write(path, {}, version=target)
    assert track.tag_version == f"ID3v2.{target}"
    assert track.tags == TagSet(**ALL)


def test_only_changed_fields_are_touched(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="Old", artist="Keep", year="1999")
    track = write(path, {"title": "New"})
    assert (track.tags.title, track.tags.artist, track.tags.year) == ("New", "Keep", "1999")


def test_empty_value_removes_frame(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T", artist="A", comment="c", year="2000")
    track = write(path, {"artist": "", "comment": "", "year": ""})
    assert track.tags == TagSet(title="T")
    assert not ID3(path).getall("TPE1")
    assert not ID3(path).getall("COMM")


def test_unknown_frames_and_cover_survive(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T", cover="x")
    tags = ID3(path)
    tags.add(TBPM(encoding=3, text="128"))
    tags.add(TXXX(encoding=3, desc="MY", text="custom"))
    tags.add(PRIV(owner="me@x", data=b"\x01\x02"))
    tags.save(path, v2_version=3)
    track = write(path, {"title": "New"})
    after = ID3(path)
    assert after["TBPM"].text == ["128"]
    assert after["TXXX:MY"].text == ["custom"]
    assert [f.data for f in after.getall("PRIV")] == [b"\x01\x02"]
    assert track.has_cover


def test_other_comment_frames_are_left_alone(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", comment="visible")
    tags = ID3(path)
    tags.add(COMM(encoding=3, lang="eng", desc="iTunNORM", text="0000 1111"))
    tags.save(path, v2_version=3)
    track = write(path, {"comment": "changed"})
    assert track.tags.comment == "changed"
    assert ID3(path)["COMM:iTunNORM:eng"].text == ["0000 1111"]


def test_comment_prefers_undescribed_frame_over_tool_data(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    tags = ID3()
    tags.add(COMM(encoding=3, lang="eng", desc="iTunNORM", text="0000 1111"))
    tags.add(COMM(encoding=3, lang="eng", desc="", text="real comment"))
    tags.save(path, v2_version=3)
    assert Id3Reader().read(path).tags.comment == "real comment"


def test_multiple_values_round_trip(make_mp3, tmp_path):
    track = write(make_mp3(tmp_path / "a.mp3"), {"artist": "One; Two"}, version=4)
    assert track.tags.artist == "One; Two"
    assert ID3(tmp_path / "a.mp3")["TPE1"].text == ["One", "Two"]


def test_id3v1_written_only_on_request(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    write(path, {"title": "T"})
    assert path.read_bytes()[-128:-125] != b"TAG"
    write(path, {"title": "T2"}, write_v1=True)
    trailer = path.read_bytes()[-128:]
    assert trailer[:3] == b"TAG" and trailer[3:5] == b"T2"


def test_existing_id3v1_is_updated_even_without_option(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    write(path, {"title": "Old"}, write_v1=True)
    write(path, {"title": "New"})
    assert path.read_bytes()[-128:][3:6] == b"New"


def test_v1_only_file_gets_v2_tag_with_content_preserved(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    pad = lambda text, n: text.ljust(n, b"\0")  # noqa: E731
    path.write_bytes(
        path.read_bytes()
        + b"TAG" + pad(b"Old", 30) + pad(b"Art", 30) + pad(b"Alb", 30)
        + b"1999" + pad(b"", 28) + b"\0" + bytes([7, 17])
    )  # fmt: skip
    track = write(path, {"title": "New"})
    assert track.tag_version == "ID3v2.3"
    assert (track.tags.title, track.tags.artist, track.tags.year) == ("New", "Art", "1999")


@pytest.mark.parametrize("year", ["abcd", "99", "2024-13", "2024-00", "2024-05-32", "2024/05/01"])
def test_invalid_year_rejected_and_file_untouched(make_mp3, tmp_path, year):
    path = make_mp3(tmp_path / "a.mp3", title="T")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Invalid year"):
        Id3Writer().write(path, {"title": "X", "year": year}, SaveOptions())
    assert path.read_bytes() == before


@pytest.mark.parametrize("year", ["2024", "2024-05", "2024-05-01"])
def test_valid_year_forms(make_mp3, tmp_path, year):
    assert write(make_mp3(tmp_path / "a.mp3"), {"year": year}).tags.year == "2024"


def test_unknown_field_rejected(make_mp3, tmp_path):
    with pytest.raises(ValueError, match="bogus"):
        Id3Writer().write(make_mp3(tmp_path / "a.mp3"), {"bogus": "x"}, SaveOptions())


def test_audio_data_unchanged(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3", frames=60, title="T")
    before = Id3Reader().read(path).info
    write(path, {"title": "A much longer title " * 20, "comment": "x" * 500})
    after = Id3Reader().read(path).info
    assert (after.duration, after.bitrate, after.sample_rate) == (
        before.duration,
        before.bitrate,
        before.sample_rate,
    )
