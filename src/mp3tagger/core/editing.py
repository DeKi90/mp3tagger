"""Pending-changes buffer: edits live here until saved, so undo never touches disk."""

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from mp3tagger.core.models import (
    FIELD_NAMES,
    UNCHANGED,
    CoverArt,
    CoverChange,
    Edit,
    TagSet,
    Track,
)

EditKey = tuple[frozenset[Path], str]
# What a track had pending before an edit: (field values, cover change).
Snapshot = tuple[dict[str, str], CoverChange]


class EditBuffer:
    """Holds the loaded tracks plus per-track pending field values and cover changes.

    Undo is a stack of snapshots of the affected tracks' pending state. Consecutive edits of
    the same field on the same tracks (typing in an input) are coalesced into one undo step until
    `break_edit` is called (e.g. when the selection changes). Saving or discarding clears the
    undo stack, because earlier snapshots would no longer describe the files on disk.
    """

    def __init__(self) -> None:
        self._tracks: dict[Path, Track] = {}
        self._pending: dict[Path, dict[str, str]] = {}
        self._covers: dict[Path, CoverChange] = {}  # presence = pending change
        self._undo: list[dict[Path, Snapshot]] = []
        self._open_edit: EditKey | None = None

    def load(self, tracks: Iterable[Track]) -> None:
        self._tracks = {t.path: t for t in tracks}
        self._pending.clear()
        self._covers.clear()
        self._reset_history()

    @property
    def paths(self) -> list[Path]:
        return list(self._tracks)

    def track(self, path: Path) -> Track:
        """The track as last read from disk (without pending edits)."""
        return self._tracks[path]

    def effective_tags(self, path: Path) -> TagSet:
        return replace(self._tracks[path].tags, **self._pending.get(path, {}))

    def effective_has_cover(self, path: Path) -> bool:
        cover = self._covers.get(path, UNCHANGED)
        if cover is UNCHANGED:
            return self._tracks[path].has_cover
        return isinstance(cover, CoverArt)  # removed, or moved out to a file in the folder

    def pending(self, path: Path) -> dict[str, str]:
        """Pending field values (without the cover)."""
        return dict(self._pending.get(path, {}))

    def pending_cover(self, path: Path) -> CoverChange:
        return self._covers.get(path, UNCHANGED)

    def pending_edit(self, path: Path) -> Edit:
        return Edit(self.pending(path), self.pending_cover(path))

    def is_dirty(self, path: Path) -> bool:
        return path in self._pending or path in self._covers

    def dirty_paths(self) -> list[Path]:
        return [p for p in self._tracks if self.is_dirty(p)]

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def set_field(self, paths: Iterable[Path], field: str, value: str) -> list[Path]:
        """Set `field` on all `paths`. Returns the paths whose effective value changed."""
        if field not in FIELD_NAMES:
            raise KeyError(f"Unknown tag field: {field}")
        changed = [p for p in paths if getattr(self.effective_tags(p), field) != value]
        if not changed:
            return []
        key: EditKey = (frozenset(changed), field)
        if key != self._open_edit:
            self._push_snapshot(changed)
            self._open_edit = key
        for path in changed:
            pending = self._pending.setdefault(path, {})
            if value == getattr(self._tracks[path].tags, field):
                pending.pop(field, None)  # edited back to the original: no longer a change
            else:
                pending[field] = value
            if not pending:
                del self._pending[path]
        return changed

    def set_cover(self, paths: Iterable[Path], cover: CoverChange) -> list[Path]:
        """Replace (CoverArt), remove (None) or move out of the file (MoveCoverToFolder) the cover.

        Returns the paths that changed.
        """
        changed = [p for p in paths if self._cover_differs(p, cover)]
        if not changed:
            return []
        self._push_snapshot(changed)
        self._open_edit = None  # a cover change is always a step of its own
        for path in changed:
            if cover is None and not self._tracks[path].has_cover:
                self._covers.pop(path, None)  # removing what was only added: back to unchanged
            else:
                self._covers[path] = cover
        return changed

    def _cover_differs(self, path: Path, cover: CoverChange) -> bool:
        pending = self._covers.get(path, UNCHANGED)
        if pending is UNCHANGED:
            return cover is not None or self._tracks[path].has_cover
        return pending != cover

    def _push_snapshot(self, paths: list[Path]) -> None:
        self._undo.append(
            {p: (dict(self._pending.get(p, {})), self._covers.get(p, UNCHANGED)) for p in paths}
        )

    def break_edit(self) -> None:
        """End the current edit so the next change starts a new undo step."""
        self._open_edit = None

    def undo_open_edit(self, field: str) -> list[Path]:
        """Undo the edit currently in progress if it is on `field`. Returns the affected paths."""
        if self._open_edit is None or self._open_edit[1] != field:
            return []
        return self.undo()

    def undo(self) -> list[Path]:
        """Revert the last edit step. Returns the affected paths."""
        if not self._undo:
            return []
        snapshot = self._undo.pop()
        for path, (fields, cover) in snapshot.items():
            if fields:
                self._pending[path] = fields
            else:
                self._pending.pop(path, None)
            if cover is UNCHANGED:
                self._covers.pop(path, None)
            else:
                self._covers[path] = cover
        self._open_edit = None
        return list(snapshot)

    def discard(self, paths: Iterable[Path] | None = None) -> list[Path]:
        """Drop pending edits of `paths` (default: all). Returns the paths that were dirty."""
        targets = self.dirty_paths() if paths is None else [p for p in paths if self.is_dirty(p)]
        for path in targets:
            self._pending.pop(path, None)
            self._covers.pop(path, None)
        self._reset_history()
        return targets

    def apply_saved(self, tracks: Iterable[Track]) -> None:
        """Replace tracks by their freshly re-read versions after a successful save."""
        for track in tracks:
            self._tracks[track.path] = track
            self._pending.pop(track.path, None)
            self._covers.pop(track.path, None)
        self._reset_history()

    def _reset_history(self) -> None:
        self._undo.clear()
        self._open_edit = None
