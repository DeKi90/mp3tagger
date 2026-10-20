import json
from pathlib import Path

from mp3tagger.core.discid import Toc
from mp3tagger.core.lookup import (
    LocalFile,
    TrackMatch,
    build_changes,
    lengths_agree,
    match_tracks,
    order_files,
    plausible_for_toc,
    scan_discs,
)
from mp3tagger.core.musicbrainz import Medium, Release, ReleaseTrack, parse_release
from mp3tagger.core.tagio.id3 import Id3Reader

FIXTURES = Path(__file__).parent / "fixtures"
WMP_TOC = "2+96+1DC94+3A640".encode("utf-16-le") + b"\x00\x00"
OTHER_TOC = "3+96+1000+2000+3000".encode("utf-16-le") + b"\x00\x00"


def karlsson() -> Release:
    data = json.loads((FIXTURES / "discid_karlsson.json").read_text())
    return parse_release(data["releases"][0], "disc id")


def local(name: str, seconds: float, track: str = "", disc: str = "") -> LocalFile:
    return LocalFile(Path(f"/m/{name}.mp3"), seconds, track, disc)


# --- discs from MCDI frames ------------------------------------------------------------------


def with_mcdi(make_mp3, path: Path, data: bytes) -> Path:
    from mutagen.id3 import ID3, MCDI, ID3NoHeaderError

    make_mp3(path)
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(MCDI(data=data))
    tags.save(path, v2_version=3)
    return path


def test_read_mcdi(make_mp3, tmp_path):
    path = with_mcdi(make_mp3, tmp_path / "a.mp3", WMP_TOC)
    assert Id3Reader().read_mcdi(path) == WMP_TOC
    assert Id3Reader().read_mcdi(make_mp3(tmp_path / "b.mp3")) is None  # no tag at all
    assert Id3Reader().read_mcdi(make_mp3(tmp_path / "c.mp3", title="T")) is None  # no MCDI


def test_files_of_one_cd_form_a_single_disc(make_mp3, tmp_path):
    paths = [with_mcdi(make_mp3, tmp_path / f"{i}.mp3", WMP_TOC) for i in range(3)]
    scan = scan_discs(paths, Id3Reader())
    (disc,) = scan.discs
    assert disc.paths == tuple(paths) and disc.toc.track_count == 2
    assert disc.disc_id == "AZfHkpq3HJPvDW8Pp0GoAHeqhtg-"
    assert scan.single_disc is disc and scan.without_toc == ()


def test_files_from_different_cds_are_separate_discs(make_mp3, tmp_path):
    a = with_mcdi(make_mp3, tmp_path / "a.mp3", WMP_TOC)
    b = with_mcdi(make_mp3, tmp_path / "b.mp3", OTHER_TOC)
    scan = scan_discs([a, b], Id3Reader())
    assert [d.paths for d in scan.discs] == [(a,), (b,)]
    assert scan.single_disc is None


def test_files_without_a_usable_toc_are_reported(make_mp3, tmp_path):
    good = with_mcdi(make_mp3, tmp_path / "good.mp3", WMP_TOC)
    plain = make_mp3(tmp_path / "plain.mp3")
    garbage = with_mcdi(make_mp3, tmp_path / "garbage.mp3", b"\x01\x02\x03")
    missing = tmp_path / "missing.mp3"
    scan = scan_discs([good, plain, garbage, missing], Id3Reader())
    assert [d.paths for d in scan.discs] == [(good,)]
    assert scan.without_toc == (plain, garbage, missing)
    assert scan.single_disc is None  # not every file is on that disc


def test_no_files():
    scan = scan_discs([], Id3Reader())
    assert scan.discs == () and scan.single_disc is None


# --- pairing ---------------------------------------------------------------------------------


def test_files_are_ordered_by_disc_track_then_name():
    files = [
        local("z", 1, track="1", disc="2"),
        local("b", 1, track="2/12"),
        local("a", 1, track="10"),
        local("c", 1),
        local("A2", 1, track="2"),
    ]
    assert [f.path.stem for f in order_files(files)] == ["A2", "b", "a", "c", "z"]
    assert [f.path.stem for f in order_files([local("q", 1), local("p", 1)])] == ["p", "q"]


def test_matching_by_position_with_length_differences():
    release = karlsson()
    (medium,) = release.media
    files = [local(f"{i}", t.seconds + 0.5, track=str(i)) for i, t in enumerate(medium.tracks, 1)]
    matches = match_tracks(files, medium)
    assert [m.track.title[-1] for m in matches] == list("123456")
    assert [m.file.path.stem for m in matches] == list("123456")
    assert all(abs(m.difference - 0.5) < 1e-9 for m in matches)
    assert lengths_agree(matches)


def test_files_are_paired_in_playing_order_not_in_the_order_given():
    (medium,) = karlsson().media
    shuffled = [local("b", 577, track="2"), local("a", 498, track="1")]
    matches = match_tracks(shuffled, medium)
    assert [m.file.path.stem for m in matches[:2]] == ["a", "b"]
    assert matches[0].track.position == 1 and matches[1].track.position == 2


def test_surplus_files_and_surplus_tracks_stay_unpaired():
    (medium,) = karlsson().media
    fewer = match_tracks([local("a", 498, track="1")], medium)
    assert len(fewer) == 6 and fewer[0].file is not None
    assert all(m.file is None and m.difference is None for m in fewer[1:])
    assert not lengths_agree(fewer)
    more = match_tracks([local(f"{i}", 100, track=str(i)) for i in range(8)], medium)
    assert len(more) == 8 and all(m.track is None for m in more[6:])


