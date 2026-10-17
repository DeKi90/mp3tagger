"""ID3 backend based on mutagen."""

from pathlib import Path

from mutagen import MutagenError
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp3 import MP3

from mp3tagger.core.models import AudioInfo, TagSet, Track

# Multiple values in one frame (e.g. several artists) are shown joined by this separator.
SEPARATOR = "; "


def _text(tags: ID3, frame_id: str) -> str:
    frame = tags.get(frame_id)
    if frame is None:
        return ""
    return SEPARATOR.join(str(t) for t in frame.text)


def _comment(tags: ID3) -> str:
    frames = tags.getall("COMM")
    return SEPARATOR.join(str(t) for f in frames[:1] for t in f.text)


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
