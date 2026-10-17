from mp3tagger.core.models import TagSet
from mp3tagger.core.tagio.id3 import Id3Reader


def test_reads_all_standard_fields(make_mp3, tmp_path):
    path = make_mp3(
        tmp_path / "a.mp3",
        title="Song", artist="Artist", album="Album", album_artist="Various",
        year="2024", track="3/12", disc="1/2", genre="Rock", comment="hi", composer="Bach",
        cover="x",
    )  # fmt: skip
    track = Id3Reader().read(path)
    assert track.error is None
    assert track.tags == TagSet(
        title="Song", artist="Artist", album="Album", album_artist="Various",
        year="2024", track="3/12", disc="1/2", genre="Rock", comment="hi", composer="Bach",
    )  # fmt: skip
    assert track.tag_version == "ID3v2.3"
    assert track.has_cover


def test_year_is_truncated_from_full_timestamp(make_mp3, tmp_path):
    track = Id3Reader().read(make_mp3(tmp_path / "a.mp3", year="2024-05-01"))
    assert track.tags.year == "2024"


def test_audio_info(make_mp3, tmp_path):
    track = Id3Reader().read(make_mp3(tmp_path / "a.mp3", frames=100))
    assert track.info.bitrate == 128_000
    assert track.info.sample_rate == 44_100
    assert track.info.channels == 2
    assert 2.5 < track.info.duration < 2.7
    assert track.info.size == (tmp_path / "a.mp3").stat().st_size


def test_file_without_tag(make_mp3, tmp_path):
    track = Id3Reader().read(make_mp3(tmp_path / "a.mp3"))
    assert track.error is None
    assert track.tags == TagSet()
    assert track.tag_version == ""
    assert not track.has_cover


def test_id3v1_only(make_mp3, tmp_path):
    path = make_mp3(tmp_path / "a.mp3")
    pad = lambda text, n: text.ljust(n, b"\0")  # noqa: E731
    trailer = (
        b"TAG" + pad(b"Old Title", 30) + pad(b"Old Artist", 30) + pad(b"Old Album", 30)
        + b"1999" + pad(b"note", 28) + b"\0" + bytes([7, 17])
    )  # fmt: skip
    path.write_bytes(path.read_bytes() + trailer)
    track = Id3Reader().read(path)
    assert track.tag_version == "ID3v1.1"
    assert (track.tags.title, track.tags.artist, track.tags.album) == (
        "Old Title", "Old Artist", "Old Album",
    )  # fmt: skip
    assert (track.tags.year, track.tags.track, track.tags.genre) == ("1999", "7", "Rock")


def test_unreadable_file_is_reported_not_raised(tmp_path):
    path = tmp_path / "broken.mp3"
    path.write_bytes(b"not an mp3")
    track = Id3Reader().read(path)
    assert track.error
    assert track.path == path
