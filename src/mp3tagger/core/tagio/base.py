"""Interface between the core and a concrete tag format backend."""

from pathlib import Path
from typing import Protocol

from mp3tagger.core.models import Track


class TagReader(Protocol):
    extensions: tuple[str, ...]

    def read(self, path: Path) -> Track:
        """Read a track. Must not raise for unreadable files: return a Track with `error` set."""
        ...
