import json
import re
from pathlib import Path

import httpx
import pytest

from imagery import png
from mp3tagger.core.images import ImageInfo
from mp3tagger.core.itunes import (
    ITunes,
    ITunesError,
    _extra_words,
    is_square,
    title_words,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"itunes_{name}.json").read_text())


# --- title matching --------------------------------------------------------------------------


def test_title_words_ignore_case_punctuation_and_accents_stay():
    assert title_words("Teil 22: Im Land der Einhörner!") == [
        "teil", "22", "im", "land", "der", "einhörner",
    ]  # fmt: skip
    assert title_words("") == [] and title_words("---") == []


@pytest.mark.parametrize(
    ("candidate", "extra"),
    [
        ("Karlsson vom Dach", 0),
        ("karlsson VOM dach!", 0),
        ("Karlsson vom Dach 1", 1),
        ("Astrid Lindgren erzählt: Karlsson vom Dach", 3),
        ("Karlsson auf dem Dach", None),  # lacks "vom"
        ("Dach", None),
    ],
)
def test_extra_words_counts_what_a_result_adds_to_the_wanted_title(candidate, extra):
    assert _extra_words(candidate, "Karlsson vom Dach") == extra


def test_an_empty_wanted_title_matches_nothing():
    assert _extra_words("Anything", "") is None


def test_squareness_allows_a_small_tolerance():
    assert is_square(ImageInfo("image/png", 600, 600))
    assert is_square(ImageInfo("image/png", 600, 590))  # 1.7 %
    assert not is_square(ImageInfo("image/png", 600, 450))
    assert not is_square(ImageInfo("image/png", 100, 200))


# --- the search ------------------------------------------------------------------------------


