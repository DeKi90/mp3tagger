"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    roots: tuple[Path, ...] = field(default_factory=lambda: (Path.home() / "Music",))
    host: str = "127.0.0.1"
    port: int = 8080
    # Shown to MusicBrainz in the User-Agent so they can reach whoever runs this (an e-mail
    # address or a URL). They ask for it but it is optional.
    contact: str = ""
    # Country of the iTunes store searched for cover art (two letters); decides which releases
    # and titles are found, e.g. "de" for German audiobooks.
    cover_country: str = "de"

    @classmethod
    def from_env(cls) -> Config:
        """Build a config from MP3TAGGER_ROOTS (os.pathsep separated) and MP3TAGGER_HOST, _PORT,
        _CONTACT and _COVER_COUNTRY."""
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
            contact=os.environ.get("MP3TAGGER_CONTACT", defaults.contact),
            cover_country=os.environ.get("MP3TAGGER_COVER_COUNTRY", defaults.cover_country),
        )
