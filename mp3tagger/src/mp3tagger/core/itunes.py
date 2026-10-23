"""Cover art search in Apple's iTunes Search API (no key needed).

The API returns the artwork of albums and audiobooks as square images in any size. Results are
ranked by how closely their title matches the wanted one, and anything that is not square is
dropped. The thumbnails are fetched by the server, so the browser never talks to Apple.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import metadata
from typing import Literal

import httpx

from mp3tagger.core.http import PoliteClient, ServiceError
from mp3tagger.core.images import ImageInfo, sniff_image
from mp3tagger.core.models import CoverArt

API = "https://itunes.apple.com/search"
THUMBNAIL_SIZE, FULL_SIZE = "200x200bb", "600x600bb"
SQUARE_TOLERANCE = 0.02  # width and height may differ by 2 %
Kind = Literal["audiobook", "album"]
_KINDS: dict[Kind, dict[str, str]] = {
    "audiobook": {"media": "audiobook", "entity": "audiobook"},
    "album": {"media": "music", "entity": "album"},
}


class ITunesError(ServiceError):
    """A cover search failed. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class CoverCandidate:
    title: str
    artist: str
    year: str
    kind: Kind
    thumbnail: CoverArt  # small, for choosing
    image_url: str  # the full-size cover
    matches_title: bool  # the result's title contains every word of the wanted title


def title_words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def _extra_words(candidate: str, wanted: str) -> int | None:
    """How many words `candidate` has beyond those of `wanted`; None if it lacks one of them."""
    have, need = title_words(candidate), title_words(wanted)
    if not need or any(word not in have for word in need):
        return None
    return len(have) - len(need)


def is_square(info: ImageInfo) -> bool:
    return abs(info.width - info.height) <= SQUARE_TOLERANCE * max(info.width, info.height)


def _sized(url: str, size: str) -> str:
    return url.replace("100x100bb", size) if "100x100bb" in url else url


def _user_agent() -> str:
    try:
        return f"MP3Tagger/{metadata.version('mp3tagger')}"
    except metadata.PackageNotFoundError:
        return "MP3Tagger/dev"


class ITunes:
    def __init__(
        self,
        *,
        country: str = "de",
        transport: httpx.AsyncBaseTransport | None = None,
        min_interval: float = 3.0,  # Apple allows roughly 20 searches a minute
        max_retries: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._country = country
        self._search_http = PoliteClient(
            "iTunes",
            user_agent=_user_agent(),
            error=ITunesError,
            transport=transport,
            min_interval=min_interval,
            max_retries=max_retries,
            sleep=sleep,
            clock=clock,
        )
        # Artwork comes from a CDN without a request limit.
        self._image_http = PoliteClient(
            "Apple's image server",
            user_agent=_user_agent(),
            error=ITunesError,
            transport=transport,
            min_interval=0,
            max_retries=1,
            sleep=sleep,
            clock=clock,
        )

    async def aclose(self) -> None:
        await self._search_http.aclose()
        await self._image_http.aclose()

    async def _results(self, term: str, kind: Kind) -> list[dict]:
        params = {**_KINDS[kind], "term": term, "country": self._country, "limit": "12"}
        response = await self._search_http.get(API, params)
        return response.json().get("results", []) if response is not None else []

    async def _candidate(self, raw: dict, kind: Kind, wanted: str) -> CoverCandidate | None:
        """A candidate for one search result, or None if its artwork is unusable or not square."""
        name, art = raw.get("collectionName"), raw.get("artworkUrl100")
        if not name or not art:
            return None
        try:
            response = await self._image_http.get(_sized(art, THUMBNAIL_SIZE))
            if response is None:
                return None
            info = sniff_image(response.content)
        except ITunesError, ValueError:
            return None
        if not is_square(info):
            return None
        return CoverCandidate(
            title=name,
            artist=raw.get("artistName", ""),
            year=(raw.get("releaseDate") or "")[:4],
            kind=kind,
            thumbnail=CoverArt(response.content, info.mime),
            image_url=_sized(art, FULL_SIZE),
            matches_title=_extra_words(name, wanted) is not None,
        )

    async def _candidates(
        self, term: str, kind: Kind, wanted: str, limit: int
    ) -> list[CoverCandidate]:
        raw = (await self._results(term, kind))[: limit + 4]
        found = await asyncio.gather(*(self._candidate(r, kind, wanted) for r in raw))
        return [c for c in found if c is not None]

    async def search_covers(
        self, title: str, artist: str = "", limit: int = 6
    ) -> list[CoverCandidate]:
        """Square covers for `title` (by `artist`), best title match first.

        Audiobooks are searched first, albums only if no audiobook has the wanted title.
        """
        term = f"{title} {artist}".strip()
        found = await self._candidates(term, "audiobook", title, limit)
        if not found and artist:
            found = await self._candidates(title, "audiobook", title, limit)
        if not any(c.matches_title for c in found):
            seen = {c.image_url for c in found}
            found += [
                c
                for c in await self._candidates(term, "album", title, limit)
                if c.image_url not in seen
            ]
        ranked = sorted(
            enumerate(found),
            key=lambda item: (
                _extra_words(item[1].title, title) if item[1].matches_title else 10**6,
                item[0],  # the API's own order breaks ties
            ),
        )
        return [c for _, c in ranked][:limit]

    async def full_cover(self, candidate: CoverCandidate) -> CoverArt:
        """The candidate's full-size cover. Raises ITunesError if it cannot be used."""
        response = await self._image_http.get(candidate.image_url)
        if response is None:
            raise ITunesError("Apple no longer has this cover")
        try:
            info = sniff_image(response.content)
        except ValueError as exc:
            raise ITunesError(f"The cover image could not be used: {exc}") from exc
        if not is_square(info):
            raise ITunesError("The cover image is not square")
        return CoverArt(response.content, info.mime)
