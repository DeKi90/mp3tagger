"""NiceGUI page layout and wiring."""

from pathlib import Path

from nicegui import run, ui

from mp3tagger.config import Config
from mp3tagger.core.library import scan_folder
from mp3tagger.core.models import Track
from mp3tagger.services.fs import PathOutsideRootsError, Sandbox
from mp3tagger.ui.dialogs.folder_browser import pick_folder
from mp3tagger.ui.file_grid import COLUMN_LABELS, DEFAULT_VISIBLE, FileGrid


def build_app(config: Config) -> None:
    sandbox = Sandbox(config.roots)

    @ui.page("/")
    def index() -> None:
        # Per-client state (not module globals) so several browsers/sessions stay independent.
        tracks: list[Track] = []
        folder: Path | None = None

        ui.query(".nicegui-content").classes("h-screen p-2 gap-2")

        with ui.row().classes("w-full items-center gap-4"):
            ui.label("MP3 tagger").classes("text-h6")
            ui.button("Open folder…", icon="folder_open", on_click=lambda: open_folder()).props(
                "unelevated"
            )
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

        grid = FileGrid(on_selection=lambda paths: update_status(len(paths)))

        def update_status(selected: int) -> None:
            broken = sum(1 for t in tracks if t.error)
            parts = [f"{len(tracks)} files", f"{selected} selected"]
            if broken:
                parts.append(f"{broken} unreadable")
            status.text = " · ".join(parts) if folder else ""

        async def open_folder() -> None:
            nonlocal tracks, folder
            chosen = await pick_folder(sandbox, folder)
            if chosen is None:
                return
            await load(chosen)

        async def load(path: Path) -> None:
            nonlocal tracks, folder
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
            folder = path
            grid.set_tracks(tracks)
            update_status(0)
            if not tracks:
                ui.notify("No MP3 files found", type="warning")
