"""The "Look up on MusicBrainz" dialog.

When the files carry a CD table of contents (MCDI frame) the CD is looked up by it at once; a
search by name is always available. The user picks a release, sees which release track would go
onto which file (with the length differences as a check), chooses what to import, and confirms.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nicegui import ui

from mp3tagger.core.http import ServiceError
from mp3tagger.core.itunes import CoverCandidate, ITunes
from mp3tagger.core.lookup import (
    IMPORT_FIELDS,
    LENGTH_TOLERANCE,
    DiscScan,
    LocalFile,
    build_changes,
    lengths_agree,
    match_tracks,
    plausible_for_toc,
)
from mp3tagger.core.models import CoverArt
from mp3tagger.core.musicbrainz import Medium, MusicBrainz, Release
from mp3tagger.ui.dialogs.parts import (
    FIELD_LABELS,
    column,
    data_url,
    display_name,
    footer,
    preview_table,
    show_rows,
)

COVER_NONE = "none"
COVER_ARCHIVE = "caa"
COVER_ITUNES = "itunes"
SELECTED_CARD = "outline: 3px solid var(--q-primary); outline-offset: -3px;"
DEFAULT_FIELDS = ("title", "track", "album", "artist", "album_artist", "year")
FOUND_BY = {"disc id": "CD identifier", "toc": "similar CD", "search": "search", "id": "selected"}
Level = Literal["info", "ok", "warning", "error"]
LEVEL_CLASSES = {
    "info": "text-grey-8",
    "ok": "text-positive",
    "warning": "text-warning",
    "error": "text-negative",
}


@dataclass(frozen=True)
class LookupResult:
    changes: dict[Path, dict[str, str]]  # {path: {field: new value}}
    paired: tuple[Path, ...]  # the files a release track was found for
    cover: CoverArt | None


def _minutes(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


class LookupDialog:
    def __init__(
        self,
        client: MusicBrainz,
        covers: ITunes,
        files: list[LocalFile],
        scan: DiscScan,
        artist: str,
        album: str,
        base: Path | None = None,
    ) -> None:
        self._client, self._covers, self._files, self._scan = client, covers, files, scan
        self._base = base
        self._candidates: list[CoverCandidate] = []
        self._chosen: int | None = None  # index into _candidates
        self._cards: list[ui.card] = []
        self._setting_cover_source = False
        self._releases: dict[str, Release] = {}
        self._release: Release | None = None
        self._medium: Medium | None = None
        self._request = 0  # a newer request makes the answer to an older one irrelevant

        with ui.dialog() as self.dialog, ui.card().classes("w-[64rem] max-w-full"):
            ui.label("Look up on MusicBrainz").classes("text-h6")
            self._status = ui.label().classes("min-h-[1.5rem]")
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                self._artist = ui.input("Artist", value=artist).props("outlined dense clearable")
                self._album = ui.input("Album", value=album).props("outlined dense clearable")
                self._artist.classes("grow")
                self._album.classes("grow")
                self._search_button = ui.button("Search", icon="search").props("unelevated")
            self._releases_table = self._make_releases_table()
            self._medium_select = ui.select({}, label="Disc of this release").props(
                "outlined dense"
            )
            self._medium_select.classes("w-96")
            self._medium_select.set_visibility(False)
            with ui.row().classes("items-center gap-4"):
                ui.label("Import:").classes("text-caption")
                self._field_boxes = {
                    name: ui.checkbox(FIELD_LABELS[name], value=name in DEFAULT_FIELDS)
                    for name in IMPORT_FIELDS
                }
            with ui.row().classes("w-full items-center gap-4"):
                self._cover_source = (
                    ui.select(
                        {COVER_NONE: "Keep the files' covers"}, value=COVER_NONE, label="Cover"
                    )
                    .props("outlined dense")
                    .classes("w-80")
                )
                self._cover_status = ui.label().classes("text-caption")
            self._cover_strip = ui.row().classes("w-full gap-2")
            self._summary = ui.label().classes("text-caption")
            self._preview = preview_table()
            self._apply = footer(self.dialog, "Apply")

        self._apply.set_enabled(False)
        self._cover_source.on_value_change(self._cover_source_changed)
        self._search_button.on_click(self.search)
        self._apply.on_click(self.apply)
        self._medium_select.on_value_change(self._medium_chosen)
        for box in self._field_boxes.values():
            box.on_value_change(self._refresh_preview)

    # --- building blocks ---------------------------------------------------------------------

    def _make_releases_table(self) -> ui.table:
        columns = [
            column("title", "Release"),
            column("artist", "Artist"),
            column("date", "Date"),
            column("country", "Country"),
            column("label", "Label"),
            column("tracks", "Tracks"),
            column("found", "Found by"),
        ]
        table = ui.table(
            columns=columns, rows=[], row_key="id", selection="single", on_select=self._on_select
        )
        table.props("dense flat bordered hide-bottom").classes("w-full")
        table.style("max-height: 12rem")
        return table

    def _say(self, text: str, level: Level = "info") -> None:
        self._status.text = text
        self._status.classes(replace=f"min-h-[1.5rem] {LEVEL_CLASSES[level]}")

    def _show_releases(self, releases: list[Release]) -> None:
        self._releases = {r.id: r for r in releases}
        self._releases_table.rows = [
            {
                "id": r.id,
                "title": r.title,
                "artist": r.artist,
                "date": r.date,
                "country": r.country,
                "label": r.label,
                "tracks": r.track_count,
                "found": FOUND_BY[r.source],
            }
            for r in releases
        ]
        self._releases_table.selected = []
        self._releases_table.update()
        self._release = self._medium = None
        self._set_cover_options(None)
        self._refresh_preview()

    def _busy(self, busy: bool) -> None:
        self._search_button.set_enabled(not busy)

    async def _guarded(self, action: Callable[[], Awaitable[None]]) -> None:
        """Run a MusicBrainz action: block the search button meanwhile, show errors as status."""
        self._request += 1
        mine = self._request
        self._busy(True)
        try:
            await action()
        except ServiceError as exc:
            if mine == self._request:
                self._say(str(exc), "error")
        finally:
            if mine == self._request:
                self._busy(False)

    # --- lookups -----------------------------------------------------------------------------

    async def start(self) -> None:
        """Look the CD up by its identifier, if the files give exactly one."""
        disc = self._scan.single_disc
        if disc is None:
            kinds = len(self._scan.discs)
            plain = len(self._scan.without_toc)
            reason = (
                f"The selected files come from {kinds} different CDs"
                if kinds > 1
                else "The selected files carry no CD identifier"
                if not kinds
                else f"{plain} of the selected files carry no CD identifier"
            )
            self._say(f"{reason}. Search by name instead.", "warning")
            return
        self._say("Looking up the CD…")
        await self._guarded(self._lookup_disc)

    async def _lookup_disc(self) -> None:
        disc = self._scan.single_disc
        assert disc is not None
        mine = self._request
        releases = await self._client.releases_for_disc_id(disc.disc_id)
        if mine != self._request:
            return
        if releases:
            self._say(f"{len(releases)} release(s) have exactly this CD identifier.", "ok")
        else:
            self._say("No release has exactly this CD identifier; looking for similar CDs…")
            candidates = await self._client.releases_for_toc(disc.toc)
            if mine != self._request:
                return
            releases = [r for r in candidates if plausible_for_toc(r, disc.toc)]
            if releases:
                self._say(
                    f"{len(releases)} release(s) with a similar CD layout. "
                    "Check that one is really yours before applying it.",
                    "warning",
                )
            else:
                self._say("MusicBrainz does not know this CD. Try searching by name.", "warning")
        self._show_releases(releases)
        if releases and (releases[0].source == "disc id" or len(releases) == 1):
            await self._select(releases[0].id)

    async def search(self) -> None:
        await self._guarded(self._search)

    async def _search(self) -> None:
        mine = self._request
        self._say("Searching…")
        releases = await self._client.search(self._artist.value or "", self._album.value or "")
        if mine != self._request:
            return
        self._show_releases(releases)
        if releases:
            self._say(f"{len(releases)} release(s) found. Select the one that fits.", "ok")
        else:
            self._say("Nothing found. Try fewer words, or only the artist.", "warning")

    def _on_select(self, event) -> None:
        if event.selection:
            release_id = event.selection[0]["id"]
            ui.timer(0, lambda: self._guarded(lambda: self._select(release_id)), once=True)

    async def _select(self, release_id: str) -> None:
        release = self._releases[release_id]
        if not release.has_track_lists:  # search results carry none
            mine = self._request
            self._say("Loading the track list…")
            release = await self._client.release(release_id, release.source)
            if mine != self._request:
                return
            self._releases[release_id] = release
        self._release = release
        # Mirror the choice in the table (it is also made programmatically, not only by clicking).
        self._releases_table.selected = [
            row for row in self._releases_table.rows if row["id"] == release_id
        ]
        disc = self._scan.single_disc
        expected = disc.toc.track_count if disc else len(self._files)
        self._medium = release.medium_for(disc.disc_id if disc else None, expected)
        multiple = len(release.media) > 1
        self._medium_select.set_visibility(multiple)
        if multiple:
            self._medium_select.options = {
                m.position: f"Disc {m.position}: {m.title or m.format} ({m.track_count} tracks)"
                for m in release.media
            }
            self._medium_select.update()
        chosen = self._medium or release.media[0]
        self._medium = chosen
        if multiple:
            self._medium_select.value = chosen.position
        self._set_cover_options(release)
        self._refresh_preview()

    def _medium_chosen(self) -> None:
        if self._release is None:
            return
        for medium in self._release.media:
            if medium.position == self._medium_select.value:
                self._medium = medium
        self._refresh_preview()

    # --- cover -------------------------------------------------------------------------------

    def _set_cover_options(self, release: Release | None) -> None:
        """Offer the cover sources that make sense for `release` and pick the best default: the
        Cover Art Archive if it has one, else a search on iTunes."""
        options = {COVER_NONE: "Keep the files' covers"}
        default = COVER_NONE
        if release is not None:
            if release.has_front_cover:
                options[COVER_ARCHIVE] = "Cover Art Archive (front cover)"
                default = COVER_ARCHIVE
            options[COVER_ITUNES] = "iTunes search (square covers)"
            if default == COVER_NONE:
                default = COVER_ITUNES
        self._setting_cover_source = True
        try:
            self._cover_source.options = options
            self._cover_source.update()
            self._cover_source.value = default
        finally:
            self._setting_cover_source = False
        self._cover_source_changed()

    def _cover_source_changed(self) -> None:
        if self._setting_cover_source:
            return
        self._clear_candidates()
        source = self._cover_source.value
        self._cover_status.text = ""
        if source == COVER_ITUNES and self._release is not None:
            self._cover_status.text = "Searching iTunes for covers…"
            ui.timer(0, lambda: self._guarded(self._search_covers), once=True)
        elif source == COVER_ARCHIVE:
            self._cover_status.text = "The front cover of this release is used."

    def _clear_candidates(self) -> None:
        self._candidates, self._chosen, self._cards = [], None, []
        self._cover_strip.clear()

    async def _search_covers(self) -> None:
        release = self._release
        if release is None:
            return
        mine = self._request
        candidates = await self._covers.search_covers(release.title, release.artist)
        if mine != self._request or self._cover_source.value != COVER_ITUNES:
            return
        self._clear_candidates()
        self._candidates = candidates
        # Preselect the best title match; a result that merely looks similar is left to the user.
        self._chosen = 0 if candidates and candidates[0].matches_title else None
        with self._cover_strip:
            for index, candidate in enumerate(candidates):
                self._cards.append(self._candidate_card(index, candidate))
        self._mark_chosen()

    def _candidate_card(self, index: int, candidate: CoverCandidate) -> ui.card:
        card = ui.card().tight().classes("w-36 cursor-pointer")
        card.on("click", lambda: self._choose_cover(index))
        with card:
            ui.image(data_url(candidate.thumbnail)).classes("w-36 h-36")
            ui.label(candidate.title).classes("text-caption px-1 ellipsis-2-lines")
            by = " · ".join(part for part in (candidate.artist, candidate.year) if part)
            ui.label(by).classes("text-caption text-grey px-1 ellipsis")
        return card

    def _choose_cover(self, index: int) -> None:
        self._chosen = index
        self._mark_chosen()

    def _mark_chosen(self) -> None:
        for index, card in enumerate(self._cards):
            card.style(replace=SELECTED_CARD if index == self._chosen else "")
        if not self._candidates:
            self._cover_status.text = "iTunes has no square cover for this title."
        elif self._chosen is None:
            self._cover_status.text = (
                "No result has exactly this title. Click a cover if one of them fits."
            )
        else:
            chosen = self._candidates[self._chosen]
            self._cover_status.text = f"Selected: {chosen.title}"

    # --- preview and apply -------------------------------------------------------------------

    def _fields(self) -> list[str]:
        return [name for name, box in self._field_boxes.items() if box.value]

    def _matches(self):
        assert self._medium is not None
        return match_tracks(self._files, self._medium)

    def _refresh_preview(self) -> None:
        release, medium = self._release, self._medium
        if release is None or medium is None:
            show_rows(self._preview, [], [])
            self._summary.text = ""
            self._apply.set_enabled(False)
            self._apply.text = "Apply"
            return
        matches = self._matches()
        columns = [
            column("n", "#"),
            column("file", "File"),
            column("title", "Title on MusicBrainz"),
            column("length", "Length file / MusicBrainz"),
            column("note", ""),
        ]
        rows = []
        for m in matches:
            difference = m.difference
            if m.file is None or m.track is None:
                note = "⚠ no file" if m.file is None else "⚠ no track"
            elif difference is not None and difference > LENGTH_TOLERANCE:
                note = f"⚠ differs by {difference:.0f} s"
            else:
                note = ""
            rows.append(
                {
                    "n": m.track.position if m.track else "",
                    "file": display_name(m.file.path, self._base) if m.file else "—",
                    "title": m.track.title if m.track else "—",
                    "length": f"{_minutes(m.file.seconds) if m.file else '—'} / "
                    f"{_minutes(m.track.seconds) if m.track else '—'}",
                    "note": note,
                }
            )
        show_rows(self._preview, columns, rows)
        paired = sum(1 for m in matches if m.file and m.track)
        if len(self._files) != medium.track_count:
            check = f"⚠ {len(self._files)} files but {medium.track_count} tracks on this disc"
        elif lengths_agree(matches):
            check = "✓ all track lengths agree with MusicBrainz"
        else:
            check = "⚠ some track lengths differ: check that this is the right release"
        self._summary.text = f"{check} · {paired} file(s) will be changed"
        self._apply.set_enabled(paired > 0 and bool(self._fields()))
        self._apply.text = f"Apply to {paired} file(s)"

    async def _load_cover(self, release: Release) -> CoverArt | None:
        """The cover the user chose, or None. A failure is reported, not fatal: the tags still
        go in."""
        source = self._cover_source.value
        if source == COVER_NONE or (source == COVER_ITUNES and self._chosen is None):
            return None
        self._busy(True)
        self._apply.set_enabled(False)
        self._say("Loading the cover…")
        try:
            if source == COVER_ARCHIVE:
                return await self._client.front_cover(release)
            return await self._covers.full_cover(self._candidates[self._chosen])
        except ServiceError as exc:
            ui.notify(f"The cover could not be loaded: {exc}", type="warning")
            return None

    async def apply(self) -> None:
        release, medium = self._release, self._medium
        if release is None or medium is None:
            return
        matches = self._matches()
        changes = build_changes(matches, release, medium, self._fields())
        cover = await self._load_cover(release)
        paired = tuple(m.file.path for m in matches if m.file and m.track)
        self.dialog.submit(LookupResult(changes, paired, cover))


async def lookup_dialog(
    client: MusicBrainz,
    covers: ITunes,
    files: list[LocalFile],
    scan: DiscScan,
    artist: str,
    album: str,
    base: Path | None = None,
) -> LookupResult | None:
    """Open the lookup dialog. Returns what the user confirmed, or None if cancelled."""
    dialog = LookupDialog(client, covers, files, scan, artist, album, base)
    ui.timer(0, dialog.start, once=True)
    result = await dialog.dialog
    dialog.dialog.delete()
    return result
