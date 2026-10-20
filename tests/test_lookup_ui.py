"""The MusicBrainz lookup in the page, with a fake client (no network)."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from mutagen.id3 import ID3, MCDI
from nicegui import ui
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

from imagery import png
from mp3tagger.config import Config
from mp3tagger.core.models import CoverArt
from mp3tagger.core.musicbrainz import MusicBrainzError, Release, parse_release
from mp3tagger.ui.app import build_app
from uihelpers import button, click, open_folder, row_for, select

FIXTURES = Path(__file__).parent / "fixtures"
KARLSSON_TOC = "6+96+926A+13B91+1A876+23885+2D8DB+34008".encode("utf-16-le") + b"\x00\x00"
OTHER_TOC = "2+96+1DC94+3A640".encode("utf-16-le") + b"\x00\x00"
KARLSSON_DISC = "QFMiaZBX.YfwImg_6WzFSe0L.I4-"
COVER = CoverArt(png(6, 6), "image/png")


def fixture_release(name: str = "discid_karlsson", index: int = 0, source="disc id") -> Release:
    return parse_release(
        json.loads((FIXTURES / f"{name}.json").read_text())["releases"][index], source
    )


def fit_lengths(release: Release, seconds: float = 1.04) -> Release:
    """The same release with track lengths the (very short) test files agree with."""
    media = tuple(
        replace(m, tracks=tuple(replace(t, seconds=seconds) for t in m.tracks))
        for m in release.media
    )
    return replace(release, media=media)


def without_tracks(release: Release) -> Release:
    """What a text search returns: no track lists."""
    media = tuple(replace(m, tracks=()) for m in release.media)
    return replace(release, media=media, source="search")


class FakeMusicBrainz:
    def __init__(self, *, by_disc=(), by_toc=(), found=(), details=(), cover=COVER, error=None):
        self.by_disc, self.by_toc, self.found = list(by_disc), list(by_toc), list(found)
        self.details = {r.id: r for r in details}
        self.cover, self.error, self.calls = cover, error, []

    def _check(self) -> None:
        if self.error:
            raise self.error

    async def releases_for_disc_id(self, disc_id):
        self.calls.append(("disc", disc_id))
        self._check()
        return list(self.by_disc)

    async def releases_for_toc(self, toc):
        self.calls.append(("toc", toc.track_count))
        self._check()
        return list(self.by_toc)

    async def search(self, artist, album, limit=10):
        self.calls.append(("search", artist, album))
        self._check()
        return list(self.found)

    async def release(self, release_id, source="id"):
        self.calls.append(("release", release_id))
        self._check()
        return self.details[release_id]

    async def front_cover(self, release):
        self.calls.append(("cover", release.id))
        if isinstance(self.cover, Exception):
            raise self.cover
        return self.cover


def add_mcdi(path: Path, data: bytes) -> None:
    tags = ID3(path)
    tags.add(MCDI(data=data))
    tags.save(path, v2_version=3)


@pytest.fixture
def cd(make_mp3, music_root):
    """Six files of one CD (its table of contents is that of "Karlsson vom Dach")."""
    folder = music_root / "cd"
    paths = [
        make_mp3(folder / f"0{i} Titelnummer {i}.mp3", title=f"Titelnummer {i}", track=str(i))
        for i in range(1, 7)
    ]
    for path in paths:
        add_mcdi(path, KARLSSON_TOC)
    return paths


async def open_lookup(user: User, music_root, monkeypatch, paths, fake, *, sub="cd") -> None:
    build_app(Config(roots=(music_root,)), musicbrainz=fake)
    await user.open("/")
    user.find("Open folder…").click()
    await asyncio.sleep(0.1)
    from uihelpers import click_folder_entry, click_in_dialog

    click_folder_entry(user, sub)
    click_in_dialog(user, ui.button, "Open")
    await user.should_see(kind=ui.label, content=" files · ", retries=100)
    await select(user, monkeypatch, *paths)
    await click(user, "Look up")
    await asyncio.sleep(0.2)


def tables(user: User) -> list[ui.table]:
    return [e for e in user.client.elements.values() if isinstance(e, ui.table)]


def rows_of(table: ui.table) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "id"} for r in table.rows]


def dialog_input(user: User, label: str) -> ui.input:
    """The dialog's input (the tag panel has inputs with the same labels; the dialog is newer)."""
    return [
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.input) and e.props.get("label") == label
    ][-1]


def checkbox(user: User, text: str) -> ui.checkbox:
    (box,) = (
        e for e in user.client.elements.values() if isinstance(e, ui.checkbox) and e.text == text
    )
    return box


