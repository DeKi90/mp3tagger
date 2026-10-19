from pathlib import Path

import pytest
from mutagen.id3 import APIC, COMM, ID3, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK

# MPEG-1 Layer III, 128 kbit/s, 44.1 kHz, stereo -> 417-byte frames (26 ms each)
_FRAME = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)


@pytest.fixture
def make_mp3():
    def _make(path: Path, frames: int = 40, **tags: str | bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_FRAME * frames)
        if tags:
            id3 = ID3()
            frame_types = {
                "title": TIT2, "artist": TPE1, "album": TALB, "album_artist": TPE2,
                "year": TDRC, "track": TRCK, "disc": TPOS, "genre": TCON, "composer": TCOM,
            }  # fmt: skip
            for name, value in tags.items():
                if name == "comment":
                    id3.add(COMM(encoding=3, lang="eng", desc="", text=value))
                elif name == "cover":  # a str is a dummy picture; pass image bytes for a real one
                    data = value if isinstance(value, bytes) else b"\x89PNG"
                    id3.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=data))
                else:
                    id3.add(frame_types[name](encoding=3, text=value))
            id3.save(path, v2_version=3)
        return path

    return _make
