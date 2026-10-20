import json
from pathlib import Path

import httpx
import pytest

from imagery import png
from mp3tagger.core.discid import Toc
from mp3tagger.core.musicbrainz import MusicBrainz, MusicBrainzError, parse_release

FIXTURES = Path(__file__).parent / "fixtures"
KARLSSON_DISC = "QFMiaZBX.YfwImg_6WzFSe0L.I4-"
PETTERSSON_DISC = "5fVdZg1UPjzrnQqpYZXG_pHylE8-"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# --- parsing real responses ------------------------------------------------------------------


def test_exact_disc_id_response():
    release = parse_release(load("discid_karlsson")["releases"][0], "disc id")
    assert (release.title, release.artist, release.date, release.year) == (
        "Karlsson vom Dach",
        "Astrid Lindgren",
        "2006",
        "2006",
    )
    assert (release.country, release.label, release.barcode) == (
        "DE",
        "Oetinger Audio",
        "9783789101885",
    )
    assert release.has_front_cover and release.source == "disc id"
    assert release.track_count == 6 and release.has_track_lists
    (medium,) = release.media
    assert [t.title for t in medium.tracks][:2] == [
        "Karlsson vom Dach, Teil 1",
        "Karlsson vom Dach, Teil 2",
    ]
    assert [t.position for t in medium.tracks] == [1, 2, 3, 4, 5, 6]
    assert medium.tracks[0].seconds == 498.0 and medium.tracks[0].artist == "Astrid Lindgren"
    assert KARLSSON_DISC in medium.disc_ids


def test_medium_for_prefers_the_disc_id_then_a_unique_track_count():
    release = parse_release(load("discid_karlsson")["releases"][0], "disc id")
    (medium,) = release.media
    assert release.medium_for(KARLSSON_DISC, 99) is medium  # the disc id decides
    assert release.medium_for(None, 6) is medium
    assert release.medium_for(None, 5) is None


def test_box_set_picks_the_disc_that_was_looked_up():
    single, box = (
        parse_release(r, "disc id") for r in load("discid_pettersson_two_releases")["releases"]
    )
    assert single.track_count == 3 and len(box.media) == 3
    chosen = box.medium_for(PETTERSSON_DISC, 3)
    assert chosen is not None and chosen.position == 1 and PETTERSSON_DISC in chosen.disc_ids
    assert box.medium_for("some-other-disc-id", 3) is None  # two discs have 3 tracks: ambiguous
    assert box.medium_for(None, 12).position == 3  # a unique track count is enough


def test_fuzzy_toc_response_has_tracks_but_no_disc_ids():
    release = parse_release(load("toc_fuzzy_benjamin")["releases"][0], "toc")
    assert release.title.startswith("Benjamin Minis - Folge 2") and release.source == "toc"
    assert release.artist == "Benjamin Blümchen"
    assert release.media[0].disc_ids == frozenset() and release.has_track_lists
    assert release.medium_for(None, 17) is release.media[0]


def test_search_results_have_no_track_lists():
    releases = [parse_release(r, "search") for r in load("search_karlsson")["releases"]]
    assert len(releases) == 3 and releases[0].source == "search"
    assert not releases[0].has_track_lists and releases[0].track_count == 6
    assert all(m.tracks == () and m.track_count > 0 for m in releases[0].media)


def test_missing_optional_data_is_tolerated():
    release = parse_release({"id": "x", "title": "T"}, "search")
    assert (release.artist, release.date, release.year, release.label, release.media) == (
        "",
        "",
        "",
        "",
        (),
    )
    assert not release.has_front_cover and release.track_count == 0


def test_joined_artist_credits():
    data = {"id": "x", "artist-credit": [{"name": "A", "joinphrase": " & "}, {"name": "B"}]}
    assert parse_release(data, "search").artist == "A & B"


# --- the client ------------------------------------------------------------------------------


class FakeTime:
    """A clock that only moves when the client sleeps, so waiting costs no real time."""

    def __init__(self) -> None:
        self.now, self.sleeps = 1000.0, []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def make(handler, *, time: FakeTime | None = None, **kwargs) -> tuple[MusicBrainz, FakeTime]:
    fake = time or FakeTime()
    client = MusicBrainz(
        transport=httpx.MockTransport(handler), sleep=fake.sleep, clock=fake.clock, **kwargs
    )
    return client, fake


def json_response(name: str):
    return httpx.Response(200, json=load(name))


async def test_lookup_by_disc_id_sends_the_expected_request():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response("discid_karlsson")

    client, _ = make(handler)
    (release,) = await client.releases_for_disc_id(KARLSSON_DISC)
    (request,) = seen
    assert request.url.path == f"/ws/2/discid/{KARLSSON_DISC}"
    assert request.url.params["fmt"] == "json" and "recordings" in request.url.params["inc"]
    assert request.url.params["cdstubs"] == "no"
    assert request.headers["User-Agent"].startswith("MP3Tagger/")
    assert release.title == "Karlsson vom Dach" and release.source == "disc id"


async def test_unknown_disc_id_is_an_empty_result_not_an_error():
    client, _ = make(lambda r: httpx.Response(404, json={"error": "Not found"}))
    assert await client.releases_for_disc_id("nope") == []


async def test_fuzzy_lookup_by_toc():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response("toc_fuzzy_benjamin")

    toc = Toc(1, (150, 5000, 9000), 12000)
    client, _ = make(handler)
    (release,) = await client.releases_for_toc(toc)
    assert seen[0].url.path == "/ws/2/discid/-"
    assert seen[0].url.params["toc"] == "1+3+12000+150+5000+9000"
    assert release.source == "toc"


