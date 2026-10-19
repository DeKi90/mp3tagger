"""Interface between the core and a concrete tag format backend."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from mp3tagger.core.models import UNCHANGED, CoverArt, CoverChange, Track


@dataclass(frozen=True)
class SaveOptions:
    # Target ID3v2 version. None keeps the file's current version (2.3 for files without a tag).
    version: Literal[3, 4] | None = None
    write_v1: bool = False  # additionally write (or update) an ID3v1 tag


class TagReader(Protocol):
    extensions: tuple[str, ...]

    def read_cover(self, path: Path) -> CoverArt | None:
        """The cover picture, or None. Raises MutagenError/OSError if the file is unreadable."""
        ...

    def read(self, path: Path) -> Track:
        """Read a track. Must not raise for unreadable files: return a Track with `error` set."""
        ...


class TagWriter(Protocol):
    def write(
        self,
        path: Path,
        changes: Mapping[str, str],
        options: SaveOptions,
        cover: CoverChange = UNCHANGED,
    ) -> None:
        """Apply `changes` (field name -> new value, "" removes the field) in place.

        `cover` replaces (CoverArt) or removes (None) the cover; UNCHANGED leaves it as it is.

        Fields not mentioned and frames the model does not know about are preserved.
        Raises MutagenError, OSError or ValueError on failure.
        """
        ...