def test_lengths_that_differ_too_much_do_not_agree():
    (medium,) = karlsson().media
    files = [local(f"{i}", t.seconds, track=str(i)) for i, t in enumerate(medium.tracks, 1)]
    files[3] = local("3", medium.tracks[3].seconds + 30, track="4")
    matches = match_tracks(files, medium)
    assert not lengths_agree(matches)
    assert lengths_agree(matches, tolerance=60)
    assert not lengths_agree([])


def test_unknown_release_length_cannot_be_compared():
    medium = Medium(1, "", "CD", 1, (ReleaseTrack(1, "T", "A", None),), frozenset())
    (match,) = match_tracks([local("a", 100, track="1")], medium)
    assert match.difference is None and not lengths_agree([match])


# --- changes ---------------------------------------------------------------------------------


def paired(release: Release) -> tuple[Medium, list[TrackMatch]]:
    (medium,) = release.media
    files = [local(f"{i}", t.seconds, track=str(i)) for i, t in enumerate(medium.tracks, 1)]
    return medium, match_tracks(files, medium)


def test_changes_for_all_fields():
    release = karlsson()
    medium, matches = paired(release)
    changes = build_changes(
        matches, release, medium, ["title", "track", "album", "artist", "album_artist", "year"]
    )
    assert changes[Path("/m/1.mp3")] == {
        "title": "Karlsson vom Dach, Teil 1",
        "track": "1",
        "album": "Karlsson vom Dach",
        "artist": "Astrid Lindgren",
        "album_artist": "Astrid Lindgren",
        "year": "2006",
    }
    assert changes[Path("/m/6.mp3")]["title"] == "Karlsson vom Dach, Teil 6"
    assert len(changes) == 6


def test_only_the_chosen_fields_are_changed():
    release = karlsson()
    medium, matches = paired(release)
    changes = build_changes(matches, release, medium, ["title"])
    assert all(set(c) == {"title"} for c in changes.values())
    assert build_changes(matches, release, medium, []) == {}


def test_disc_is_only_set_for_releases_with_several_discs():
    release = karlsson()
    medium, matches = paired(release)
    assert "disc" not in build_changes(matches, release, medium, ["disc"]).get(Path("/m/1.mp3"), {})
    box_data = json.loads((FIXTURES / "discid_pettersson_two_releases.json").read_text())
    box = parse_release(box_data["releases"][1], "disc id")
    second = box.media[1]
    files = [local(f"{i}", 100, track=str(i)) for i in range(1, 4)]
    changes = build_changes(match_tracks(files, second), box, second, ["disc", "track"])
    assert changes[Path("/m/1.mp3")] == {"disc": "2", "track": "1"}


def test_empty_values_never_blank_a_tag():
    release = Release("x", "Album", "", "", "", "", "", (), False, "search")  # no artist, no date
    medium = Medium(1, "", "CD", 1, (ReleaseTrack(1, "", "", None),), frozenset())
    matches = match_tracks([local("a", 10, track="1")], medium)
    changes = build_changes(
        matches, release, medium, ["title", "artist", "album_artist", "year", "album"]
    )
    assert changes == {Path("/m/a.mp3"): {"album": "Album"}}


def test_unpaired_files_and_tracks_produce_no_changes():
    release = karlsson()
    (medium,) = release.media
    matches = match_tracks([local("a", 498, track="1")], medium)  # five tracks have no file
    assert list(build_changes(matches, release, medium, ["title"])) == [Path("/m/a.mp3")]
    extra = match_tracks([local(f"{i}", 1, track=str(i)) for i in range(8)], medium)
    assert len(build_changes(extra, release, medium, ["title"])) == 6  # two files stay as they are


def test_files_without_a_disc_tag_count_as_disc_one():
    files = [local("second", 1, track="1", disc="2"), local("first", 1, track="9")]
    assert [f.path.stem for f in order_files(files)] == ["first", "second"]


# --- plausibility of fuzzy matches -----------------------------------------------------------


def benjamin_toc() -> Toc:
    numbers = [int(n) for n in (FIXTURES / "toc_fuzzy_benjamin.toc.txt").read_text().split("+")]
    first, last, leadout, *offsets = numbers
    assert (first, last) == (1, 17) and len(offsets) == 17
    return Toc(first, tuple(offsets), leadout)


def test_the_real_fuzzy_match_is_plausible_for_its_own_disc():
    release = parse_release(
        json.loads((FIXTURES / "toc_fuzzy_benjamin.json").read_text())["releases"][0], "toc"
    )
    assert plausible_for_toc(release, benjamin_toc())


def test_other_track_counts_or_lengths_are_not_plausible():
    release = parse_release(
        json.loads((FIXTURES / "toc_fuzzy_benjamin.json").read_text())["releases"][0], "toc"
    )
    toc = benjamin_toc()
    assert not plausible_for_toc(release, Toc(1, toc.offsets[:-1], toc.leadout))  # 16 tracks
    assert not plausible_for_toc(release, Toc(1, toc.offsets, toc.leadout + 75 * 600))  # +10 min
    assert plausible_for_toc(release, Toc(1, toc.offsets, toc.leadout + 75 * 5))  # +5 s is fine


def test_unknown_lengths_cannot_rule_a_release_out():
    def release_with(*tracks: ReleaseTrack) -> Release:
        medium = Medium(1, "", "CD", 2, tracks, frozenset())
        return Release("x", "T", "", "", "", "", "", (medium,), False, "toc")

    toc = Toc(1, (150, 5000), 90000)
    partly_known = release_with(ReleaseTrack(1, "a", "", None), ReleaseTrack(2, "b", "", 5.0))
    assert plausible_for_toc(partly_known, toc)
    assert plausible_for_toc(release_with(), toc)  # no track list at all
