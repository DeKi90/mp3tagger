"""Dialogs of the converters. Each one shows a live preview and returns its result only when
the user confirms; applying it is up to the caller."""

from collections.abc import Sequence
from pathlib import Path

from nicegui import ui

from mp3tagger.core.models import FIELD_NAMES, TagSet
from mp3tagger.core.numbering import number_tracks
from mp3tagger.core.patterns import (
    PatternError,
    compile_parse_pattern,
    format_values,
    parse_path,
)
from mp3tagger.core.rename import RenamePlan, plan_renames

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


def _column(name: str, label: str) -> dict:
    return {"name": name, "label": label, "field": name, "align": "left"}


def _preview_table() -> ui.table:
    table = ui.table(columns=[], rows=[], row_key="id", pagination=0)
    table.props("dense flat bordered virtual-scroll hide-bottom").classes("w-full")
    table.style("max-height: 22rem")
    return table


def _show(table: ui.table, columns: list[dict], rows: Sequence[dict]) -> None:
    table.columns = columns
    table.rows = [{"id": i, **row} for i, row in enumerate(rows[:MAX_PREVIEW_ROWS])]
    table.update()


def _note(total: int) -> str:
    return f" (preview shows the first {MAX_PREVIEW_ROWS})" if total > MAX_PREVIEW_ROWS else ""


async def _run(dialog: ui.dialog) -> object:
    result = await dialog
    dialog.delete()
    return result


def _footer(dialog: ui.dialog, apply_label: str) -> ui.button:
    """Cancel and apply buttons; returns the apply button. The caller submits via `submit`."""
    with ui.row().classes("w-full justify-end"):
        ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
        return ui.button(apply_label).props("unelevated")


def _pattern_input(default: str) -> ui.input:
    field = ui.input("Pattern", value=default).props("outlined dense autofocus clearable")
    field.classes("w-full")
    ui.label(PATTERN_HELP).classes("text-caption text-grey")
    return field


async def filename_to_tag(paths: Sequence[Path]) -> dict[Path, dict[str, str]] | None:
    """Read tags from file names. Returns {path: {field: value}} for the files that match."""
    result: dict[Path, dict[str, str]] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[56rem] max-w-full"):
        ui.label("Filename → Tag").classes("text-h6")
        pattern = _pattern_input("%artist% - %title%")
        ui.label(
            "Use / to read folder names too, e.g. %artist%/%album%/%track% - %title%. "
            "%ignore% skips a part."
        ).classes("text-caption text-grey")
        error = ui.label().classes("text-negative")
        summary = ui.label().classes("text-caption")
        table = _preview_table()
        apply = _footer(dialog, "Apply")

    def refresh() -> None:
        result.clear()
        try:
            compiled = compile_parse_pattern(pattern.value or "")
        except PatternError as exc:
            error.text, summary.text = str(exc), ""
            _show(table, [], [])
            apply.set_enabled(False)
            return
        error.text = ""
        parsed = [(path, parse_path(compiled, path)) for path in paths]
        result.update({path: values for path, values in parsed if values is not None})
        columns = [_column("file", "File"), *(_column(f, FIELD_LABELS[f]) for f in compiled.fields)]
        columns.append(_column("match", ""))
        rows = [
            {
                "file": path.name,
                **{f: (values or {}).get(f, "") for f in compiled.fields},
                "match": "" if values is not None else "no match",
            }
            for path, values in parsed
        ]
        _show(table, columns, rows)
        summary.text = f"{len(result)} of {len(paths)} files match{_note(len(rows))}"
        apply.set_enabled(bool(result))
        apply.text = f"Apply to {len(result)} file(s)"

    pattern.on_value_change(refresh)
    apply.on_click(lambda: dialog.submit(dict(result)))
    refresh()
    return await _run(dialog)  # type: ignore[return-value]


