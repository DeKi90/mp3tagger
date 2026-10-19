"""Writing pending changes to disk. Blocking; call from a worker thread."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from mutagen import MutagenError

from mp3tagger.core.models import CoverArt, Edit, MoveCoverToFolder, Track
from mp3tagger.core.tagio.base import SaveOptions, TagReader, TagWriter


def write_cover_file(target: Path, cover: CoverArt) -> None:
    """Write `cover` to `target` atomically. An identical existing file is fine; a different one
    is never overwritten (raises ValueError)."""
    if target.exists():
        if target.is_file() and target.read_bytes() == cover.data:
            return
        raise ValueError(f"{target.parent.name}/{target.name} already exists with other content")
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(cover.data)
    temporary.replace(target)


def find_folder_cover_conflicts(
    paths: Iterable[Path], filename: str, cover: CoverArt
) -> dict[Path, str]:
    """Folders (of `paths`) where `filename` exists with content other than `cover`."""
    conflicts: dict[Path, str] = {}
    for folder in {p.parent for p in paths}:
        target = folder / filename
        try:
            if target.exists() and not (target.is_file() and target.read_bytes() == cover.data):
                conflicts[folder] = f"{folder.name}/{filename} already exists with other content"
        except OSError as exc:
            conflicts[folder] = f"{folder.name}/{filename}: {exc.strerror or exc}"
    return conflicts


@dataclass(frozen=True)
class SaveResult:
    path: Path
    track: Track | None = None  # the file re-read after writing
    error: str | None = None


def write_changes(
    edits: Mapping[Path, Edit],
    writer: TagWriter,
    reader: TagReader,
    options: SaveOptions | None = None,
) -> list[SaveResult]:
    """Write each file's edit, then re-read it so the UI shows what is really on disk.

    One failing file does not stop the others.
    """
    options = options or SaveOptions()
    results = []
    for path, edit in edits.items():
        try:
            cover = edit.cover
            if isinstance(cover, MoveCoverToFolder):
                # The image file goes first: if anything fails afterwards the embedded cover is
                # still there, and a retry finds the identical file and carries on.
                write_cover_file(path.parent / cover.filename, cover.cover)
                cover = None  # then remove the embedded picture
            writer.write(path, edit.fields, options, cover)
        except (MutagenError, OSError, ValueError) as exc:
            results.append(SaveResult(path, error=str(exc) or type(exc).__name__))
            continue
        track = reader.read(path)
        results.append(SaveResult(path, track=track, error=track.error))
    return results
