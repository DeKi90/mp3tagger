"""Writing pending changes to disk. Blocking; call from a worker thread."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mutagen import MutagenError

from mp3tagger.core.models import Track
from mp3tagger.core.tagio.base import SaveOptions, TagReader, TagWriter


@dataclass(frozen=True)
class SaveResult:
    path: Path
    track: Track | None = None  # the file re-read after writing
    error: str | None = None


def write_changes(
    changes: Mapping[Path, Mapping[str, str]],
    writer: TagWriter,
    reader: TagReader,
    options: SaveOptions | None = None,
) -> list[SaveResult]:
    """Write each file's changes, then re-read it so the UI shows what is really on disk.

    One failing file does not stop the others.
    """
    options = options or SaveOptions()
    results = []
    for path, file_changes in changes.items():
        try:
            writer.write(path, file_changes, options)
        except (MutagenError, OSError, ValueError) as exc:
            results.append(SaveResult(path, error=str(exc) or type(exc).__name__))
            continue
        track = reader.read(path)
        results.append(SaveResult(path, track=track, error=track.error))
    return results
