"""Track numbering for a list of files."""

from collections.abc import Sequence
from pathlib import Path


def number_tracks(
    paths: Sequence[Path],
    *,
    start: int = 1,
    restart_per_folder: bool = False,
    total: bool = False,
    width: int = 0,
) -> dict[Path, str]:
    """Track numbers for `paths`, in the order given.

    `restart_per_folder` starts again at `start` in every folder (an album per folder); `total`
    appends the number of tracks ("3/12"), counted per folder when restarting; `width` pads with
    zeros ("03").
    """
    if start < 0:
        raise ValueError("The first number cannot be negative")
    groups: dict[Path | None, list[Path]] = {}
    for path in paths:
        groups.setdefault(path.parent if restart_per_folder else None, []).append(path)
    result: dict[Path, str] = {}
    for members in groups.values():
        count = len(members)
        for offset, path in enumerate(members):
            number = str(start + offset).zfill(width)
            result[path] = f"{number}/{str(count).zfill(width)}" if total else number
    return result
