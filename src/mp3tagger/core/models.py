"""Format-agnostic data model for tracks and their tags."""

import re
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class TagSet:
    """The normalised, editable tag fields of a track. Empty string means "not set"."""

    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track: str = ""
    disc: str = ""
    genre: str = ""
    comment: str = ""
    composer: str = ""

    def as_dict(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


FIELD_NAMES: tuple[str, ...] = tuple(f.name for f in fields(TagSet))

_YEAR = re.compile(r"\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?")
YEAR_FORMATS = "YYYY, YYYY-MM or YYYY-MM-DD"


def is_valid_year(value: str) -> bool:
    """Empty (field removed) or a date of the form YYYY, YYYY-MM or YYYY-MM-DD."""
    return not value or _YEAR.fullmatch(value) is not None


@dataclass(frozen=True)
class AudioInfo:
    """Technical, read-only properties of the audio stream."""

    duration: float = 0.0  # seconds
    bitrate: int = 0  # bits per second
    sample_rate: int = 0  # Hz
    channels: int = 0
    size: int = 0  # file size in bytes


@dataclass(frozen=True)
class Track:
    path: Path
    tags: TagSet = field(default_factory=TagSet)
    info: AudioInfo = field(default_factory=AudioInfo)
    tag_version: str = ""  # e.g. "ID3v2.3", "ID3v1.1"; empty if the file has no tag
    has_cover: bool = False
    error: str | None = None  # set when the file could not be read

    @property
    def filename(self) -> str:
        return self.path.name
