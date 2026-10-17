"""Pending-changes buffer: edits live here until saved, so undo never touches disk."""

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from mp3tagger.core.models import FIELD_NAMES, TagSet, Track

EditKey = tuple[frozenset[Path], str]


class EditBuffer:
    """Holds the loaded tracks plus per-track, per-field pending values.

    Undo is a stack of snapshots of the affected tracks' pending values. Consecutive edits of
    the same field on the same tracks (typing in an input) are coalesced into one undo step until
    `break_edit` is called (e.g. when the selection changes). Saving or discarding clears the
    undo stack, because earlier snapshots would no longer describe the files on disk.
    """

    def __init__(self) -> None:
        self._tracks: dict[Path, Track] = {}
        self._pending: dict[Path, dict[str, str]] = {}
        self._undo: list[dict[Path, dict[str, str]]] = []
        self._open_edit: EditKey | None = None

    def load(self, tracks: Iterable[Track]) -> None:
        self._tracks = {t.path: t for t in tracks}
        self._pending.clear()
        self._undo.clear()
        self._open_edit = None

    @property
    def paths(self) -> list[Path]:
        return list(self._tracks)

    def track(self, path: Path) -> Track:
        """The track as last read from disk (without pending edits)."""
        return self._tracks[path]

    def effective_tags(self, path: Path) -> TagSet:
        return replace(self._tracks[path].tags, **self._pending.get(path, {}))

    def pending(self, path: Path) -> dict[str, str]:
        return dict(self._pending.get(path, {}))

    def is_dirty(self, path: Path) -> bool:
        return path in self._pending

    def dirty_paths(self) -> list[Path]:
        return [p for p in self._tracks if p in self._pending]

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
            self._undo.append({p: dict(self._pending.get(p, {})) for p in changed})
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

    def break_edit(self) -> None:
        """End the current edit so the next change starts a new undo step."""
        self._open_edit = None

    def undo(self) -> list[Path]:
        """Revert the last edit step. Returns the affected paths."""
        if not self._undo:
            return []
        snapshot = self._undo.pop()
        for path, pending in snapshot.items():
            if pending:
                self._pending[path] = pending
            else:
                self._pending.pop(path, None)
        self._open_edit = None
        return list(snapshot)

    def discard(self, paths: Iterable[Path] | None = None) -> list[Path]:
        """Drop pending edits of `paths` (default: all). Returns the paths that were dirty."""
        targets = self.dirty_paths() if paths is None else [p for p in paths if p in self._pending]
        for path in targets:
            del self._pending[path]
        self._undo.clear()
        self._open_edit = None
        return targets

    def apply_saved(self, tracks: Iterable[Track]) -> None:
        """Replace tracks by their freshly re-read versions after a successful save."""
        for track in tracks:
            self._tracks[track.path] = track
            self._pending.pop(track.path, None)
        self._undo.clear()
        self._open_edit = None
