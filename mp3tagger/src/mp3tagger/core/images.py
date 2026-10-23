"""Recognising cover images from their bytes (never from the file name)."""

from dataclasses import dataclass

MAX_COVER_BYTES = 10 * 1024 * 1024

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# JPEG start-of-frame markers carry the dimensions (all SOFn except DHT, JPG and DAC).
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_JPEG_STANDALONE = frozenset({0x01, *range(0xD0, 0xDA)})  # markers without a length field

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png"}
# Name of the cover image placed in an album folder (a widely recognised convention).
FOLDER_COVER_NAMES = {mime: f"cover{ext}" for mime, ext in EXTENSIONS.items()}


@dataclass(frozen=True)
class ImageInfo:
    mime: str
    width: int
    height: int


def sniff_image(data: bytes) -> ImageInfo:
    """Return mime type and size of a JPEG or PNG image. Raises ValueError for anything else."""
    if len(data) > MAX_COVER_BYTES:
        raise ValueError(f"Image is too large (maximum {MAX_COVER_BYTES // 1024 // 1024} MB)")
    if data.startswith(_PNG_SIGNATURE):
        return _png_info(data)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_info(data)
    raise ValueError("Unsupported image format: use JPEG or PNG")


def _png_info(data: bytes) -> ImageInfo:
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise ValueError("Corrupt PNG image")
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if not width or not height:
        raise ValueError("Corrupt PNG image")
    return ImageInfo("image/png", width, height)


def _jpeg_info(data: bytes) -> ImageInfo:
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
        elif marker in _JPEG_STANDALONE:
            pos += 2
        elif marker in _JPEG_SOF:
            height = int.from_bytes(data[pos + 5 : pos + 7], "big")
            width = int.from_bytes(data[pos + 7 : pos + 9], "big")
            if not width or not height:
                break
            return ImageInfo("image/jpeg", width, height)
        else:
            pos += 2 + int.from_bytes(data[pos + 2 : pos + 4], "big")
    raise ValueError("Corrupt JPEG image")
