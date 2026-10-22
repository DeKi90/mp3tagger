"""MusicBrainz lookups (releases by CD identifier, CD table of contents or text) and cover art
from the Cover Art Archive.

MusicBrainz asks clients to send at most about one request per second and to identify
themselves with a User-Agent; "busy" answers (HTTP 503) are normal and mean "try again later".
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Literal

import httpx

from mp3tagger.core.discid import Toc
from mp3tagger.core.http import PoliteClient, ServiceError
from mp3tagger.core.images import sniff_image
from mp3tagger.core.models import CoverArt

API = "https://musicbrainz.org/ws/2"
COVER_ART = "https://coverartarchive.org"
RELEASE_INCLUDES = "artist-credits+labels+recordings+release-groups"
Source = Literal["disc id", "toc", "search", "id"]


class MusicBrainzError(ServiceError):
    """A lookup failed. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class ReleaseTrack:
    position: int  # on its medium
    title: str
    artist: str
    seconds: float | None


@dataclass(frozen=True)
class Medium:
    position: int  # which disc of the release
    title: str
    format: str
    track_count: int
    tracks: tuple[ReleaseTrack, ...]  # empty in search results, which carry no track lists
    disc_ids: frozenset[str]


@dataclass(frozen=True)
class Release:
    id: str
    title: str
    artist: str
    date: str  # as MusicBrainz has it: "2006", "2006-05", "2006-05-01" or ""
    country: str
    label: str
    barcode: str
    media: tuple[Medium, ...]
    has_front_cover: bool
    source: Source

    @property
    def year(self) -> str:
        return self.date[:4]

    @property
    def track_count(self) -> int:
        return sum(m.track_count for m in self.media)

    @property
    def has_track_lists(self) -> bool:
        return all(m.tracks for m in self.media)

    def medium_for(self, disc_id: str | None, track_count: int) -> Medium | None:
        """The disc of this release that `disc_id` identifies; failing that, the only disc with
        `track_count` tracks (a fuzzy match or a text search). None if it is not clear."""
        if disc_id:
            for medium in self.media:
                if disc_id in medium.disc_ids:
                    return medium
        candidates = [m for m in self.media if m.track_count == track_count]
        return candidates[0] if len(candidates) == 1 else None


def _credit(parts: list[dict[str, Any]] | None) -> str:
    return "".join(f"{p.get('name', '')}{p.get('joinphrase', '')}" for p in parts or [])


def _medium(data: dict[str, Any], release_artist: str) -> Medium:
    tracks = []
    for t in data.get("tracks", []):
        length = t.get("length") or (t.get("recording") or {}).get("length")
        tracks.append(
            ReleaseTrack(
                position=int(t.get("position") or 0),
                title=t.get("title", ""),
                artist=_credit(t.get("artist-credit")) or release_artist,
                seconds=length / 1000 if length else None,
            )
        )
    return Medium(
        position=int(data.get("position") or 1),
        title=data.get("title") or "",
        format=data.get("format") or "",
        track_count=int(data.get("track-count") or len(tracks)),
        tracks=tuple(tracks),
        disc_ids=frozenset(d["id"] for d in data.get("discs", []) if "id" in d),
    )


def parse_release(data: dict[str, Any], source: Source) -> Release:
    artist = _credit(data.get("artist-credit"))
    labels = [li["label"]["name"] for li in data.get("label-info", []) if li.get("label")]
    return Release(
        id=data["id"],
        title=data.get("title", ""),
        artist=artist,
        date=data.get("date") or "",
        country=data.get("country") or "",
        label=", ".join(dict.fromkeys(labels)),
        barcode=data.get("barcode") or "",
        media=tuple(_medium(m, artist) for m in data.get("media", [])),
        has_front_cover=bool((data.get("cover-art-archive") or {}).get("front")),
        source=source,
    )


def _user_agent(contact: str) -> str:
    try:
        version = metadata.version("mp3tagger")
    except metadata.PackageNotFoundError:
        version = "dev"
    return f"MP3Tagger/{version}" + (f" ( {contact} )" if contact else "")


class MusicBrainz:
    def __init__(
        self,
        *,
        contact: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        min_interval: float = 1.1,
        max_retries: int = 4,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = PoliteClient(
            "MusicBrainz",
            user_agent=_user_agent(contact),
            error=MusicBrainzError,
            transport=transport,
            min_interval=min_interval,
            max_retries=max_retries,
            sleep=sleep,
            clock=clock,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response | None:
        return await self._http.get(url, params)

    async def _releases(self, path: str, source: Source, params: dict[str, str]) -> list[Release]:
        response = await self._get(f"{API}/{path}", {"fmt": "json", **params})
        if response is None:
            return []
        return [parse_release(r, source) for r in response.json().get("releases", [])]

    async def releases_for_disc_id(self, disc_id: str) -> list[Release]:
        """Releases of the CD with this exact Disc ID (empty if MusicBrainz does not know it)."""
        return await self._releases(
            f"discid/{disc_id}", "disc id", {"inc": RELEASE_INCLUDES, "cdstubs": "no"}
        )

    async def releases_for_toc(self, toc: Toc) -> list[Release]:
        """Releases whose table of contents is similar (fuzzy; the caller must check them)."""
        params = {"toc": toc.musicbrainz_toc(), "inc": RELEASE_INCLUDES, "cdstubs": "no"}
        return await self._releases("discid/-", "toc", params)

    async def search(self, artist: str, album: str, limit: int = 10) -> list[Release]:
        """Text search. Results have no track lists; use `release` for the one the user picks."""
        terms = [
            f'{field}:"{_lucene(value)}"'
            for field, value in (("release", album), ("artist", artist))
            if value.strip()
        ]
        if not terms:
            raise MusicBrainzError("Enter an artist or an album to search for")
        return await self._releases(
            "release", "search", {"query": " AND ".join(terms), "limit": str(limit)}
        )

    async def release(self, release_id: str, source: Source = "id") -> Release:
        """One release with its track lists."""
        response = await self._get(
            f"{API}/release/{release_id}", {"fmt": "json", "inc": RELEASE_INCLUDES}
        )
        if response is None:
            raise MusicBrainzError("MusicBrainz does not know this release")
        return parse_release(response.json(), source)

    async def front_cover(self, release: Release) -> CoverArt | None:
        """The release's front cover (500 px) from the Cover Art Archive, or None."""
        if not release.has_front_cover:
            return None
        response = await self._get(f"{COVER_ART}/release/{release.id}/front-500")
        if response is None:
            return None
        try:
            info = sniff_image(response.content)
        except ValueError as exc:
            raise MusicBrainzError(f"The cover image could not be used: {exc}") from exc
        return CoverArt(response.content, info.mime)


def _lucene(value: str) -> str:
    """Make `value` safe inside a quoted Lucene phrase."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