def select_row(user: User, table: ui.table, index: int = 0) -> None:
    row = table.rows[index]
    UserInteraction(user, {table}, None).trigger(
        "selection", {"added": True, "rows": [row], "keys": [row["id"]]}
    )


# --- the button ------------------------------------------------------------------------------


async def test_lookup_needs_a_selection(user: User, music_root, cd, monkeypatch):
    build_app(Config(roots=(music_root,)), musicbrainz=FakeMusicBrainz())
    await user.open("/")
    assert not button(user, "Look up").enabled
    await open_folder(user, music_root, "cd")
    await select(user, monkeypatch, cd[0])
    assert button(user, "Look up").enabled


# --- lookup by CD identifier -----------------------------------------------------------------


async def test_the_cd_is_looked_up_by_its_identifier_as_soon_as_the_dialog_opens(
    user: User, music_root, cd, monkeypatch
):
    release = fit_lengths(fixture_release())
    fake = FakeMusicBrainz(by_disc=[release])
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("1 release(s) have exactly this CD identifier")
    assert fake.calls == [("disc", KARLSSON_DISC)]
    releases, preview = tables(user)[-2:]
    assert rows_of(releases) == [
        {
            "title": "Karlsson vom Dach",
            "artist": "Astrid Lindgren",
            "date": "2006",
            "country": "DE",
            "label": "Oetinger Audio",
            "tracks": 6,
            "found": "CD identifier",
        }
    ]
    assert [r["title"] for r in rows_of(preview)] == [
        f"Karlsson vom Dach, Teil {i}" for i in range(1, 7)
    ]
    assert [r["file"] for r in rows_of(preview)][:2] == [
        "01 Titelnummer 1.mp3",
        "02 Titelnummer 2.mp3",
    ]
    await user.should_see("all track lengths agree with MusicBrainz")
    assert button(user, "Apply to 6").enabled


async def test_the_release_that_is_previewed_is_marked_in_the_table(
    user: User, music_root, cd, monkeypatch
):
    release = fit_lengths(fixture_release())
    await open_lookup(user, music_root, monkeypatch, cd, FakeMusicBrainz(by_disc=[release]))
    await user.should_see("1 release(s) have exactly this CD identifier")
    releases = tables(user)[-2]
    assert [row["id"] for row in releases.selected] == [release.id]


async def test_applying_imports_titles_numbers_and_cover_as_pending_edits(
    user: User, music_root, cd, monkeypatch
):
    fake = FakeMusicBrainz(by_disc=[fit_lengths(fixture_release())])
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("1 release(s) have exactly this CD identifier")
    await click(user, "Apply to 6")
    await user.should_see("MusicBrainz: 6 file(s) modified")
    assert ("cover", "71034996-9dfc-4857-a86d-c1da0263ab4c") in fake.calls
    first = row_for(user, cd[0])
    assert (first["title"], first["track"], first["album"], first["artist"], first["year"]) == (
        "Karlsson vom Dach, Teil 1",
        "1",
        "Karlsson vom Dach",
        "Astrid Lindgren",
        "2006",
    )
    assert first["album_artist"] == "Astrid Lindgren" and first["cover"] == "✓"
    assert all(row_for(user, p)["dirty"] for p in cd)
    assert ID3(cd[0])["TIT2"].text == ["Titelnummer 1"]  # nothing written yet
    await click(user, "Save")
    await user.should_see("Saved 6 file(s)")
    tags = ID3(cd[2])
    assert tags["TIT2"].text == ["Karlsson vom Dach, Teil 3"] and tags["TALB"].text == [
        "Karlsson vom Dach"
    ]
    assert [f.data for f in tags.getall("APIC")] == [COVER.data]


async def test_only_the_chosen_fields_are_imported(user: User, music_root, cd, monkeypatch):
    fake = FakeMusicBrainz(by_disc=[fit_lengths(fixture_release())], cover=None)
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("1 release(s) have exactly this CD identifier")
    for text in ("Title", "Artist", "Album artist", "Year"):
        checkbox(user, text).set_value(False)
    checkbox(user, "Cover (Cover Art Archive)").set_value(False)
    await click(user, "Apply to 6")
    row = row_for(user, cd[0])
    assert (row["title"], row["track"], row["album"]) == ("Titelnummer 1", "1", "Karlsson vom Dach")
    assert row["artist"] == ""  # the files had no artist and the import was told to leave it
    assert not any(c[0] == "cover" for c in fake.calls)
    assert row["cover"] == ""


async def test_differing_track_lengths_are_called_out(user: User, music_root, cd, monkeypatch):
    fake = FakeMusicBrainz(by_disc=[fixture_release()])  # real lengths: 8 minutes, files: 1 second
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("some track lengths differ")
    assert "⚠" in rows_of(tables(user)[-1])[0]["note"]
    assert button(user, "Apply to 6").enabled  # a warning, not a block


