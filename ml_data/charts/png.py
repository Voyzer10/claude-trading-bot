"""Standard-library PNG validation for chart images (structure, header, sRGB and the decoded image stream).

Checks: signature; every chunk CRC; IHDR first (13 bytes; 8-bit RGB; compression 0, filter 0, interlace 0);
IDAT chunks consecutive; the concatenated zlib stream decompresses completely with no trailing data and to exactly
height * (1 + width * 3) bytes; every scanline filter byte is 0-4; exactly one valid sRGB chunk (1 byte, rendering
intent 0-3) before the first IDAT; no iCCP; IEND last and empty. No rendering, no pixel interpretation.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import List, Tuple

from .exceptions import ImageValidationError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOR_TYPE_RGB = 2
RGB_BYTES_PER_PIXEL = 3
MAX_DIMENSION = 16384


@dataclass(frozen=True)
class PngInfo:
    width: int
    height: int
    bit_depth: int
    color_type: int
    compression: int
    filter_method: int
    interlace: int
    has_srgb: bool
    srgb_intent: int
    chunk_types: Tuple[str, ...]


def _chunks(data: bytes) -> List[Tuple[str, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        raise ImageValidationError("not a PNG file (bad signature)")
    pos, out = len(PNG_SIGNATURE), []
    while pos < len(data):
        if pos + 8 > len(data):
            raise ImageValidationError("truncated PNG chunk header")
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 8 + length + 4
        if end > len(data):
            raise ImageValidationError("truncated PNG chunk")
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:end])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise ImageValidationError(f"CRC mismatch in PNG chunk {ctype!r}")
        if not all(65 <= b <= 90 or 97 <= b <= 122 for b in ctype):
            raise ImageValidationError("invalid PNG chunk type")
        name = ctype.decode("ascii")
        out.append((name, body))
        pos = end
        if name == "IEND":
            break
    if pos != len(data):
        raise ImageValidationError("trailing bytes after PNG IEND (or IEND missing)")
    return out


def inspect_png(data: bytes) -> PngInfo:
    """Parse and structurally validate a PNG; does not enforce the chart profile (see validate_chart_png)."""
    if not isinstance(data, (bytes, bytearray)):
        raise ImageValidationError("image data must be bytes")
    chunks = _chunks(bytes(data))
    names = [n for n, _ in chunks]
    if not chunks or names[0] != "IHDR" or len(chunks[0][1]) != 13:
        raise ImageValidationError("PNG must start with a 13-byte IHDR chunk")
    if names.count("IHDR") != 1:
        raise ImageValidationError("PNG must contain exactly one IHDR")
    if names[-1] != "IEND" or names.count("IEND") != 1 or chunks[-1][1]:
        raise ImageValidationError("PNG must end with exactly one empty IEND chunk")
    if "IDAT" not in names:
        raise ImageValidationError("PNG has no IDAT image data")
    first_idat = names.index("IDAT")
    last_idat = len(names) - 1 - names[::-1].index("IDAT")
    if any(n != "IDAT" for n in names[first_idat:last_idat + 1]):
        raise ImageValidationError("PNG IDAT chunks must be consecutive")
    w, h, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if not (1 <= w <= MAX_DIMENSION and 1 <= h <= MAX_DIMENSION):
        raise ImageValidationError(f"PNG dimensions out of range: {w}x{h}")
    if comp != 0 or filt != 0 or interlace not in (0, 1):
        raise ImageValidationError(f"invalid IHDR methods (compression={comp}, filter={filt}, interlace={interlace})")
    srgb = [(i, body) for i, (n, body) in enumerate(chunks) if n == "sRGB"]
    intent = -1
    if srgb:
        if len(srgb) != 1:
            raise ImageValidationError("PNG must contain at most one sRGB chunk")
        idx, body = srgb[0]
        if len(body) != 1 or body[0] > 3:
            raise ImageValidationError("invalid sRGB chunk (must be 1 byte, rendering intent 0-3)")
        if idx > first_idat:
            raise ImageValidationError("sRGB chunk must precede the first IDAT")
        intent = body[0]
    return PngInfo(width=w, height=h, bit_depth=depth, color_type=ctype, compression=comp, filter_method=filt,
                   interlace=interlace, has_srgb=bool(srgb), srgb_intent=intent, chunk_types=tuple(names))


def _validate_image_stream(data: bytes, info: PngInfo) -> None:
    """Decompress the concatenated IDAT stream and check scanline count, length and filter bytes (8-bit RGB)."""
    chunks = _chunks(bytes(data))
    stream = b"".join(body for name, body in chunks if name == "IDAT")
    row_len = 1 + info.width * RGB_BYTES_PER_PIXEL
    expected = info.height * row_len
    d = zlib.decompressobj()
    try:
        raw = d.decompress(stream, expected + 1)
    except zlib.error as exc:
        raise ImageValidationError(f"corrupt IDAT zlib stream: {exc}") from None
    if len(raw) > expected or d.unconsumed_tail:
        raise ImageValidationError("IDAT image data is longer than height * (1 + width * 3) bytes")
    if not d.eof:
        raise ImageValidationError("IDAT zlib stream is truncated (no end of stream)")
    if d.unused_data:
        raise ImageValidationError("trailing data after the IDAT zlib stream")
    if len(raw) != expected:
        raise ImageValidationError(f"IDAT image data is {len(raw)} bytes, expected {expected} "
                                   f"({info.height} scanlines of {row_len} bytes)")
    for row in range(info.height):
        f = raw[row * row_len]
        if f > 4:
            raise ImageValidationError(f"invalid scanline filter type {f} on row {row}")


def validate_chart_png(data: bytes, *, width_px: int, height_px: int) -> PngInfo:
    """Chart profile image: exact size, 8-bit RGB (no alpha), non-interlaced, valid sRGB, no ICC, valid image data."""
    info = inspect_png(data)
    if (info.width, info.height) != (width_px, height_px):
        raise ImageValidationError(f"PNG is {info.width}x{info.height}, expected {width_px}x{height_px}")
    if info.color_type != COLOR_TYPE_RGB or info.bit_depth != 8:
        raise ImageValidationError(f"PNG must be 8-bit RGB (colour type 2); got type {info.color_type} depth {info.bit_depth}")
    if info.interlace != 0:
        raise ImageValidationError("PNG must not be interlaced")
    if not info.has_srgb:
        raise ImageValidationError("PNG must declare the sRGB colour space (sRGB chunk before IDAT)")
    if "iCCP" in info.chunk_types:
        raise ImageValidationError("PNG must not embed an ICC profile (sRGB is declared via the sRGB chunk)")
    _validate_image_stream(data, info)
    return info
