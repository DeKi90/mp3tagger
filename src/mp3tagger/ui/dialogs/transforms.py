"""Dialogs of the bulk transforms (case, find/replace): live preview, result on confirm."""

from collections.abc import Sequence
from pathlib import Path

from nicegui import ui

from mp3tagger.core.models import TagSet
from mp3tagger.core.transforms import (
    FieldChange,
    FindReplace,
    TransformError,
    changes_by_path,
    compile_find_replace,
    convert_case,
    plan_field_changes,
)
from mp3tagger.ui.dialogs.parts import (
    FIELD_LABELS,
    column,
    fields_select,
    footer,
    note,
    preview_table,
    run_dialog,
    show_rows,
)

CASE_STYLES = {
    "upper": "UPPER CASE",
    "lower": "lower case",
    "title": "Title Case",
    "sentence": "Sentence case",
}
DEFAULT_FIELDS = ["title", "artist", "album"]
CHANGE_COLUMNS = [
    column("file", "File"),
    column("field", "Field"),
    column("old", "Before"),
    column("new", "After"),
]


def _show_changes(
    table: ui.table, summary: ui.label, apply: ui.button, changes: list[FieldChange], files: int
) -> None:
    """Fill the preview with one row per changed value and update the summary/apply button."""
    rows = [
        {"file": c.path.name, "field": FIELD_LABELS[c.field], "old": c.old, "new": c.new}
        for c in changes
    ]
    show_rows(table, CHANGE_COLUMNS, rows)
    affected = len({c.path for c in changes})
    summary.text = f"{len(changes)} value(s) change in {affected} of {files} files{note(len(rows))}"
    apply.set_enabled(bool(changes))
    apply.text = f"Apply to {affected} file(s)" if changes else "Apply"


async def change_case(
    items: Sequence[tuple[Path, TagSet]],
) -> dict[Path, dict[str, str]] | None:
    """Change the case of chosen fields. Returns {path: {field: new value}}."""
    result: dict[Path, dict[str, str]] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[56rem] max-w-full"):
        ui.label("Change case").classes("text-h6")
        fields = fields_select(DEFAULT_FIELDS)
        style = ui.select(CASE_STYLES, value="title", label="Style").props("outlined dense")
        style.classes("w-64")
        small = ui.checkbox("Keep small words (a, of, the, …) in lower case", value=True)
        ui.label(
            "Title case follows English rules; the first and last word are always capitalised."
        ).classes("text-caption text-grey")
        summary = ui.label().classes("text-caption")
        table = preview_table()
        apply = footer(dialog, "Apply")

    def refresh() -> None:
        small.set_enabled(style.value == "title")
        changes = plan_field_changes(
            items,
            fields.value,
            lambda v: convert_case(v, style.value, keep_small_words=small.value),
        )
        result.clear()
        result.update(changes_by_path(changes))
        _show_changes(table, summary, apply, changes, len(items))

    for control in (fields, style, small):
        control.on_value_change(refresh)
    apply.on_click(lambda: dialog.submit(dict(result)))
    refresh()
    return await run_dialog(dialog)  # type: ignore[return-value]


async def find_replace(
    items: Sequence[tuple[Path, TagSet]],
) -> dict[Path, dict[str, str]] | None:
    """Find and replace in chosen fields. Returns {path: {field: new value}}."""
    result: dict[Path, dict[str, str]] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[56rem] max-w-full"):
        ui.label("Find and replace").classes("text-h6")
        fields = fields_select(DEFAULT_FIELDS)
        with ui.row().classes("w-full no-wrap gap-4"):
            find = ui.input("Find").props("outlined dense autofocus clearable").classes("grow")
            replace = ui.input("Replace with").props("outlined dense clearable").classes("grow")
        with ui.row().classes("items-center gap-4"):
            regex = ui.checkbox("Regular expression")
            match_case = ui.checkbox("Match case")
            whole = ui.checkbox("Match the whole field")
        ui.label(
            "Regular expressions: use \\1 or \\g<name> in the replacement for matched groups."
        ).classes("text-caption text-grey")
        error = ui.label().classes("text-negative")
        summary = ui.label().classes("text-caption")
        table = preview_table()
        apply = footer(dialog, "Apply")

    def refresh() -> None:
        result.clear()
        spec = FindReplace(
            find.value or "",
            replace.value or "",
            regex=regex.value,
            match_case=match_case.value,
            whole_field=whole.value,
        )
        try:
            changes = plan_field_changes(
                items, fields.value, lambda v: compile_find_replace(spec)(v).value
            )
        except TransformError as exc:
            error.text = str(exc) if find.value else ""  # no complaint before typing anything
            summary.text = ""
            show_rows(table, [], [])
            apply.set_enabled(False)
            return
        error.text = ""
        result.update(changes_by_path(changes))
        _show_changes(table, summary, apply, changes, len(items))

    for control in (fields, find, replace, regex, match_case, whole):
        control.on_value_change(refresh)
    apply.on_click(lambda: dialog.submit(dict(result)))
    refresh()
    return await run_dialog(dialog)  # type: ignore[return-value]