async def tag_to_filename(items: Sequence[tuple[Path, TagSet]]) -> list[RenamePlan] | None:
    """Rename files from their tags. Returns the plans (only "rename" ones will be applied)."""
    plans: list[RenamePlan] = []
    with ui.dialog() as dialog, ui.card().classes("w-[56rem] max-w-full"):
        ui.label("Tag → Filename").classes("text-h6")
        pattern = _pattern_input("%track:2% - %title%")
        ui.label(
            "The extension is kept and files stay in their folder. Illegal characters in tag "
            "values are replaced by _. Files are renamed on disk as soon as you apply."
        ).classes("text-caption text-grey")
        error = ui.label().classes("text-negative")
        summary = ui.label().classes("text-caption")
        table = _preview_table()
        apply = _footer(dialog, "Rename")

    def refresh() -> None:
        plans.clear()
        try:
            plans.extend(plan_renames(items, pattern.value or ""))
        except PatternError as exc:
            error.text, summary.text = str(exc), ""
            _show(table, [], [])
            apply.set_enabled(False)
            return
        error.text = ""
        columns = [_column("old", "Current name"), _column("new", "New name"), _column("note", "")]
        rows = []
        for plan in plans:
            note = {"unchanged": "unchanged", "rename": plan.message, "error": plan.message}
            rows.append(
                {
                    "old": plan.source.name,
                    "new": plan.target.name if plan.target else "—",
                    "note": ("⚠ " if plan.status == "error" else "") + note[plan.status],
                }
            )
        _show(table, columns, rows)
        count = {
            s: sum(1 for p in plans if p.status == s) for s in ("rename", "unchanged", "error")
        }
        incomplete = sum(1 for p in plans if p.status == "rename" and p.message.startswith("empty"))
        warning = f" · {incomplete} with an empty field" if incomplete else ""
        summary.text = (
            f"{count['rename']} to rename, {count['unchanged']} unchanged, "
            f"{count['error']} with problems (skipped){warning}{_note(len(rows))}"
        )
        apply.set_enabled(count["rename"] > 0)
        apply.text = f"Rename {count['rename']} file(s)"

    pattern.on_value_change(refresh)
    apply.on_click(lambda: dialog.submit(list(plans)))
    refresh()
    return await _run(dialog)  # type: ignore[return-value]


async def tag_to_tag(items: Sequence[tuple[Path, TagSet]]) -> dict[Path, dict[str, str]] | None:
    """Fill one field from a format of other fields. Returns {path: {field: new value}}."""
    result: dict[Path, dict[str, str]] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[56rem] max-w-full"):
        ui.label("Tag → Tag").classes("text-h6")
        target = ui.select(FIELD_LABELS, value="album_artist", label="Set field")
        target.props("outlined dense").classes("w-64")
        pattern = _pattern_input("%artist%")
        error = ui.label().classes("text-negative")
        summary = ui.label().classes("text-caption")
        table = _preview_table()
        apply = _footer(dialog, "Apply")

    def refresh() -> None:
        result.clear()
        field = target.value
        try:
            formatted = format_values(items, pattern.value or "")
        except PatternError as exc:
            error.text, summary.text = str(exc), ""
            _show(table, [], [])
            apply.set_enabled(False)
            return
        error.text = ""
        changed = 0
        rows = []
        for (path, tags), (_, new) in zip(items, formatted, strict=True):
            current = getattr(tags, field)
            changed += current != new.text
            result[path] = {field: new.text}
            rows.append({"file": path.name, "current": current, "new": new.text})
        columns = [
            _column("file", "File"),
            _column("current", f"{FIELD_LABELS[field]} now"),
            _column("new", f"{FIELD_LABELS[field]} new"),
        ]
        _show(table, columns, rows)
        empty = sum(1 for _, f in formatted if f.empty_fields)
        warning = f" · {empty} with an empty field" if empty else ""
        summary.text = f"{changed} of {len(items)} files change{warning}{_note(len(rows))}"
        apply.set_enabled(changed > 0)

    pattern.on_value_change(refresh)
    target.on_value_change(refresh)
    apply.on_click(lambda: dialog.submit(dict(result)))
    refresh()
    return await _run(dialog)  # type: ignore[return-value]


async def auto_number(paths: Sequence[Path]) -> dict[Path, dict[str, str]] | None:
    """Number the files in the given order. Returns {path: {"track": value}}."""
    result: dict[Path, dict[str, str]] = {}
    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label("Auto-number tracks").classes("text-h6")
        ui.label("Files are numbered in the order the file list currently shows them.").classes(
            "text-caption text-grey"
        )
        with ui.row().classes("items-center gap-4"):
            start = ui.number("First number", value=1, min=0, precision=0).props("outlined dense")
            width = ui.select(
                {0: "No padding", 2: "2 digits (01)", 3: "3 digits (001)"}, value=0, label="Digits"
            ).props("outlined dense")
            width.classes("w-44")
        restart = ui.checkbox("Start again in every folder", value=True)
        total = ui.checkbox("Also write the total (3/12)", value=False)
        summary = ui.label().classes("text-caption")
        table = _preview_table()
        apply = _footer(dialog, "Apply")

    def refresh() -> None:
        numbers = number_tracks(
            paths,
            start=int(start.value or 0),
            restart_per_folder=restart.value,
            total=total.value,
            width=int(width.value or 0),
        )
        result.clear()
        result.update({path: {"track": value} for path, value in numbers.items()})
        rows = [{"file": p.name, "folder": p.parent.name, "track": numbers[p]} for p in paths]
        columns = [_column("file", "File"), _column("folder", "Folder"), _column("track", "Track")]
        _show(table, columns, rows)
        summary.text = f"{len(paths)} files{_note(len(rows))}"

    for control in (start, width, restart, total):
        control.on_value_change(refresh)
    apply.on_click(lambda: dialog.submit(dict(result)))
    refresh()
    return await _run(dialog)  # type: ignore[return-value]