async def test_different_track_counts_leave_files_or_tracks_unpaired(
    user: User, music_root, cd, monkeypatch
):
    fake = FakeMusicBrainz(by_disc=[fit_lengths(fixture_release())])
    await open_lookup(user, music_root, monkeypatch, cd[:4], fake)  # only four of six files
    await user.should_see("4 files but 6 tracks")
    rows = rows_of(tables(user)[-1])
    assert [r["note"] for r in rows[4:]] == ["⚠ no file", "⚠ no file"]
    assert button(user, "Apply to 4").enabled


async def test_cancel_changes_nothing(user: User, music_root, cd, monkeypatch):
    fake = FakeMusicBrainz(by_disc=[fit_lengths(fixture_release())])
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("1 release(s) have exactly this CD identifier")
    await click(user, "Cancel")
    assert not any(row_for(user, p)["dirty"] for p in cd)


# --- fuzzy lookup and failure ----------------------------------------------------------------


async def test_without_an_exact_match_only_plausible_similar_cds_are_offered(
    user: User, music_root, cd, monkeypatch
):
    good = fit_lengths(fixture_release(source="toc"), seconds=2838 / 6)
    wrong_count = replace(good, id="other", title="Heidi", media=good.media[0:0])
    fake = FakeMusicBrainz(by_toc=[good, wrong_count])
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("similar CD layout")
    assert [c[0] for c in fake.calls] == ["disc", "toc"]
    assert [r["title"] for r in rows_of(tables(user)[-2])] == ["Karlsson vom Dach"]


async def test_an_unknown_cd_points_to_the_search(user: User, music_root, cd, monkeypatch):
    await open_lookup(user, music_root, monkeypatch, cd, FakeMusicBrainz())
    await user.should_see("MusicBrainz does not know this CD")
    assert rows_of(tables(user)[-2]) == [] and not button(user, "Apply").enabled


async def test_a_busy_server_is_reported_and_the_search_stays_usable(
    user: User, music_root, cd, monkeypatch
):
    fake = FakeMusicBrainz(
        error=MusicBrainzError("MusicBrainz is busy, please try again in a moment")
    )
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("MusicBrainz is busy")
    assert button(user, "Search").enabled
    fake.error = None
    fake.found = [without_tracks(fixture_release())]
    fake.details = {fake.found[0].id: fit_lengths(fixture_release())}
    await click(user, "Search")
    await user.should_see("1 release(s) found")


# --- search by name --------------------------------------------------------------------------


async def test_files_without_a_cd_identifier_are_searched_by_name(
    user: User, music_root, make_mp3, monkeypatch
):
    folder = music_root / "plain"
    paths = [
        make_mp3(
            folder / f"0{i}.mp3",
            title=f"T{i}",
            artist="Astrid Lindgren",
            album="Karlsson vom Dach",
            track=str(i),
        )
        for i in range(1, 7)
    ]
    detail = fit_lengths(fixture_release(source="search"))
    fake = FakeMusicBrainz(found=[without_tracks(detail)], details=[detail])
    await open_lookup(user, music_root, monkeypatch, paths, fake, sub="plain")
    await user.should_see("carry no CD identifier")
    assert fake.calls == []  # nothing is sent until the user searches
    assert dialog_input(user, "Artist").value == "Astrid Lindgren"  # prefilled from the tags
    assert dialog_input(user, "Album").value == "Karlsson vom Dach"
    await click(user, "Search")
    await user.should_see("1 release(s) found")
    assert fake.calls == [("search", "Astrid Lindgren", "Karlsson vom Dach")]
    releases = tables(user)[-2]
    assert rows_of(releases)[0]["found"] == "search"
    assert rows_of(tables(user)[-1]) == []  # nothing to preview until a release is chosen
    select_row(user, releases)
    await user.should_see("all track lengths agree")  # the track list was fetched on selection
    assert fake.calls[-1] == ("release", detail.id)
    await click(user, "Apply to 6")
    assert row_for(user, paths[3])["title"] == "Karlsson vom Dach, Teil 4"


async def test_the_search_terms_can_be_edited(user: User, music_root, make_mp3, monkeypatch):
    path = make_mp3(music_root / "plain" / "a.mp3", title="x", artist="Wrong", album="Wrong")
    fake = FakeMusicBrainz()
    await open_lookup(user, music_root, monkeypatch, [path], fake, sub="plain")
    dialog_input(user, "Artist").set_value("Ellis Kaut")
    dialog_input(user, "Album").set_value("Pumuckl Folge 14")
    await click(user, "Search")
    await user.should_see("Nothing found")
    assert fake.calls == [("search", "Ellis Kaut", "Pumuckl Folge 14")]