class Apple:
    """A fake Apple: search results from recorded responses, artwork generated on request."""

    def __init__(self, audiobook=None, album=None, non_square=(), missing=()):
        self.audiobook, self.album = audiobook or {"results": []}, album or {"results": []}
        self.non_square, self.missing = tuple(non_square), tuple(missing)
        self.searches: list[httpx.Request] = []
        self.images: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "itunes.apple.com":
            self.searches.append(request)
            media = request.url.params["media"]
            return httpx.Response(200, json=self.audiobook if media == "audiobook" else self.album)
        url = str(request.url)
        self.images.append(url)
        if any(marker in url for marker in self.missing):
            return httpx.Response(404)
        size = int(re.search(r"/(\d+)x\d+bb", url).group(1)) // 10
        if any(marker in url for marker in self.non_square):
            return httpx.Response(200, content=png(size, size // 2))
        return httpx.Response(200, content=png(size, size))


def make(apple: Apple, **kwargs) -> ITunes:
    async def no_wait(_seconds: float) -> None:
        return None

    return ITunes(transport=httpx.MockTransport(apple), sleep=no_wait, **kwargs)


async def test_results_are_ranked_by_how_close_their_title_is():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    candidates = await make(apple).search_covers("Karlsson vom Dach", "Astrid Lindgren")
    assert candidates[0].title == "Karlsson vom Dach 1"  # one extra word beats longer titles
    assert candidates[0].matches_title and candidates[0].kind == "audiobook"
    titles = [c.title for c in candidates]
    assert titles.index("Astrid Lindgren erzählt: Karlsson vom Dach") > 0
    matching = [c.matches_title for c in candidates]
    assert matching == sorted(matching, reverse=True)  # matches first, then the others


async def test_candidate_carries_a_thumbnail_and_the_full_size_url():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    first = (await make(apple).search_covers("Karlsson vom Dach", "Astrid Lindgren"))[0]
    assert first.thumbnail.mime == "image/png" and first.thumbnail.data.startswith(b"\x89PNG")
    assert first.image_url.endswith("/600x600bb.jpg") and "100x100" not in first.image_url
    assert any(u.endswith("/200x200bb.jpg") for u in apple.images)  # thumbnails are 200 px
    assert first.year == "2011" and first.artist.startswith("Astrid Lindgren")


async def test_the_search_is_for_audiobooks_in_the_configured_country():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    await make(apple, country="at").search_covers("Karlsson vom Dach", "Astrid Lindgren")
    params = apple.searches[0].url.params
    assert (params["media"], params["entity"], params["country"]) == (
        "audiobook",
        "audiobook",
        "at",
    )
    assert params["term"] == "Karlsson vom Dach Astrid Lindgren"
    assert len(apple.searches) == 1  # a good audiobook match: no need to search albums as well


async def test_only_square_covers_are_offered():
    first_collection = fixture("karlsson_audiobook")["results"][2]["artworkUrl100"]
    marker = first_collection.split("/")[-3]  # part of the path of "Karlsson vom Dach 1"
    apple = Apple(audiobook=fixture("karlsson_audiobook"), non_square=[marker])
    candidates = await make(apple).search_covers("Karlsson vom Dach", "Astrid Lindgren")
    assert "Karlsson vom Dach 1" not in [c.title for c in candidates]
    assert candidates and candidates[0].matches_title  # the next best square one


async def test_covers_that_cannot_be_fetched_are_skipped():
    marker = fixture("karlsson_audiobook")["results"][2]["artworkUrl100"].split("/")[-3]
    apple = Apple(audiobook=fixture("karlsson_audiobook"), missing=[marker])
    candidates = await make(apple).search_covers("Karlsson vom Dach", "Astrid Lindgren")
    assert "Karlsson vom Dach 1" not in [c.title for c in candidates]


async def test_albums_are_searched_when_no_audiobook_has_the_title():
    apple = Apple(audiobook={"results": []}, album=fixture("karlsson_album"))
    candidates = await make(apple).search_covers("Karlsson vom Dach", "Astrid Lindgren")
    assert [r.url.params["media"] for r in apple.searches] == ["audiobook", "audiobook", "music"]
    assert candidates and all(c.kind == "album" for c in candidates)
    assert candidates[0].title == "Karlsson vom Dach - Single"  # the only one with the title


async def test_without_an_artist_hit_the_title_alone_is_tried():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    original = apple.__call__
    terms = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "itunes.apple.com":
            terms.append(request.url.params["term"])
            if "Lindgren" in request.url.params["term"]:
                return httpx.Response(200, json={"results": []})
        return original(request)

    client = ITunes(transport=httpx.MockTransport(handler), sleep=lambda s: _noop())
    candidates = await client.search_covers("Karlsson vom Dach", "Astrid Lindgren")
    assert terms[:2] == ["Karlsson vom Dach Astrid Lindgren", "Karlsson vom Dach"]
    assert candidates


async def _noop() -> None:
    return None


async def test_no_artwork_for_other_titles_means_no_matches_flag():
    apple = Apple(audiobook=fixture("sternenschweif_audiobook"))
    candidates = await make(apple).search_covers("Something Entirely Different", "X", limit=4)
    assert candidates and not any(c.matches_title for c in candidates)
    assert len(candidates) <= 4


async def test_the_limit_caps_the_candidates():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    assert len(await make(apple).search_covers("Karlsson vom Dach", "A", limit=2)) == 2


async def test_sternenschweif_title_with_extra_words_still_matches():
    apple = Apple(audiobook=fixture("sternenschweif_audiobook"))
    candidates = await make(apple).search_covers(
        "Teil 22: Im Land der Einhörner", "Sternenschweif, Linda Chapman"
    )
    assert candidates[0].title == "Sternenschweif, Teil 22: Im Land der Einhörner"
    assert candidates[0].matches_title


async def test_searches_are_spaced_out():
    sleeps = []

    async def sleep(seconds: float) -> None:
        sleeps.append(round(seconds, 2))

    apple = Apple(audiobook={"results": []}, album={"results": []})
    client = ITunes(
        transport=httpx.MockTransport(apple), sleep=sleep, min_interval=3.0, clock=lambda: 0.0
    )
    await client.search_covers("Nothing", "Nobody")
    assert len(apple.searches) == 3 and sleeps == [3.0, 3.0]  # only the searches wait


async def test_a_busy_api_is_reported_as_an_itunes_error():
    client = ITunes(
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        max_retries=0,
        sleep=lambda s: _noop(),
    )
    with pytest.raises(ITunesError, match="iTunes is busy"):
        await client.search_covers("A", "B")


# --- the chosen cover ------------------------------------------------------------------------


async def test_full_cover_downloads_the_big_image():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    client = make(apple)
    candidate = (await client.search_covers("Karlsson vom Dach", "A"))[0]
    cover = await client.full_cover(candidate)
    assert cover.mime == "image/png" and cover.data.startswith(b"\x89PNG")
    assert apple.images[-1] == candidate.image_url


async def test_full_cover_must_be_square_and_present():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    client = make(apple)
    candidate = (await client.search_covers("Karlsson vom Dach", "A"))[0]
    apple.non_square = ("600x600bb",)
    with pytest.raises(ITunesError, match="not square"):
        await client.full_cover(candidate)
    apple.non_square, apple.missing = (), ("600x600bb",)
    with pytest.raises(ITunesError, match="no longer has"):
        await client.full_cover(candidate)


async def test_full_cover_rejects_something_that_is_not_an_image():
    apple = Apple(audiobook=fixture("karlsson_audiobook"))
    client = make(apple)
    candidate = (await client.search_covers("Karlsson vom Dach", "A"))[0]
    broken = ITunes(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>")))
    with pytest.raises(ITunesError, match="could not be used"):
        await broken.full_cover(candidate)