async def test_text_search_builds_a_quoted_query():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response("search_karlsson")

    client, _ = make(handler)
    releases = await client.search("Astrid Lindgren", 'Karlsson "vom" Dach', limit=5)
    params = seen[0].url.params
    assert seen[0].url.path == "/ws/2/release"
    assert params["query"] == 'release:"Karlsson \\"vom\\" Dach" AND artist:"Astrid Lindgren"'
    assert params["limit"] == "5" and len(releases) == 3


async def test_search_with_only_one_term_and_with_none():
    seen = []
    client, _ = make(lambda r: seen.append(r) or json_response("search_karlsson"))
    await client.search("", "Karlsson")
    assert seen[0].url.params["query"] == 'release:"Karlsson"'
    with pytest.raises(MusicBrainzError, match="Enter an artist or an album"):
        await client.search("  ", "")
    assert len(seen) == 1  # nothing was sent for the empty search


async def test_release_details_and_unknown_release():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/known"):
            return httpx.Response(200, json=load("discid_karlsson")["releases"][0])
        return httpx.Response(404, json={"error": "Not Found"})

    client, _ = make(handler)
    release = await client.release("known")
    assert release.has_track_lists and release.source == "id"
    with pytest.raises(MusicBrainzError, match="does not know"):
        await client.release("unknown")


# --- cover art -------------------------------------------------------------------------------


def with_cover(front: bool = True):
    data = load("discid_karlsson")["releases"][0]
    data["cover-art-archive"] = {"front": front}
    return parse_release(data, "disc id")


async def test_cover_follows_the_redirect_to_the_image():
    image = png(4, 3)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "coverartarchive.org":
            return httpx.Response(
                307, headers={"Location": "https://archive.org/download/x/front.png"}
            )
        return httpx.Response(200, content=image, headers={"Content-Type": "image/png"})

    client, _ = make(handler)
    cover = await client.front_cover(with_cover())
    assert cover is not None and (cover.mime, cover.data) == ("image/png", image)
    assert seen[0].endswith("/release/71034996-9dfc-4857-a86d-c1da0263ab4c/front-500")
    assert seen[1].startswith("https://archive.org/")


async def test_no_request_when_the_release_has_no_front_cover():
    seen = []
    client, _ = make(lambda r: seen.append(r) or httpx.Response(200))
    assert await client.front_cover(with_cover(front=False)) is None
    assert seen == []


async def test_cover_that_is_not_there_or_not_an_image():
    client, _ = make(lambda r: httpx.Response(404))
    assert await client.front_cover(with_cover()) is None
    client, _ = make(lambda r: httpx.Response(200, content=b"<html>not an image</html>"))
    with pytest.raises(MusicBrainzError, match="cover image could not be used"):
        await client.front_cover(with_cover())


# --- politeness and failure handling ---------------------------------------------------------


async def test_requests_are_spaced_by_the_minimum_interval():
    client, fake = make(lambda r: json_response("discid_karlsson"), min_interval=1.1)
    await client.releases_for_disc_id("a")
    assert fake.sleeps == []  # the first request goes out at once
    await client.releases_for_disc_id("b")
    assert fake.sleeps == [1.1]
    fake.now += 5  # plenty of time has passed on its own
    await client.releases_for_disc_id("c")
    assert fake.sleeps == [1.1]  # no extra wait needed


async def test_busy_server_is_retried_with_growing_pauses():
    answers = [503, 503, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        status = answers.pop(0)
        return json_response("discid_karlsson") if status == 200 else httpx.Response(status)

    client, fake = make(handler, min_interval=0)
    assert len(await client.releases_for_disc_id("x")) == 1
    assert fake.sleeps == [1.5, 3.0] and answers == []


async def test_retry_after_header_is_respected():
    answers = [httpx.Response(503, headers={"Retry-After": "7"}), json_response("discid_karlsson")]
    client, fake = make(lambda r: answers.pop(0), min_interval=0)
    await client.releases_for_disc_id("x")
    assert fake.sleeps == [7.0]


async def test_giving_up_after_the_retries_explains_what_happened():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    client, fake = make(handler, min_interval=0, max_retries=2)
    with pytest.raises(MusicBrainzError, match="busy"):
        await client.releases_for_disc_id("x")
    assert len(calls) == 3 and fake.sleeps == [1.5, 3.0]


async def test_other_errors_are_not_retried_and_show_the_servers_reason():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, json={"error": "Invalid query"})

    client, fake = make(handler, min_interval=0)
    with pytest.raises(MusicBrainzError, match=r"HTTP 400.*Invalid query"):
        await client.search("a", "b")
    assert len(calls) == 1 and fake.sleeps == []


async def test_network_failures_are_retried_and_then_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client, fake = make(handler, min_interval=0, max_retries=1)
    with pytest.raises(MusicBrainzError, match="Cannot reach MusicBrainz"):
        await client.releases_for_disc_id("x")
    assert fake.sleeps == [1.5]


async def test_contact_is_part_of_the_user_agent_only_when_given():
    agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers["User-Agent"])
        return json_response("discid_karlsson")

    for contact, expected in (("", False), ("me@example.org", True)):
        client, _ = make(handler, contact=contact)
        await client.releases_for_disc_id("x")
        assert ("( me@example.org )" in agents[-1]) is expected
