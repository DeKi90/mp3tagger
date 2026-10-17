"""NiceGUI page layout and wiring."""

from pathlib import Path

from nicegui import events, run, ui

from mp3tagger.config import Config
from mp3tagger.core.batch import KEEP, merge_tags
from mp3tagger.core.editing import EditBuffer
from mp3tagger.core.library import scan_folder
from mp3tagger.core.saving import write_changes
from mp3tagger.core.tagio.base import SaveOptions
from mp3tagger.core.tagio.id3 import Id3Reader, Id3Writer
from mp3tagger.services.fs import PathOutsideRootsError, Sandbox
from mp3tagger.ui.dialogs.confirm import confirm
from mp3tagger.ui.dialogs.folder_browser import pick_folder
from mp3tagger.ui.file_grid import COLUMN_LABELS, DEFAULT_VISIBLE, FileGrid, track_row
from mp3tagger.ui.tag_panel import TagPanel, format_info

VERSION_CHOICES = {"keep": "Keep ID3v2 version", 3: "ID3v2.3", 4: "ID3v2.4"}

# Browsers would otherwise open their "save page" dialog on Ctrl/Cmd+S.
SUPPRESS_BROWSER_SAVE = """
<script>
window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') e.preventDefault();
});
</script>
"""


def build_app(config: Config) -> None:
    sandbox = Sandbox(config.roots)
    reader, writer = Id3Reader(), Id3Writer()

    @ui.page("/")
    def index() -> None:
        # Per-client state (not module globals) so several browsers/sessions stay independent.
        buffer = EditBuffer()
        folder: Path | None = None
        selected: list[Path] = []
        unload_guard_active = False

        ui.add_head_html(SUPPRESS_BROWSER_SAVE)
        ui.query(".nicegui-content").classes("h-screen p-2 gap-2 flex-nowrap")

        # --- toolbars ---------------------------------------------------------------------
        with ui.row().classes("w-full items-center gap-4"):
            ui.label("MP3 tagger").classes("text-h6")
            # Handlers are defined further down, hence the lambdas (resolved at click time).
            open_button = ui.button("Open folder…", icon="folder_open")
            open_button.on_click(lambda: open_folder())
            open_button.props("unelevated")
            recursive = ui.checkbox("Include subfolders")
            ui.select(
                COLUMN_LABELS,
                multiple=True,
                value=DEFAULT_VISIBLE,
                label="Columns",
                on_change=lambda e: grid.set_visible_columns(e.value),
            ).props("dense outlined use-chips").classes("min-w-64")
            ui.space()
            status = ui.label().classes("text-caption")

        with ui.row().classes("w-full items-center gap-4"):
            save_button = ui.button("Save", icon="save", on_click=lambda: save())
            save_button.props("unelevated")
            undo_button = ui.button("Undo", icon="undo", on_click=lambda: undo())
            undo_button.props("outline")
            revert_button = ui.button("Revert all", icon="restore", on_click=lambda: revert())
            revert_button.props("outline")
            ui.space()
            version_select = (
                ui.select(VERSION_CHOICES, value="keep", label="Save as")
                .props("dense outlined")
                .classes("min-w-48")
            )
            write_v1 = ui.checkbox("Also write ID3v1")
        controls = [open_button, save_button, undo_button, revert_button]

        # --- grid + tag panel -------------------------------------------------------------
        with ui.splitter(value=70).classes("w-full flex-grow min-h-0") as splitter:
            with splitter.before:
                grid = FileGrid(on_selection=lambda paths: on_selection(paths))
            with splitter.after:
                panel = TagPanel(on_change=lambda field, value: on_panel_change(field, value))

        ui.keyboard(on_key=lambda e: on_key(e), ignore=[])

        # --- state -> view ----------------------------------------------------------------
        def row(path: Path) -> dict:
            return track_row(buffer.track(path), buffer.effective_tags(path), buffer.is_dirty(path))

        def refresh_rows(paths: list[Path]) -> None:
            if paths:
                grid.update_rows([row(p) for p in paths])

        def editable_paths() -> list[Path]:
            """The selected files that could be read and so can be edited."""
            return [p for p in selected if not buffer.track(p).error]

        def pending_fields(paths: list[Path]) -> set[str]:
            return {field for p in paths for field in buffer.pending(p)}

        def refresh_panel() -> None:
            editable = editable_paths()
            if not selected:
                panel.show_message("Select a file to edit its tags")
            elif not editable and len(selected) == 1:
                path = selected[0]
                panel.show_message(f"{path.name} cannot be edited: {buffer.track(path).error}")
            elif not editable:
                panel.show_message("None of the selected files can be edited")
            else:
                merged = merge_tags([buffer.effective_tags(p) for p in editable])
                if len(selected) == 1:
                    track = buffer.track(editable[0])
                    heading, info = track.filename, format_info(track)
                else:
                    heading = f"{len(selected)} files selected"
                    skipped = len(selected) - len(editable)
                    info = f"{KEEP} fields differ between files and stay unchanged unless edited."
                    if skipped:
                        info += f" {skipped} unreadable file(s) are skipped."
                panel.show(heading, info, merged, pending_fields(editable))

        def refresh_status() -> None:
            nonlocal unload_guard_active
            dirty = len(buffer.dirty_paths())
            broken = sum(1 for p in buffer.paths if buffer.track(p).error)
            parts = [f"{len(buffer.paths)} files", f"{len(selected)} selected"]
            if dirty:
                parts.append(f"{dirty} modified")
            if broken:
                parts.append(f"{broken} unreadable")
            status.text = " · ".join(parts) if folder else ""
            save_button.text = f"Save ({dirty})" if dirty else "Save"
            save_button.set_enabled(bool(dirty))
            revert_button.set_enabled(bool(dirty))
            undo_button.set_enabled(buffer.can_undo)
            if bool(dirty) != unload_guard_active:  # warn before closing the tab with unsaved edits
                unload_guard_active = bool(dirty)
                handler = "(e) => { e.preventDefault(); e.returnValue = ''; }"
                ui.run_javascript(f"window.onbeforeunload = {handler if dirty else 'null'}")

        def set_busy(busy: bool) -> None:
            for control in controls:
                control.set_enabled(not busy)
            panel.set_enabled(not busy)
            if not busy:
                refresh_status()  # restores the state-dependent enabled flags

        # --- actions ----------------------------------------------------------------------
        def on_selection(paths: list[Path]) -> None:
            nonlocal selected
            selected = [p for p in paths if p in set(buffer.paths)]
            buffer.break_edit()
            refresh_panel()
            refresh_status()

        def on_panel_change(field: str, value: str) -> None:
            editable = editable_paths()
            if not editable:
                return
            if len(editable) > 1 and value == KEEP:
                # The user put `<keep>` back: drop the edit in progress. If there is none, the
                # re-render below shows the actual values again.
                refresh_rows(buffer.undo_open_edit(field))
                refresh_panel()
            else:
                refresh_rows(buffer.set_field(editable, field, value))
                mixed = merge_tags([buffer.effective_tags(p) for p in editable]).mixed
                panel.mark_state(pending_fields(editable), mixed)
            refresh_status()

        def undo() -> None:
            refresh_rows(buffer.undo())
            refresh_panel()
            refresh_status()

        async def revert() -> None:
            n = len(buffer.dirty_paths())
            if n and await confirm(f"Discard unsaved changes in {n} file(s)?", ok="Discard"):
                refresh_rows(buffer.discard())
                refresh_panel()
                refresh_status()

        async def save() -> None:
            changes = {p: buffer.pending(p) for p in buffer.dirty_paths()}
            if not changes:
                return
            version = version_select.value
            options = SaveOptions(
                version=None if version == "keep" else version, write_v1=write_v1.value
            )
            set_busy(True)  # edits during the write would be lost when the result is applied
            busy = ui.notification(f"Saving {len(changes)} file(s)…", spinner=True, timeout=None)
            try:
                results = await run.io_bound(write_changes, changes, writer, reader, options)
            finally:
                busy.dismiss()
            saved = [r.track for r in results if r.track and not r.error]
            failed = [r for r in results if r.error]
            buffer.apply_saved(saved)
            refresh_rows([t.path for t in saved])
            refresh_panel()
            set_busy(False)
            if saved:
                ui.notify(f"Saved {len(saved)} file(s)", type="positive")
            for result in failed[:5]:
                ui.notify(f"{result.path.name}: {result.error}", type="negative", close_button=True)
            if len(failed) > 5:
                ui.notify(f"…and {len(failed) - 5} more failed", type="negative")

        async def on_key(event: events.KeyEventArguments) -> None:
            is_save_shortcut = event.key == "s" and (event.modifiers.ctrl or event.modifiers.meta)
            if event.action.keydown and is_save_shortcut and save_button.enabled:
                await save()

        async def open_folder() -> None:
            n = len(buffer.dirty_paths())
            if n and not await confirm(
                f"{n} file(s) have unsaved changes. Discard them and open another folder?",
                ok="Discard",
            ):
                return
            chosen = await pick_folder(sandbox, folder)
            if chosen is not None:
                await load(chosen)

        async def load(path: Path) -> None:
            nonlocal folder, selected
            try:
                path = sandbox.resolve(path)
            except PathOutsideRootsError as exc:
                ui.notify(str(exc), type="negative")
                return
            busy = ui.notification(f"Scanning {path}…", spinner=True, timeout=None)
            try:
                tracks = await run.io_bound(scan_folder, path, recursive=recursive.value)
            finally:
                busy.dismiss()
            folder, selected = path, []
            buffer.load(tracks)
            grid.set_rows([row(p) for p in buffer.paths])
            refresh_panel()
            refresh_status()
            if not tracks:
                ui.notify("No MP3 files found", type="warning")

        refresh_status()
