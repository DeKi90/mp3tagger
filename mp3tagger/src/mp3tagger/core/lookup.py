"""Putting a MusicBrainz release onto files: which disc the files came from, which release track
belongs to which file, and the tag changes that follow."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from mutagen import MutagenError

from mp3tagger.core.discid import InvalidTocError, Toc, parse_mcdi
from mp3tagger.core.models import FIELD_NAMES
from mp3tagger.core.musicbrainz import Medium, Release, ReleaseTrack
from mp3tagger.core.tagio.base import TagReader

# Fields a release can fill in, in the order they are offered.
IMPORT_FIELDS = ("title", "track", "album", "artist", "album_artist", "year", "disc")
assert set(IMPORT_FIELDS) <= set(FIELD_NAMES)
LENGTH_TOLERANCE = 3.0  # seconds a track may differ from MusicBrainz and still count as a match


@dataclass(frozen=True)
class Disc:
    """The files that share one CD table of contents."""

    toc: Toc
    paths: tuple[Path, ...]

    @property
    def disc_id(self) -> str:
        return self.toc.disc_id()


@dataclass(frozen=True)
class DiscScan:
    discs: tuple[Disc, ...]  # one per distinct table of contents, in the order first met
    without_toc: tuple[Path, ...]  # files with no (usable) CD table of contents

    @property
    def single_disc(self) -> Disc | None:
        """The disc if all files belong to the same one."""
        return self.discs[0] if len(self.discs) == 1 and not self.without_toc else None


def scan_discs(paths: Iterable[Path], reader: TagReader) -> DiscScan:
    """Group `paths` by the CD they were ripped from. Blocking; call from a worker thread."""
    by_toc: dict[Toc, list[Path]] = {}
    missing: list[Path] = []
    for path in paths:
        try:
            data = reader.read_mcdi(path)
            toc = parse_mcdi(data) if data else None
        except MutagenError, OSError, InvalidTocError:
            toc = None
        if toc is None:
            missing.append(path)
        else:
            by_toc.setdefault(toc, []).append(path)
    return DiscScan(tuple(Disc(t, tuple(p)) for t, p in by_toc.items()), tuple(missing))


@dataclass(frozen=True)
class LocalFile:
    path: Path
    seconds: float
    track: str = ""  # the file's track and disc tags, used to put the files in order
    disc: str = ""


def _number(text: str) -> int:
    digits = text.partition("/")[0].strip()
    return int(digits) if digits.isdigit() else 10**9  # untagged files go last


def _disc(text: str) -> int:
    return _number(text) if text.strip() else 1  # most rips have no disc tag: disc 1


def order_files(files: Iterable[LocalFile]) -> list[LocalFile]:
    """Files in playing order: by disc (none means 1) and track number, then by name."""
    return sorted(files, key=lambda f: (_disc(f.disc), _number(f.track), f.path.name.casefold()))


@dataclass(frozen=True)
class TrackMatch:
    file: LocalFile | None  # None: a release track no file corresponds to
    track: ReleaseTrack | None  # None: a file without a release track

    @property
    def difference(self) -> float | None:
        """How much the file's length differs from the release track's, in seconds."""
        if self.file is None or self.track is None or self.track.seconds is None:
            return None
        return abs(self.file.seconds - self.track.seconds)


def match_tracks(files: Sequence[LocalFile], medium: Medium) -> list[TrackMatch]:
    """Pair the i-th file with the i-th track of `medium`. Surplus files or tracks stay unpaired."""
    ordered = order_files(files)
    tracks = medium.tracks
    return [
        TrackMatch(ordered[i] if i < len(ordered) else None, tracks[i] if i < len(tracks) else None)
        for i in range(max(len(ordered), len(tracks)))
    ]


def lengths_agree(matches: Sequence[TrackMatch], tolerance: float = LENGTH_TOLERANCE) -> bool:
    """True if every file is paired with a track of (nearly) the same length."""
    return bool(matches) and all(
        m.difference is not None and m.difference <= tolerance for m in matches
    )


def build_changes(
    matches: Sequence[TrackMatch], release: Release, medium: Medium, fields: Iterable[str]
) -> dict[Path, dict[str, str]]:
    """The tag changes for the paired files. Fields the release has no value for are left alone
    (an import never blanks an existing tag)."""
    wanted = set(fields)
    changes: dict[Path, dict[str, str]] = {}
    for match in matches:
        if match.file is None or match.track is None:
            continue
        candidates = {
            "title": match.track.title,
            "track": str(match.track.position),
            "album": release.title,
            "artist": match.track.artist,
            "album_artist": release.artist,
            "year": release.year,
            "disc": str(medium.position) if len(release.media) > 1 else "",
        }
        values = {f: v for f, v in candidates.items() if f in wanted and v}
        if values:
            changes[match.file.path] = values
    return changes


def plausible_for_toc(release: Release, toc: Toc, tolerance: float = 0.05) -> bool:
    """Whether a release found by a fuzzy table-of-contents lookup can be this disc: one of its
    discs has the same number of tracks and (where MusicBrainz knows the lengths) about the same
    total length. Fuzzy lookups return a lot of unrelated releases."""
    for medium in release.media:
        if medium.track_count != toc.track_count:
            continue
        lengths = [t.seconds for t in medium.tracks]
        if not lengths or None in lengths:
            return True  # nothing to compare the length with
        total = sum(s for s in lengths if s is not None)
        if abs(total - toc.seconds) <= tolerance * toc.seconds:
            return True
    return False
