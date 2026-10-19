"""Scanning folders for audio files."""

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from mutagen import MutagenError

from mp3tagger.core.models import CoverArt, Track
from mp3tagger.core.tagio.base import TagReader
from mp3tagger.core.tagio.id3 import Id3Reader

ProgressCallback = Callable[[int, int], None]  # (done, total)


def find_files(folder: Path, extensions: tuple[str, ...], recursive: bool) -> Iterator[Path]:
    pattern = "**/*" if recursive else "*"
    for path in sorted(folder.glob(pattern)):
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in extensions:
            yield path


def scan_folder(
    folder: Path,
    *,
    recursive: bool = False,
    reader: TagReader | None = None,
    progress: ProgressCallback | None = None,
) -> list[Track]:
    """Read all supported files in `folder`. Unreadable files are returned with `error` set."""
    reader = reader or Id3Reader()
    paths = list(find_files(folder, reader.extensions, recursive))
    tracks = []
    for done, path in enumerate(paths, start=1):
        tracks.append(reader.read(path))
        if progress:
            progress(done, len(paths))
    return tracks


def load_covers(
    paths: Iterable[Path], reader: TagReader | None = None
) -> tuple[dict[Path, CoverArt | None], dict[Path, str]]:
    """Read the covers of `paths`. Returns (covers, errors); a bad file does not stop the rest."""
    reader = reader or Id3Reader()
    covers: dict[Path, CoverArt | None] = {}
    errors: dict[Path, str] = {}
    for path in paths:
        try:
            covers[path] = reader.read_cover(path)
        except (MutagenError, OSError) as exc:
            errors[path] = str(exc) or type(exc).__name__
    return covers, errors
