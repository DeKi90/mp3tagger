"""AG Grid based, sortable, multi-selectable file list."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from nicegui import ui

from mp3tagger.core.models import Track


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
    Column("path", "Path", default_visible=False, width=300),
    Column("error", "Error", default_visible=False),
)

COLUMN_LABELS: dict[str, str] = {c.field: c.label for c in COLUMNS}
DEFAULT_VISIBLE: list[str] = [c.field for c in COLUMNS if c.default_visible]

SelectionHandler = Callable[[list[Path]], Awaitable[None] | None]


def track_row(track: Track) -> dict:
    return {
        "id": str(track.path),
        "filename": track.filename,
        **track.tags.as_dict(),
        "duration": track.info.duration or None,  # raw numbers; the columns format them
        "bitrate": track.info.bitrate or None,
        "sample_rate": track.info.sample_rate or None,
        "tag_version": track.tag_version,
        "path": str(track.path.parent),
        "error": track.error or "",
    }


class FileGrid:
    def __init__(self, on_selection: SelectionHandler | None = None) -> None:
        self._on_selection = on_selection
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
                "enableCellTextSelection": True,
            },
            auto_size_columns=False,
        ).classes("w-full h-full")
        self.grid.on("selectionChanged", self._selection_changed)

    def set_tracks(self, tracks: list[Track]) -> None:
        self.grid.options["rowData"] = [track_row(t) for t in tracks]
        self.grid.update()

    def set_visible_columns(self, visible: list[str]) -> None:
        shown = [c.field for c in COLUMNS if c.field in visible]
        hidden = [c.field for c in COLUMNS if c.field not in visible]
        self.grid.run_grid_method("setColumnsVisible", shown, True)
        self.grid.run_grid_method("setColumnsVisible", hidden, False)

    async def selected_paths(self) -> list[Path]:
        return [Path(row["id"]) for row in await self.grid.get_selected_rows()]

    async def _selection_changed(self, _event) -> None:
        if self._on_selection:
            result = self._on_selection(await self.selected_paths())
            if result is not None:
                await result
