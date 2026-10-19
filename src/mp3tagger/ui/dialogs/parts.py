"""Building blocks shared by the converter and transform dialogs."""

from collections.abc import Sequence

from nicegui import ui

from mp3tagger.core.models import FIELD_NAMES

MAX_PREVIEW_ROWS = 500  # the preview is a sample for checking the pattern, not a full listing

FIELD_LABELS = {
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
assert set(FIELD_LABELS) == set(FIELD_NAMES)

PATTERN_HELP = (
    "Fields: " + ", ".join(f"%{name}%" for name in FIELD_NAMES) + ". "
    "%track:2% pads with zeros (03). %albumartist% also works."
)


def column(name: str, label: str) -> dict:
    return {"name": name, "label": label, "field": name, "align": "left"}


def preview_table() -> ui.table:
    table = ui.table(columns=[], rows=[], row_key="id", pagination=0)
    table.props("dense flat bordered virtual-scroll hide-bottom").classes("w-full")
    table.style("max-height: 22rem")
    return table


def show_rows(table: ui.table, columns: list[dict], rows: Sequence[dict]) -> None:
    table.columns = columns
    table.rows = [{"id": i, **row} for i, row in enumerate(rows[:MAX_PREVIEW_ROWS])]
    table.update()


def note(total: int) -> str:
    return f" (preview shows the first {MAX_PREVIEW_ROWS})" if total > MAX_PREVIEW_ROWS else ""


async def run_dialog(dialog: ui.dialog) -> object:
    result = await dialog
    dialog.delete()
    return result


def footer(dialog: ui.dialog, apply_label: str) -> ui.button:
    """Cancel and apply buttons; returns the apply button. The caller submits via `submit`."""
    with ui.row().classes("w-full justify-end"):
        ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
        return ui.button(apply_label).props("unelevated")


def pattern_input(default: str) -> ui.input:
    field = ui.input("Pattern", value=default).props("outlined dense autofocus clearable")
    field.classes("w-full")
    ui.label(PATTERN_HELP).classes("text-caption text-grey")
    return field


def fields_select(default: list[str]) -> ui.select:
    """Multi-select of the tag fields an operation applies to."""
    select = ui.select(FIELD_LABELS, multiple=True, value=default, label="Fields")
    select.props("outlined dense use-chips").classes("w-full")
    return select
