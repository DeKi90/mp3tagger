from mp3tagger.core.saving import write_changes
from mp3tagger.core.tagio.base import SaveOptions
from mp3tagger.core.tagio.id3 import Id3Reader, Id3Writer


def test_writes_and_rereads_every_file(make_mp3, tmp_path):
    a = make_mp3(tmp_path / "a.mp3", title="A")
    b = make_mp3(tmp_path / "b.mp3", title="B")
    results = write_changes(
        {a: {"title": "A2"}, b: {"artist": "Art"}}, Id3Writer(), Id3Reader(), SaveOptions()
    )
    assert [r.error for r in results] == [None, None]
    assert results[0].track.tags.title == "A2"
    assert (results[1].track.tags.title, results[1].track.tags.artist) == ("B", "Art")


def test_one_failure_does_not_stop_the_others(make_mp3, tmp_path):
    good = make_mp3(tmp_path / "good.mp3")
    missing = tmp_path / "missing.mp3"
    bad_year = make_mp3(tmp_path / "bad.mp3")
    results = write_changes(
        {missing: {"title": "x"}, bad_year: {"year": "nope"}, good: {"title": "ok"}},
        Id3Writer(),
        Id3Reader(),
    )
    by_name = {r.path.name: r for r in results}
    assert by_name["missing.mp3"].error and by_name["missing.mp3"].track is None
    assert "Invalid year" in by_name["bad.mp3"].error
    assert by_name["good.mp3"].error is None
    assert by_name["good.mp3"].track.tags.title == "ok"
