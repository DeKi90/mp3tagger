import struct

import pytest

from imagery import jpeg, png
from mp3tagger.core.images import MAX_COVER_BYTES, sniff_image


def test_png():
    info = sniff_image(png(3, 2))
    assert (info.mime, info.width, info.height) == ("image/png", 3, 2)


@pytest.mark.parametrize("sof", [0xC0, 0xC1, 0xC2])
def test_jpeg_baseline_and_progressive(sof):
    info = sniff_image(jpeg(640, 480, sof=sof))
    assert (info.mime, info.width, info.height) == ("image/jpeg", 640, 480)


def test_jpeg_with_comment_segment_before_frame():
    data = jpeg()
    comment = b"\xff\xfe" + struct.pack(">H", 6) + b"hi!!"
    info = sniff_image(data[:2] + comment + data[2:])
    assert (info.width, info.height) == (40, 30)


@pytest.mark.parametrize(
    "data",
    [b"", b"GIF89a....", b"RIFF....WEBP", b"plain text", b"\xff\xd8", b"\x89PNG\r\n\x1a\nshort"],
)
def test_rejects_unsupported_or_corrupt(data):
    with pytest.raises(ValueError):
        sniff_image(data)


def test_rejects_too_large():
    with pytest.raises(ValueError, match="too large"):
        sniff_image(png() + bytes(MAX_COVER_BYTES))
