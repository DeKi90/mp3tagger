"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    roots: tuple[Path, ...] = field(default_factory=lambda: (Path.home() / "Music",))
    host: str = "127.0.0.1"
    port: int = 8080

    @classmethod
    def from_env(cls) -> Config:
        """Build a config from MP3TAGGER_ROOTS (os.pathsep separated), _HOST and _PORT."""
        defaults = cls()
        raw_roots = os.environ.get("MP3TAGGER_ROOTS")
        roots = (
            tuple(Path(r).expanduser().resolve() for r in raw_roots.split(os.pathsep) if r)
            if raw_roots
            else defaults.roots
        )
        return cls(
            roots=roots,
            host=os.environ.get("MP3TAGGER_HOST", defaults.host),
            port=int(os.environ.get("MP3TAGGER_PORT", defaults.port)),
        )
