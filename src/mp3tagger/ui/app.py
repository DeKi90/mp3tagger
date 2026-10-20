"""NiceGUI page layout and wiring."""

from pathlib import Path

from nicegui import events, run, ui

from mp3tagger.config import Config
from mp3tagger.core.batch import KEEP, ShownCover, merge_covers, merge_tags
from mp3tagger.core.editing import EditBuffer
from mp3tagger.core.folder_cover import FolderCover, load_folder_covers
from mp3tagger.core.images import EXTENSIONS, FOLDER_COVER_NAMES, sniff_image
from mp3tagger.core.library import load_covers, scan_folder
from mp3tagger.core.lookup import LocalFile, scan_discs
from mp3tagger.core.models import UNCHANGED, CoverArt, MoveCoverToFolder, TagSet
from mp3tagger.core.musicbrainz import MusicBrainz
from mp3tagger.core.rename import RenameError, apply_renames
from mp3tagger.core.saving import find_folder_cover_conflicts, write_changes
from mp3tagger.core.tagio.base import SaveOptions
from mp3tagger.core.tagio.id3 import Id3Reader, Id3Writer
from mp3tagger.services.fs import PathOutsideRootsError, Sandbox
from mp3tagger.ui.dialogs import converters, transforms
from mp3tagger.ui.dialogs.confirm import confirm
from mp3tagger.ui.dialogs.folder_browser import pick_folder
from mp3tagger.ui.dialogs.lookup import lookup_dialog
from mp3tagger.ui.file_grid import COLUMN_LABELS, DEFAULT_VISIBLE, FileGrid, track_row
from mp3tagger.ui.tag_panel import TagPanel, format_info

# Above this many selected files the cover is not loaded for display (it would read every file).
MAX_COVER_PREVIEW = 200

VERSION_CHOICES = {"keep": "Keep ID3v2 version", 3: "ID3v2.3", 4: "ID3v2.4"}

# Browsers would otherwise open their "save page" dialog on Ctrl/Cmd+S.
SUPPRESS_BROWSER_SAVE = """
<script>
window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') e.preventDefault();
});
</script>
"""