async def test_a_search_error_is_shown(user: User, music_root, make_mp3, monkeypatch):
    path = make_mp3(music_root / "plain" / "a.mp3", title="x")
    fake = FakeMusicBrainz(error=MusicBrainzError("Enter an artist or an album to search for"))
    await open_lookup(user, music_root, monkeypatch, [path], fake, sub="plain")
    await click(user, "Search")
    await user.should_see("Enter an artist or an album")


async def test_files_from_several_cds_are_not_looked_up_automatically(
    user: User, music_root, cd, monkeypatch
):
    add_mcdi(cd[5], OTHER_TOC)  # the last file claims to be from another CD
    fake = FakeMusicBrainz()
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("come from 2 different CDs")
    assert fake.calls == []


async def test_some_files_without_cd_data_are_not_looked_up_automatically(
    user: User, music_root, cd, make_mp3, monkeypatch
):
    extra = make_mp3(music_root / "cd" / "07 extra.mp3", title="extra", track="7")
    fake = FakeMusicBrainz()
    await open_lookup(user, music_root, monkeypatch, [*cd, extra], fake)
    await user.should_see("1 of the selected files carry no CD identifier")
    assert fake.calls == []


# --- releases with several discs, and covers -------------------------------------------------


async def test_a_box_set_offers_the_discs_and_preselects_the_one_that_was_looked_up(
    user: User, music_root, make_mp3, monkeypatch
):
    folder = music_root / "box"
    toc = "3+96+18FB2+2D327+3D0C2".encode("utf-16-le") + b"\x00\x00"
    paths = [make_mp3(folder / f"0{i}.mp3", title=f"t{i}", track=str(i)) for i in range(1, 4)]
    for path in paths:
        add_mcdi(path, toc)
    from mp3tagger.core.discid import parse_mcdi

    disc_id = parse_mcdi(toc).disc_id()
    box = fixture_release("discid_pettersson_two_releases", 1)
    media = tuple(
        replace(m, disc_ids=frozenset({disc_id}) if m.position == 2 else frozenset())
        for m in box.media
    )
    box = fit_lengths(replace(box, media=media))
    fake = FakeMusicBrainz(by_disc=[box])
    await open_lookup(user, music_root, monkeypatch, paths, fake, sub="box")
    await user.should_see("1 release(s) have exactly this CD identifier")
    chooser = [
        e
        for e in user.client.elements.values()
        if isinstance(e, ui.select) and e.props.get("label") == "Disc of this release"
    ][0]
    assert chooser.visible and chooser.value == 2  # the disc whose id matched
    second = box.media[1]
    assert [r["title"] for r in rows_of(tables(user)[-1])] == [t.title for t in second.tracks]
    await click(user, "Apply to 3")
    assert row_for(user, paths[0])["title"] == second.tracks[0].title


async def test_a_release_without_cover_art_disables_the_cover_option(
    user: User, music_root, cd, monkeypatch
):
    release = replace(fit_lengths(fixture_release()), has_front_cover=False)
    fake = FakeMusicBrainz(by_disc=[release])
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("none available")
    box = checkbox(user, "Cover (Cover Art Archive) – none available")
    assert not box.enabled
    await click(user, "Apply to 6")
    assert not any(c[0] == "cover" for c in fake.calls)
    assert row_for(user, cd[0])["cover"] == ""


async def test_a_cover_that_cannot_be_loaded_does_not_stop_the_tags(
    user: User, music_root, cd, monkeypatch
):
    fake = FakeMusicBrainz(
        by_disc=[fit_lengths(fixture_release())], cover=MusicBrainzError("MusicBrainz is busy")
    )
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("1 release(s) have exactly this CD identifier")
    await click(user, "Apply to 6")
    await user.should_see("The cover could not be loaded")
    assert row_for(user, cd[0])["title"] == "Karlsson vom Dach, Teil 1"
    assert row_for(user, cd[0])["cover"] == ""


async def test_the_import_can_be_undone(user: User, music_root, cd, monkeypatch):
    fake = FakeMusicBrainz(by_disc=[fit_lengths(fixture_release())])
    await open_lookup(user, music_root, monkeypatch, cd, fake)
    await user.should_see("1 release(s) have exactly this CD identifier")
    await click(user, "Apply to 6")
    await user.should_see("MusicBrainz: 6 file(s) modified")
    await click(user, "Undo")  # the cover
    await click(user, "Undo")  # the tags
    assert not any(row_for(user, p)["dirty"] for p in cd)
    assert row_for(user, cd[0])["title"] == "Titelnummer 1"
