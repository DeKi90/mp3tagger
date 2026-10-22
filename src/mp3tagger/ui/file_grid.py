"""AG Grid based, sortable, multi-selectable file list."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from nicegui import ui

from mp3tagger.core.models import TagSet, Track


@dataclass(frozen=True)
class Column:
    field: str
    label: str
    default_visible: bool = True
    width: int | None = None
    numeric: bool = False  # sort by leading integer ("10/12" > "2"), not as text
    formatter: str | None = None  # JS valueFormatter; the row value stays raw so sorting is numeric


DURATION_FORMATTER = (
    "(p) => p.value ? `${Math.floor(Math.round(p.value) / 60)}:"
    "${String(Math.round(p.value) % 60).padStart(2, '0')}` : ''"
)
BITRATE_FORMATTER = "(p) => p.value ? `${Math.round(p.value / 1000)} kbps` : ''"
HZ_FORMATTER = "(p) => p.value ? `${p.value} Hz` : ''"
NUMERIC_COMPARATOR = "(a, b) => (parseInt(a) || 0) - (parseInt(b) || 0)"

COLUMNS: tuple[Column, ...] = (
    Column("filename", "Filename", width=220),
    Column("title", "Title"),
    Column("artist", "Artist"),
    Column("album", "Album"),
    Column("album_artist", "Album artist", default_visible=False),
    Column("year", "Year", width=80, numeric=True),
    Column("track", "Track", width=80, numeric=True),
    Column("disc", "Disc", default_visible=False, width=80, numeric=True),
    Column("genre", "Genre", width=120),
    Column("comment", "Comment", default_visible=False),
    Column("composer", "Composer", default_visible=False),
    Column("duration", "Length", width=90, formatter=DURATION_FORMATTER),
    Column("bitrate", "Bitrate", default_visible=False, width=100, formatter=BITRATE_FORMATTER),
    Column("sample_rate", "Sample rate", default_visible=False, width=110, formatter=HZ_FORMATTER),
    Column("tag_version", "Tag", default_visible=False, width=100),
    Column("cover", "Cover", default_visible=False, width=80),
    Column("path", "Folder", default_visible=False, width=300),
    Column("error", "Error", default_visible=False),
)

COLUMN_LABELS: dict[str, str] = {c.field: c.label for c in COLUMNS}
DEFAULT_VISIBLE: list[str] = [c.field for c in COLUMNS if c.default_visible]

SelectionHandler = Callable[[list[Path]], Awaitable[None] | None]


def _folder(path: Path, base: Path | None) -> str:
    if base is not None:
        try:
            return path.parent.relative_to(base).as_posix().removeprefix(".")
        except ValueError:
            pass
    return str(path.parent)


def track_row(
    track: Track,
    tags: TagSet | None = None,
    dirty: bool = False,
    has_cover: bool | None = None,
    base: Path | None = None,
) -> dict:
    """Grid row for a track. `tags` are the effective tags (original plus pending edits). The
    folder is shown below `base`, the open folder."""
    return {
        "id": str(track.path),
        "dirty": dirty,
        "filename": track.filename,
        **(tags or track.tags).as_dict(),
        "duration": track.info.duration or None,  # raw numbers; the columns format them
        "bitrate": track.info.bitrate or None,
        "sample_rate": track.info.sample_rate or None,
        "tag_version": track.tag_version,
        "cover": "✓" if (track.has_cover if has_cover is None else has_cover) else "",
        "path": _folder(track.path, base),
        "error": track.error or "",
    }


DIRTY_ROW_CSS = ".row-dirty { font-style: italic; color: var(--q-warning) !important; }"


class FileGrid:
    def __init__(self, on_selection: SelectionHandler | None = None) -> None:
        self._on_selection = on_selection
        ui.add_css(DIRTY_ROW_CSS)
        self.grid = ui.aggrid(
            {
                "columnDefs": [
                    {
                        "field": c.field,
                        "headerName": c.label,
                        "hide": not c.default_visible,
                        **({"width": c.width} if c.width else {}),
                        **({":valueFormatter": c.formatter} if c.formatter else {}),
                        **({":comparator": NUMERIC_COMPARATOR} if c.numeric else {}),
                    }
                    for c in COLUMNS
                ],
                "defaultColDef": {"sortable": True, "resizable": True, "filter": False},
                "rowData": [],
                "rowSelection": {"mode": "multiRow", "enableClickSelection": True},
                ":getRowId": "(params) => params.data.id",
                "rowClassRules": {"row-dirty": "data.dirty"},
                "enableCellTextSelection": True,
            },
            auto_size_columns=False,
        ).classes("w-full h-full")
        self.grid.on("selectionChanged", self._selection_changed)

    def set_rows(self, rows: list[dict]) -> None:
        """Replace all rows. Sorting and column visibility are kept (no grid rebuild)."""
        self._mirror_rows(rows)
        self.grid.run_grid_method("setGridOption", "rowData", rows)

    def update_rows(self, rows: list[dict]) -> None:
        """Update existing rows in place. Selection and sorting are kept (no grid rebuild)."""
        by_id = {row["id"]: row for row in rows}
        known = self.grid.options["rowData"]
        for i, existing in enumerate(known):
            if existing["id"] in by_id:
                known[i] = by_id[existing["id"]]
        self.grid.run_grid_method("applyTransaction", {"update": rows})

    def _mirror_rows(self, rows: list[dict]) -> None:
        # `options` is an observable dict: assigning to it makes NiceGUI rebuild the whole grid on
        # the client, losing selection, sorting and column state. The rows are pushed to the
        # client with run_grid_method instead; this only keeps the server-side copy in sync (for
        # reading the rows back), so it bypasses the observer with the plain dict method.
        dict.__setitem__(self.grid.options, "rowData", rows)

    def set_visible_columns(self, visible: list[str]) -> None:
        shown = [c.field for c in COLUMNS if c.field in visible]
        hidden = [c.field for c in COLUMNS if c.field not in visible]
        self.grid.run_grid_method("setColumnsVisible", shown, True)
        self.grid.run_grid_method("setColumnsVisible", hidden, False)

    async def displayed_paths(self) -> list[Path]:
        """All files in the order the grid currently shows them (sorting and filtering applied)."""
        rows = await self.grid.get_client_data(method="filtered_sorted")
        return [Path(row["id"]) for row in rows]

    def select_paths(self, paths: list[Path]) -> None:
        """Select exactly these rows (after rows were replaced, which clears the selection)."""
        ids = json.dumps([str(p) for p in paths])
        self.grid.client.run_javascript(
            f"const ids = new Set({ids}); "
            f"getElement({self.grid.id}).api.forEachNode((n) => n.setSelected(ids.has(n.id)));"
        )

    async def selected_paths(self) -> list[Path]:
        return [Path(row["id"]) for row in await self.grid.get_selected_rows()]

    async def _selection_changed(self, _event) -> None:
        if self._on_selection:
            result = self._on_selection(await self.selected_paths())
            if result is not None:
                await result