def build_app(config: Config, musicbrainz: MusicBrainz | None = None) -> None:
    """Register the page. `musicbrainz` is injectable for tests; by default one client is shared
    by all sessions, so MusicBrainz's request limit holds for the whole process."""
    sandbox = Sandbox(config.roots)
    reader, writer = Id3Reader(), Id3Writer()
    shared: list[MusicBrainz] = [musicbrainz] if musicbrainz else []

    def musicbrainz_client() -> MusicBrainz:
        if not shared:  # created on first use, inside the running event loop
            shared.append(MusicBrainz(contact=config.contact))
        return shared[0]

    @ui.page("/")
    def index() -> None:
        # Per-client state (not module globals) so several browsers/sessions stay independent.
        buffer = EditBuffer()
        folder: Path | None = None
        selected: list[Path] = []
        unload_guard_active = False
        covers: dict[Path, CoverArt | None] = {}  # covers as on disk, loaded on demand
        folder_covers: dict[Path, FolderCover | None] = {}  # folder images, per folder
        shown_cover: ShownCover | None = None  # the single common cover currently displayed
        cover_request = 0  # lets a newer refresh_cover() supersede an older, slower one

        ui.add_head_html(SUPPRESS_BROWSER_SAVE)
        ui.query(".nicegui-content").classes("h-screen p-2 gap-2 flex-nowrap")

        # --- toolbars ---------------------------------------------------------------------
        with ui.row().classes("w-full items-center gap-4"):
            ui.label("MP3 tagger").classes("text-h6")
            # Handlers are defined further down, hence the lambdas (resolved at click time).
            open_button = ui.button("Open folder…", icon="folder_open")
            open_button.on_click(lambda: open_folder())
            open_button.props("unelevated")
            recursive = ui.checkbox("Include subfolders", value=True)
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
            lookup_button = ui.button("Look up", icon="cloud_download", on_click=lambda: lookup())
            lookup_button.props("outline")
            convert_button = ui.button("Convert", icon="transform").props("outline")
            with convert_button, ui.menu():
                ui.menu_item("Filename → Tag…", on_click=lambda: convert_filename_to_tag())
                ui.menu_item("Tag → Filename…", on_click=lambda: convert_tag_to_filename())
                ui.menu_item("Tag → Tag…", on_click=lambda: convert_tag_to_tag())
                ui.menu_item("Auto-number tracks…", on_click=lambda: convert_auto_number())
                ui.separator()
                ui.menu_item("Change case…", on_click=lambda: convert_case())
                ui.menu_item("Find and replace…", on_click=lambda: convert_find_replace())
            ui.space()
            version_select = (
                ui.select(VERSION_CHOICES, value="keep", label="Save as")
                .props("dense outlined")
                .classes("min-w-48")
            )
            write_v1 = ui.checkbox("Also write ID3v1")
        controls = [
            open_button,
            save_button,
            undo_button,
            revert_button,
            lookup_button,
            convert_button,
        ]

        # --- grid + tag panel -------------------------------------------------------------
        with ui.splitter(value=70).classes("w-full flex-grow min-h-0") as splitter:
            with splitter.before:
                grid = FileGrid(on_selection=lambda paths: on_selection(paths))
            with splitter.after:
                panel = TagPanel(
                    on_change=lambda field, value: on_panel_change(field, value),
                    on_cover_upload=lambda name, data: add_cover(name, data),
                    on_cover_extract=lambda: extract_cover(),
                    on_cover_folder_action=lambda: cover_folder_action(),
                    on_cover_remove=lambda: remove_cover(),
                )

        ui.keyboard(on_key=lambda e: on_key(e), ignore=[])

        # --- state -> view ----------------------------------------------------------------
        def row(path: Path) -> dict:
            return track_row(
                buffer.track(path),
                buffer.effective_tags(path),
                buffer.is_dirty(path),
                buffer.effective_has_cover(path),
            )

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

        async def refresh_cover() -> None:
            """Show the cover of the selection, loading covers from disk where not yet known."""
            nonlocal shown_cover, cover_request
            cover_request += 1
            mine = cover_request
            editable = editable_paths()
            if not editable:
                return
            pending = [buffer.pending_cover(p) for p in editable]
            modified = any(c is not UNCHANGED for c in pending)
            moves = {c.filename for c in pending if isinstance(c, MoveCoverToFolder)}
            note = f"{', '.join(sorted(moves))} is written on save" if moves else ""
            if len(editable) > MAX_COVER_PREVIEW:
                shown_cover = None
                panel.show_cover(None, modified=modified, note=note)
                return
            missing = [
                p for p in editable if buffer.pending_cover(p) is UNCHANGED and p not in covers
            ]
            if missing:
                loaded, errors = await run.io_bound(load_covers, missing, reader)
                covers.update(loaded)
                if mine != cover_request:  # the selection changed while we were reading
                    return
                for path, error in list(errors.items())[:3]:
                    ui.notify(f"Cannot read cover of {path.name}: {error}", type="warning")
            embedded: list[CoverArt | None] = []
            for path, change in zip(editable, pending, strict=True):
                if change is UNCHANGED:
                    embedded.append(covers.get(path))
                else:  # a move takes the picture out of the file, like a removal
                    embedded.append(change if isinstance(change, CoverArt) else None)
            # Files without an embedded cover fall back to the image in their folder.
            folders = {p.parent for p, cover in zip(editable, embedded, strict=True) if not cover}
            unknown_folders = [f for f in folders if f not in folder_covers]
            if unknown_folders:
                folder_covers.update(await run.io_bound(load_folder_covers, unknown_folders))
                if mine != cover_request:
                    return
            effective: list[ShownCover | None] = []
            for path, cover in zip(editable, embedded, strict=True):
                if cover:
                    effective.append(ShownCover(cover))
                elif folder_image := folder_covers.get(path.parent):
                    effective.append(ShownCover(folder_image.cover, folder_image.name))
                else:
                    effective.append(None)
            merged = merge_covers(effective)
            shown_cover = merged.shown
            panel.show_cover(merged, modified=modified, note=note)

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
            lookup_button.set_enabled(bool(editable_paths()))
            convert_button.set_enabled(bool(editable_paths()))
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
        async def on_selection(paths: list[Path]) -> None:
            nonlocal selected
            selected = [p for p in paths if p in set(buffer.paths)]
            buffer.break_edit()
            refresh_panel()
            refresh_status()
            await refresh_cover()

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

        async def undo() -> None:
            refresh_rows(buffer.undo())
            refresh_panel()
            refresh_status()
            await refresh_cover()

        # --- online lookup ----------------------------------------------------------------
        async def lookup() -> None:
            editable = editable_paths()
            scan = await run.io_bound(scan_discs, editable, reader)  # reads the MCDI frames
            tags = {p: buffer.effective_tags(p) for p in editable}
            files = [
                LocalFile(p, buffer.track(p).info.duration, tags[p].track, tags[p].disc)
                for p in editable
            ]
            first = tags[editable[0]]
            result = await lookup_dialog(
                musicbrainz_client(), files, scan, first.artist, first.album
            )
            if result is None:
                return
            changed = buffer.set_fields(result.changes)
            if result.cover is not None:
                changed += buffer.set_cover(list(result.paired), result.cover)
            after_bulk_edit(sorted(set(changed)), "MusicBrainz")
            await refresh_cover()

        # --- converters -------------------------------------------------------------------
        def tags_of(paths: list[Path]) -> list[tuple[Path, TagSet]]:
            return [(p, buffer.effective_tags(p)) for p in paths]

        def after_bulk_edit(changed: list[Path], what: str) -> None:
            refresh_rows(changed)
            refresh_panel()
            refresh_status()
            if changed:
                ui.notify(f"{what}: {len(changed)} file(s) modified. Save to write them.")

        async def convert_filename_to_tag() -> None:
            changes = await converters.filename_to_tag(editable_paths())
            if changes:
                after_bulk_edit(buffer.set_fields(changes), "Filename → Tag")

        async def convert_tag_to_tag() -> None:
            changes = await converters.tag_to_tag(tags_of(editable_paths()))
            if changes:
                after_bulk_edit(buffer.set_fields(changes), "Tag → Tag")

        async def convert_case() -> None:
            changes = await transforms.change_case(tags_of(editable_paths()))
            if changes:
                after_bulk_edit(buffer.set_fields(changes), "Change case")

        async def convert_find_replace() -> None:
            changes = await transforms.find_replace(tags_of(editable_paths()))
            if changes:
                after_bulk_edit(buffer.set_fields(changes), "Find and replace")

        async def convert_auto_number() -> None:
            wanted = set(editable_paths())
            shown = await grid.displayed_paths()  # sorted/filtered the way the user sees it
            ordered = [p for p in shown if p in wanted] or editable_paths()
            changes = await converters.auto_number(ordered)
            if changes:
                after_bulk_edit(buffer.set_fields(changes), "Auto-number")

        async def convert_tag_to_filename() -> None:
            plans = await converters.tag_to_filename(tags_of(editable_paths()))
            if plans is None:
                return
            set_busy(True)  # the paths change under the buffer; nothing may be edited meanwhile
            try:
                mapping = await run.io_bound(apply_renames, plans)
            except RenameError as exc:
                ui.notify(str(exc), type="negative", close_button=True)
                return
            finally:
                set_busy(False)
            follow_renames(mapping)
            ui.notify(f"Renamed {len(mapping)} file(s)", type="positive")

        def follow_renames(mapping: dict[Path, Path]) -> None:
            """Make the state follow files that were renamed on disk."""
            nonlocal selected
            if not mapping:
                return
            buffer.rename_paths(mapping)
            cached = {mapping.get(p, p): cover for p, cover in covers.items()}
            covers.clear()
            covers.update(cached)
            selected = [mapping.get(p, p) for p in selected]
            grid.set_rows([row(p) for p in buffer.paths])  # replacing rows clears the selection
            grid.select_paths(selected)
            refresh_panel()
            refresh_status()

        # --- cover art --------------------------------------------------------------------
        async def apply_cover(cover: CoverArt | None) -> None:
            editable = editable_paths()
            changed = buffer.set_cover(editable, cover)
            refresh_rows(changed)
            refresh_status()
            await refresh_cover()

        async def add_cover(name: str, data: bytes) -> None:
            if not editable_paths():
                return
            try:
                info = sniff_image(data)  # judged by content, whatever the file is called
            except ValueError as exc:
                ui.notify(f"{name}: {exc}", type="negative")
                return
            await apply_cover(CoverArt(data, info.mime))

        async def remove_cover() -> None:
            await apply_cover(None)

        async def cover_folder_action() -> None:
            """Embedded cover -> image file in the folder; folder image -> embedded cover."""
            shown = shown_cover
            editable = editable_paths()
            if shown is None or not editable:
                return
            if shown.folder_file:  # only a folder image: embed it into the files
                await apply_cover(shown.cover)
                return
            filename = FOLDER_COVER_NAMES[shown.cover.mime]
            conflicts = await run.io_bound(
                find_folder_cover_conflicts, editable, filename, shown.cover
            )
            for message in list(conflicts.values())[:3]:
                ui.notify(f"{message}: skipped", type="warning")
            movable = [p for p in editable if p.parent not in conflicts]
            changed = buffer.set_cover(movable, MoveCoverToFolder(shown.cover, filename))
            refresh_rows(changed)
            refresh_status()
            await refresh_cover()

        def extract_cover() -> None:
            shown = shown_cover
            if shown is None:
                return
            cover = shown.cover
            editable = editable_paths()
            stem = editable[0].stem if len(editable) == 1 else "cover"
            ui.download.content(cover.data, f"{stem}{EXTENSIONS[cover.mime]}", cover.mime)

        async def revert() -> None:
            n = len(buffer.dirty_paths())
            if n and await confirm(f"Discard unsaved changes in {n} file(s)?", ok="Discard"):
                refresh_rows(buffer.discard())
                refresh_panel()
                refresh_status()
                await refresh_cover()

        async def save() -> None:
            changes = {p: buffer.pending_edit(p) for p in buffer.dirty_paths()}
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
            for track in saved:
                covers.pop(track.path, None)  # reload from the file that was just written
                folder_covers.pop(track.path.parent, None)  # a cover file may have been written
            refresh_rows([t.path for t in saved])
            refresh_panel()
            set_busy(False)
            await refresh_cover()
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
            covers.clear()
            folder_covers.clear()
            grid.set_rows([row(p) for p in buffer.paths])
            refresh_panel()
            refresh_status()
            if not tracks:
                ui.notify("No MP3 files found", type="warning")

        refresh_status()
