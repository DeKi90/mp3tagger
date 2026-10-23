"""Cover images that sit in the album folder next to the audio files."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mp3tagger.core.images import MAX_COVER_BYTES, sniff_image
from mp3tagger.core.models import CoverArt

# A de-facto convention, not a standard. In order of preference; matched case-insensitively.
FOLDER_COVER_STEMS = ("cover", "folder", "front", "album", "albumart")
FOLDER_COVER_SUFFIXES = (".jpg", ".jpeg", ".png")


@dataclass(frozen=True)
class FolderCover:
    name: str  # the file name as it is on disk, e.g. "Folder.JPG"
    cover: CoverArt


def find_folder_cover(folder: Path) -> FolderCover | None:
    """The folder's cover image, or None. Files that are not valid images are ignored."""
    try:
        files = {e.name.lower(): e for e in folder.iterdir() if e.is_file()}
    except OSError:
        return None
    for stem in FOLDER_COVER_STEMS:
        for suffix in FOLDER_COVER_SUFFIXES:
            entry = files.get(stem + suffix)
            if entry is None:
                continue
            try:
                if entry.stat().st_size > MAX_COVER_BYTES:
                    continue
                data = entry.read_bytes()
                info = sniff_image(data)
            except OSError, ValueError:
                continue
            return FolderCover(entry.name, CoverArt(data, info.mime))
    return None


def load_folder_covers(folders: Iterable[Path]) -> dict[Path, FolderCover | None]:
    return {folder: find_folder_cover(folder) for folder in folders}
