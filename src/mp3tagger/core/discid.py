"""CD table of contents (the ID3 MCDI frame) and the MusicBrainz Disc ID computed from it."""

import base64
import hashlib
import re
from dataclasses import dataclass

LEAD_IN = 150  # frames (2 s) before the first track; track offsets include it
_WMP_TOC = re.compile(r"^[0-9A-Fa-f]+(\+[0-9A-Fa-f]+)+$")
_LEAD_OUT_TRACK = 0xAA


class InvalidTocError(ValueError):
    """The data is not a usable CD table of contents."""


@dataclass(frozen=True)
class Toc:
    first_track: int
    offsets: tuple[int, ...]  # start of each track, in frames from the start of the disc
    leadout: int  # where the disc ends

    @property
    def last_track(self) -> int:
        return self.first_track + len(self.offsets) - 1

    @property
    def track_count(self) -> int:
        return len(self.offsets)

    @property
    def seconds(self) -> float:
        return (self.leadout - LEAD_IN) / 75

    def disc_id(self) -> str:
        """The MusicBrainz Disc ID: SHA-1 over first/last track and 100 offsets, in a URL-safe
        base64 variant (``+/=`` become ``._-``)."""
        slots = [0] * 100  # slot 0 is the lead-out, slots 1..99 the tracks
        slots[0] = self.leadout
        for number, offset in enumerate(self.offsets, start=self.first_track):
            slots[number] = offset
        text = f"{self.first_track:02X}{self.last_track:02X}" + "".join(f"{o:08X}" for o in slots)
        digest = hashlib.sha1(text.encode("ascii")).digest()
        return base64.b64encode(digest).decode().translate(str.maketrans("+/=", "._-"))

    def musicbrainz_toc(self) -> str:
        """The TOC in the form MusicBrainz accepts for fuzzy lookups."""
        numbers = [self.first_track, self.last_track, self.leadout, *self.offsets]
        return "+".join(str(n) for n in numbers)


def _checked(first_track: int, offsets: list[int], leadout: int) -> Toc:
    if not 1 <= first_track <= 99 or not offsets or first_track + len(offsets) - 1 > 99:
        raise InvalidTocError("Invalid track numbers in the CD table of contents")
    increasing = all(a < b for a, b in zip(offsets, [*offsets[1:], leadout], strict=True))
    if offsets[0] < LEAD_IN or not increasing:
        raise InvalidTocError("The CD table of contents is inconsistent")
    return Toc(first_track, tuple(offsets), leadout)


def _parse_text(data: bytes) -> Toc | None:
    """Windows Media Player's form: UTF-16 text "N+off1+...+offN+leadout", all numbers in hex."""
    try:
        text = data.decode("utf-16-le").rstrip("\x00")
    except UnicodeDecodeError:
        return None
    if not _WMP_TOC.match(text):
        return None
    numbers = [int(part, 16) for part in text.split("+")]
    count, rest = numbers[0], numbers[1:]
    if len(rest) != count + 1:
        raise InvalidTocError("The CD table of contents does not list all of its tracks")
    return _checked(1, rest[:-1], rest[-1])


def _parse_binary(data: bytes) -> Toc:
    """The layout the ID3 spec describes: a CD "READ TOC" dump with a 4-byte header followed by
    8 bytes per track and one for the lead-out (track number 0xAA). Addresses are either
    minutes/seconds/frames or plain sector numbers; both occur, so tell them apart by the first
    track, which starts at 00:02:00 in the former and at sector 0 in the latter."""
    if len(data) < 4 + 16 or (len(data) - 4) % 8:
        raise InvalidTocError("Unrecognised CD table of contents")
    first, last = data[2], data[3]
    rows = [data[i : i + 8] for i in range(4, len(data), 8)]
    if len(rows) != last - first + 2 or rows[-1][2] != _LEAD_OUT_TRACK:
        raise InvalidTocError("Unrecognised CD table of contents")

    def msf(row: bytes) -> int:
        return (row[5] * 60 + row[6]) * 75 + row[7]

    use_msf = msf(rows[0]) >= LEAD_IN
    addresses = [msf(row) if use_msf else int.from_bytes(row[4:8], "big") + LEAD_IN for row in rows]
    return _checked(first, addresses[:-1], addresses[-1])


def parse_mcdi(data: bytes) -> Toc:
    """Read the content of an MCDI frame. Raises InvalidTocError if it cannot be understood."""
    return _parse_text(data) or _parse_binary(data)
