"""Editor for the tags of the selected file."""

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import fields

from nicegui import ui

from mp3tagger.core.batch import MergedCover, MergedTags
from mp3tagger.core.images import MAX_COVER_BYTES, sniff_image
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


def _toggle_prop(element: ui.element, prop: str, on: bool) -> None:
    if on:
        element.props(prop)
    else:
        element.props(remove=prop.split("=")[0])


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


REJECTED_IMAGE = f"Image rejected: JPEG or PNG, at most {MAX_COVER_BYTES // 1024 // 1024} MB"


def describe_cover(data: bytes) -> str:
    try:
        info = sniff_image(data)
    except ValueError:
        return "Unrecognised image"
    kind = info.mime.removeprefix("image/").upper()
    return f"{kind} · {info.width}×{info.height} · {len(data) / 1024:.0f} KB"


class TagPanel:
    def __init__(
        self,
        on_change: Callable[[str, str], None],
        on_cover_upload: Callable[[str, bytes], Awaitable[None]],
        on_cover_extract: Callable[[], None],
        on_cover_folder_action: Callable[[], Awaitable[None]],
        on_cover_remove: Callable[[], Awaitable[None]],
    ) -> None:
        """`on_change(field, value)` is called when the user edits a field; the `on_cover_*`
        callbacks when the user adds/replaces, extracts, moves to/embeds from the folder or
        removes the cover."""
        self._on_change = on_change
        self._on_cover_upload = on_cover_upload
        self._updating = False  # True while we fill the inputs ourselves
        self._inputs: dict[str, ui.input] = {}
        with ui.column().classes("w-full gap-2 p-2"):
            self._message = ui.label().classes("text-grey")
            self._form = ui.column().classes("w-full gap-1")
            with self._form:
                self._heading = ui.label().classes("text-subtitle2 break-all")
                self._info = ui.label().classes("text-caption text-grey")
                self._build_cover_section(on_cover_extract, on_cover_folder_action, on_cover_remove)
                for name in FIELD_NAMES:
                    self._inputs[name] = self._make_input(name)
        self.show_message("Select a file to edit its tags")

    def _build_cover_section(
        self,
        on_extract: Callable[[], None],
        on_folder_action: Callable[[], Awaitable[None]],
        on_remove: Callable[[], Awaitable[None]],
    ) -> None:
        with ui.column().classes("w-full items-center gap-1"):
            self._cover_image = ui.image().classes("w-48 h-48 rounded border bg-grey-2")
            self._cover_image.props("fit=contain")
            self._cover_placeholder = ui.icon("image", size="6rem").classes("text-grey-5")
            self._cover_caption = ui.label().classes("text-caption text-grey text-center")
            with ui.row().classes("gap-1"):
                self._cover_set = ui.button(on_click=lambda: self._upload.run_method("pickFiles"))
                self._cover_extract = ui.button("Extract", icon="download", on_click=on_extract)
                self._cover_folder_action = ui.button(on_click=on_folder_action)
                with self._cover_folder_action:
                    self._folder_action_tooltip = ui.tooltip()
                self._set_folder_action(to_folder=True)
                self._cover_remove = ui.button("Remove", icon="delete", on_click=on_remove)
                for button in (
                    self._cover_set,
                    self._cover_extract,
                    self._cover_folder_action,
                    self._cover_remove,
                ):
                    button.props("flat dense no-caps")
            # The upload element is hidden; the "Add/Replace" button opens its file chooser.
            self._upload = (
                ui.upload(
                    on_upload=self._handle_upload,
                    on_rejected=lambda: ui.notify(REJECTED_IMAGE, type="negative"),
                    auto_upload=True,
                    max_file_size=MAX_COVER_BYTES,
                )
                .props("accept=.jpg,.jpeg,.png")
                .classes("hidden")
            )

    def _set_folder_action(self, *, to_folder: bool) -> None:
        """The button moves an embedded cover to the folder, or embeds the folder image."""
        button = self._cover_folder_action
        if to_folder:
            button.text, button.icon = "To folder", "drive_file_move"
            self._folder_action_tooltip.text = (
                "Write the cover as an image file in the folder and remove it from the file"
            )
        else:
            button.text, button.icon = "From folder", "move_to_inbox"
            self._folder_action_tooltip.text = "Embed the folder image into the files"

    async def _handle_upload(self, event) -> None:
        data = await event.file.read()
        self._upload.reset()
        await self._on_cover_upload(event.file.name, data)

    def show_cover(
        self, merged: MergedCover | None, *, modified: bool = False, note: str = ""
    ) -> None:
        """Show the cover of the selection. `None` means it was not loaded (large selection).

        A cover that is only a folder image is shown too, marked as such. It cannot be moved or
        removed (nothing is embedded); instead the folder button embeds it into the files, and a
        new cover can still be added.
        """
        image_src = None
        embedded = True  # whether the shown cover is embedded (so it can be moved or removed)
        if merged is None:
            caption, set_label = "Cover not shown for large selections", "Set cover"
        elif merged.state == "none":
            caption, set_label = "No embedded cover or folder image", "Add cover"
        elif merged.state == "mixed":
            caption, set_label = "Covers differ between the files", "Replace all"
        else:
            shown = merged.shown
            assert shown is not None
            image_src = (
                f"data:{shown.cover.mime};base64,{base64.b64encode(shown.cover.data).decode()}"
            )
            caption, set_label = describe_cover(shown.cover.data), "Replace"
            if shown.folder_file:
                caption += f" · folder image ({shown.folder_file})"
                set_label, embedded = "Add cover", False
        if modified:
            caption += " · modified"
        if note:
            caption += f" · {note}"
        if image_src:
            self._cover_image.set_source(image_src)
        self._cover_image.set_visibility(image_src is not None)
        self._cover_placeholder.set_visibility(image_src is None)
        self._cover_caption.text = caption
        self._cover_set.text, self._cover_set.icon = set_label, "upload"
        self._cover_extract.set_enabled(image_src is not None)
        self._cover_folder_action.set_enabled(image_src is not None)
        self._set_folder_action(to_folder=embedded)
        removable = (merged is None or merged.state != "none") and embedded
        self._cover_remove.set_enabled(removable)

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

    def show(self, heading: str, info: str, merged: MergedTags, dirty_fields: set[str]) -> None:
        """Show the merged tags of one or more tracks (differing fields read `<keep>`)."""
        self._message.set_visibility(False)
        self._form.set_visibility(True)
        self._heading.text = heading
        self._info.text = info
        self._updating = True
        try:
            for name, value in merged.values.items():
                self._inputs[name].value = value
        finally:
            self._updating = False
        self._sync_browser_text(merged.values)
        self.mark_state(dirty_fields, merged.mixed)

    def _sync_browser_text(self, values: dict[str, str]) -> None:
        """Make the browser show `values` even where it holds different text for an input.

        NiceGUI's input keeps what the user typed in local state and only follows changes of the
        server-side value. Setting a value equal to the last one the server knew (restoring
        "Band" after the user typed `<keep>` over it, or showing the saved text again) sends
        nothing, so the old text would stay. Set the component's local text directly instead.
        """
        texts = {self._inputs[name].id: value for name, value in values.items()}
        self._form.client.run_javascript(
            f"for (const [id, text] of Object.entries({json.dumps(texts)})) "
            "{ const input = getElement(id); if (input) input.inputValue = text; }"
        )

    def mark_state(self, dirty_fields: set[str], mixed_fields: frozenset[str]) -> None:
        """Highlight fields with unsaved changes and grey out fields that differ between files."""
        for name, input_ in self._inputs.items():
            _toggle_prop(input_, "bg-color=amber-1", name in dirty_fields)
            _toggle_prop(input_, "input-class=text-grey-7", name in mixed_fields)

    def set_enabled(self, enabled: bool) -> None:
        for input_ in self._inputs.values():
            input_.set_enabled(enabled)
        self._upload.set_enabled(enabled)
        self._cover_set.set_enabled(enabled)
        if enabled:
            return  # extract/remove depend on the shown cover: show_cover() sets them
        self._cover_extract.set_enabled(False)
        self._cover_folder_action.set_enabled(False)
        self._cover_remove.set_enabled(False)
