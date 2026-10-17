"""Yes/no confirmation dialog."""

from nicegui import ui


async def confirm(message: str, *, ok: str = "OK", cancel: str = "Cancel") -> bool:
    with ui.dialog() as dialog, ui.card():
        ui.label(message)
        with ui.row().classes("w-full justify-end"):
            ui.button(cancel, on_click=lambda: dialog.submit(False)).props("flat")
            ui.button(ok, on_click=lambda: dialog.submit(True)).props("unelevated color=negative")
    result = await dialog
    dialog.delete()
    return bool(result)
