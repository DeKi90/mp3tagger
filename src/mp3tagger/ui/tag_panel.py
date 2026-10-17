"""Editor for the tags of the selected file."""

from collections.abc import Callable
from dataclasses import fields

from nicegui import ui

from mp3tagger.core.models import FIELD_NAMES, YEAR_FORMATS, TagSet, Track, is_valid_year

LABELS = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album artist",
    "year": "Year",
    "track": "Track",
    "disc": "Disc",
    "genre": "Genre",
    "comment": "Comment",
    "composer": "Composer",
}
assert set(LABELS) == {f.name for f in fields(TagSet)}

DIRTY_PROPS = "bg-color=amber-1"  # highlights fields with unsaved changes


def format_info(track: Track) -> str:
    info = track.info
    parts = [track.tag_version or "no tag"]
    if info.bitrate:
        parts.append(f"{info.bitrate // 1000} kbps")
    if info.sample_rate:
        parts.append(f"{info.sample_rate} Hz")
    if info.duration:
        parts.append(f"{round(info.duration) // 60}:{round(info.duration) % 60:02d}")
    if info.size:
        parts.append(f"{info.size / 1_048_576:.1f} MB")
    if track.has_cover:
        parts.append("cover")
    return " · ".join(parts)


class TagPanel:
    def __init__(self, on_change: Callable[[str, str], None]) -> None:
        """`on_change(field, value)` is called when the user edits a field."""
        self._on_change = on_change
        self._updating = False  # True while we fill the inputs ourselves
        self._inputs: dict[str, ui.input] = {}
        with ui.column().classes("w-full gap-2 p-2"):
            self._message = ui.label().classes("text-grey")
            self._form = ui.column().classes("w-full gap-1")
            with self._form:
                self._filename = ui.label().classes("text-subtitle2 break-all")
                self._info = ui.label().classes("text-caption text-grey")
                for name in FIELD_NAMES:
                    self._inputs[name] = self._make_input(name)
        self.show_message("Select a file to edit its tags")

    def _make_input(self, name: str) -> ui.input:
        validation = {f"Expected {YEAR_FORMATS}": is_valid_year} if name == "year" else None
        return (
            ui.input(
                LABELS[name],
                validation=validation,
                on_change=lambda e, n=name: self._changed(n, e.value),
            )
            .props("dense outlined clearable hide-bottom-space")
            .classes("w-full")
        )

    def _changed(self, name: str, value: str | None) -> None:
        if self._updating:
            return
        self._on_change(name, value or "")

    def show_message(self, text: str) -> None:
        self._message.text = text
        self._message.set_visibility(True)
        self._form.set_visibility(False)

    def show_track(self, track: Track, tags: TagSet, dirty_fields: set[str]) -> None:
        """Show `tags` (original plus pending edits) of a single track."""
        if track.error:
            self.show_message(f"{track.filename} cannot be edited: {track.error}")
            return
        self._message.set_visibility(False)
        self._form.set_visibility(True)
        self._filename.text = track.filename
        self._info.text = format_info(track)
        self._updating = True
        try:
            for name, value in tags.as_dict().items():
                self._inputs[name].value = value
        finally:
            self._updating = False
        self.mark_dirty(dirty_fields)

    def mark_dirty(self, dirty_fields: set[str]) -> None:
        for name, input_ in self._inputs.items():
            if name in dirty_fields:
                input_.props(DIRTY_PROPS)
            else:
                input_.props(remove="bg-color")

    def set_enabled(self, enabled: bool) -> None:
        for input_ in self._inputs.values():
            input_.set_enabled(enabled)
