"""ID3 backend based on mutagen."""

from collections.abc import Mapping
from pathlib import Path

from mutagen import MutagenError
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    TALB,
    TCOM,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    ID3NoHeaderError,
)
from mutagen.mp3 import MP3

from mp3tagger.core.images import EXTENSIONS
from mp3tagger.core.models import (
    FIELD_NAMES,
    UNCHANGED,
    YEAR_FORMATS,
    AudioInfo,
    CoverArt,
    CoverChange,
    MoveCoverToFolder,
    TagSet,
    Track,
    is_valid_year,
)
from mp3tagger.core.tagio.base import SaveOptions

# Multiple values in one frame (e.g. several artists) are shown joined by this separator.
SEPARATOR = "; "


def _text(tags: ID3, frame_id: str) -> str:
    frame = tags.get(frame_id)
    if frame is None:
        return ""
    return SEPARATOR.join(str(t) for t in frame.text)


def _main_comment(tags: ID3) -> COMM | None:
    """The user-visible comment: the one without a description, else the first one.

    Other COMM frames are usually tool-specific data (e.g. iTunes' iTunNORM).
    """
    frames = tags.getall("COMM")
    return next((f for f in frames if not f.desc), frames[0] if frames else None)


FRONT_COVER = 3  # APIC picture type


def _main_picture(tags: ID3) -> APIC | None:
    """The picture shown as cover: the front cover if there is one, else the first picture."""
    frames = tags.getall("APIC")
    return next((f for f in frames if f.type == FRONT_COVER), frames[0] if frames else None)


def _comment(tags: ID3) -> str:
    frame = _main_comment(tags)
    return SEPARATOR.join(str(t) for t in frame.text) if frame else ""


def _tag_version(tags: ID3) -> str:
    major, minor = tags.version[:2]  # v1-only files report a 2-tuple
    if major == 1:
        return "ID3v1.1" if minor else "ID3v1"
    return f"ID3v2.{minor}"


def _tagset(tags: ID3) -> TagSet:
    return TagSet(
        title=_text(tags, "TIT2"),
        artist=_text(tags, "TPE1"),
        album=_text(tags, "TALB"),
        album_artist=_text(tags, "TPE2"),
        # TDRC may hold a full timestamp (2024-05-01); the year column shows the year only.
        year=_text(tags, "TDRC")[:4],
        track=_text(tags, "TRCK"),
        disc=_text(tags, "TPOS"),
        genre=_text(tags, "TCON"),
        comment=_comment(tags),
        composer=_text(tags, "TCOM"),
    )


class Id3Reader:
    extensions = (".mp3",)

    def read_cover(self, path: Path) -> CoverArt | None:
        """The cover picture of a file, or None. Raises MutagenError/OSError if unreadable."""
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            return None
        picture = _main_picture(tags)
        return CoverArt(bytes(picture.data), picture.mime) if picture else None

    def read(self, path: Path) -> Track:
        try:
            audio = MP3(path)
            size = path.stat().st_size
        except (MutagenError, OSError) as exc:
            return Track(path=path, error=str(exc) or type(exc).__name__)
        info = AudioInfo(
            duration=audio.info.length,
            bitrate=audio.info.bitrate,
            sample_rate=audio.info.sample_rate,
            channels=audio.info.channels,
            size=size,
        )
        try:
            # Combines ID3v1 and ID3v2 (v2 takes precedence) and upgrades v2.3 frames to v2.4 names.
            tags = ID3(path)
        except ID3NoHeaderError:
            return Track(path=path, info=info)
        except MutagenError as exc:
            return Track(path=path, info=info, error=str(exc) or type(exc).__name__)
        return Track(
            path=path,
            tags=_tagset(tags),
            info=info,
            tag_version=_tag_version(tags),
            has_cover=bool(tags.getall("APIC")),
        )


_TEXT_FRAMES = {
    "title": TIT2,
    "artist": TPE1,
    "album": TALB,
    "album_artist": TPE2,
    "track": TRCK,
    "disc": TPOS,
    "genre": TCON,
    "composer": TCOM,
}
_UTF8 = 3  # mutagen converts to UTF-16 when saving as ID3v2.3, which has no UTF-8
DEFAULT_VERSION = 3  # most widely supported; used for files that have no ID3v2 tag yet


def _set_text(tags: ID3, frame_cls: type, value: str) -> None:
    tags.delall(frame_cls.__name__)
    if value:
        tags.add(frame_cls(encoding=_UTF8, text=value.split(SEPARATOR)))


def _set_year(tags: ID3, value: str) -> None:
    if not is_valid_year(value):
        raise ValueError(f"Invalid year {value!r}: expected {YEAR_FORMATS}")
    tags.delall("TDRC")
    if value:
        tags.add(TDRC(encoding=_UTF8, text=value))


def _set_comment(tags: ID3, value: str) -> None:
    frame = _main_comment(tags)
    if frame is None:
        if value:
            tags.add(COMM(encoding=_UTF8, lang="eng", desc="", text=value))
    elif value:
        frame.encoding = _UTF8
        frame.text = [value]
    else:
        del tags[frame.HashKey]


def _set_cover(tags: ID3, cover: CoverArt | None) -> None:
    """Replace or remove the displayed picture. Other embedded pictures are left alone."""
    if cover is not None and cover.mime not in EXTENSIONS:
        raise ValueError(f"Unsupported cover image type {cover.mime!r}")
    old = _main_picture(tags)
    if old is not None:
        del tags[old.HashKey]
    if cover is not None:
        # APIC frames are keyed by description: pick one that does not replace another picture.
        taken = {f.desc for f in tags.getall("APIC")}
        desc = next(d for d in ("", *(f"cover{i}" for i in range(1, 100))) if d not in taken)
        tags.add(
            APIC(encoding=_UTF8, mime=cover.mime, type=FRONT_COVER, desc=desc, data=cover.data)
        )


class Id3Writer:
    def write(
        self,
        path: Path,
        changes: Mapping[str, str],
        options: SaveOptions,
        cover: CoverChange = UNCHANGED,
    ) -> None:
        unknown = set(changes) - set(FIELD_NAMES)
        if unknown:
            raise ValueError(f"Unknown tag fields: {', '.join(sorted(unknown))}")
        try:
            # Loading keeps all existing frames, so frames outside our model survive the save.
            tags = ID3(path)
            existing = tags.version[:2]
            current = existing[1] if existing[0] == 2 and existing[1] in (3, 4) else None
        except ID3NoHeaderError:
            tags = ID3()
            current = None
        version = options.version or current or DEFAULT_VERSION

        for field, value in changes.items():
            if field == "year":
                _set_year(tags, value)
            elif field == "comment":
                _set_comment(tags, value)
            else:
                _set_text(tags, _TEXT_FRAMES[field], value)

        if isinstance(cover, MoveCoverToFolder):
            raise ValueError("Moving a cover to a file is resolved before writing tags")
        if cover is not UNCHANGED:
            _set_cover(tags, cover)

        # v1=2 creates an ID3v1 tag, v1=1 only updates one that already exists.
        tags.save(path, v1=2 if options.write_v1 else 1, v2_version=version)
