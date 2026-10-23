from pathlib import Path

import pytest
from mutagen.id3 import APIC, COMM, ID3, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from nicegui.testing import User

from imagery import png
from uihelpers import open_folder, select

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


# --- fixtures for the page tests (see uihelpers.py) ---------------------------------------------


@pytest.fixture
def music_root(make_mp3, tmp_path):
    root = tmp_path / "music"
    make_mp3(root / "rock" / "b.mp3", title="Beta", artist="Band", year="2001", track="2")
    make_mp3(
        root / "rock" / "a.mp3",
        title="Alpha",
        artist="Band",
        year="2000",
        track="1",
        cover=png(3, 2),
    )
    make_mp3(root / "rock" / "deep" / "c.mp3", title="Gamma")
    (root / "empty").mkdir()
    return root


@pytest.fixture
async def editing(user: User, music_root, monkeypatch):
    """A folder is open and a.mp3 is selected."""
    await open_folder(user, music_root, "rock")
    a = music_root / "rock" / "a.mp3"
    await select(user, monkeypatch, a)
    return a


@pytest.fixture
async def batch(user: User, music_root, monkeypatch):
    """A folder is open and a.mp3 (Alpha, 2000) and b.mp3 (Beta, 2001) are both selected."""
    await open_folder(user, music_root, "rock")
    rock = music_root / "rock"
    a, b = rock / "a.mp3", rock / "b.mp3"
    await select(user, monkeypatch, a, b)
    return a, b
