"""Server-side folder picker (browsers do not expose real paths)."""

from pathlib import Path

from nicegui import ui

from mp3tagger.services.fs import Sandbox


async def pick_folder(sandbox: Sandbox, start: Path | None = None) -> Path | None:
    """Show a folder picker confined to the sandbox roots. Returns None if cancelled."""
    current = sandbox.resolve(start) if start else sandbox.roots[0]

    with ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
        ui.label("Open folder").classes("text-h6")
        location = ui.label().classes("text-caption break-all")
        with ui.scroll_area().classes("w-full h-80 border rounded"):
            listing = ui.column().classes("w-full gap-0")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button("Open", on_click=lambda: dialog.submit(current)).props("unelevated")

    def show(path: Path) -> None:
        nonlocal current
        directory = sandbox.list_dir(path)
        current = directory.path
        location.text = str(current)
        listing.clear()
        with listing:
            if directory.parent:
                _entry("..", directory.parent, "arrow_upward")
            for sub in directory.subdirs:
                _entry(sub.name, sub, "folder")
            if not directory.subdirs and not directory.parent:
                ui.label("No subfolders").classes("text-grey p-2")

    def _entry(name: str, target: Path, icon: str) -> None:
        with ui.item(on_click=lambda: show(target)).classes("w-full"):
            with ui.item_section().props("avatar"):
                ui.icon(icon)
            with ui.item_section():
                ui.item_label(name)

    show(current)
    result = await dialog
    dialog.delete()
    return result
