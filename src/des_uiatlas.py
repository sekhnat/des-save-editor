"""Read the remake's UI texture atlas (``global.ctal`` + ``global_pages.ctxr``).

The atlas table (``.ctal``) starts with a length-prefixed atlas path, then a u32
sprite count and 40-byte records: u32 name hash, four (u, v) f32 corners and a
u32 page index. Sprite names are hashed with 32-bit FNV-1a over the uppercased
name (``Tex_InvIcon_Elixir`` -> ``fnv1a_upper('Tex_InvIcon_Elixir')``).

The pages file (``.ctxr``) is a 0x4D-byte header followed by the page array.
The atlas pages are 32-bit RGBA, 4096 x 4096, stored in the GPU's standard
64 KiB tiling: 128 x 128 texel blocks in row-major order, and inside each block
the byte address is built from interleaved x/y bits (``_SWIZZLE_32BPP``; this
is AMD's documented SW_64KB_S pattern for 4-byte elements).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

import numpy as np

CTXR_DATA = 0x4D
_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193

# Byte-address bit -> source coordinate bit inside one 64 KiB block (32 bpp).
# Address bits 0-1 select the byte within the texel.
_SWIZZLE_32BPP = {2: ('x', 0), 3: ('x', 1), 4: ('y', 0), 5: ('y', 1), 6: ('y', 2),
                  7: ('x', 2), 8: ('y', 3), 9: ('x', 3), 10: ('y', 4), 11: ('x', 4),
                  12: ('y', 5), 13: ('x', 5), 14: ('y', 6), 15: ('x', 6)}
BLOCK = 128                      # texels per block side at 32 bpp
BLOCK_BYTES = BLOCK * BLOCK * 4  # 64 KiB


def fnv1a_upper(name: str) -> int:
    """The atlas sprite id of ``name`` (FNV-1a 32 over the ASCII-uppercased name)."""
    value = _FNV_OFFSET
    for byte in name.upper().encode('ascii'):
        value = ((value ^ byte) * _FNV_PRIME) & 0xFFFFFFFF
    return value


@dataclass(frozen=True)
class Sprite:
    hash: int
    x: int
    y: int
    w: int
    h: int
    page: int


def parse_ctal(data: bytes, size: int = 4096) -> tuple[str, list[Sprite]]:
    """Atlas path and sprites (pixel rectangles on a ``size``-texel page)."""
    if len(data) < 6:
        raise ValueError('CTAL is truncated')
    plen = data[0]
    path = data[1:1 + plen].decode('ascii', 'replace')
    at = 1 + plen
    if at + 4 > len(data):
        raise ValueError('CTAL header is truncated')
    count = struct.unpack_from('<I', data, at)[0]
    at += 4
    if at + count * 40 > len(data):
        raise ValueError('CTAL sprite table exceeds file bounds')
    sprites = []
    for _ in range(count):
        name_hash = struct.unpack_from('<I', data, at)[0]
        corners = struct.unpack_from('<8f', data, at + 4)
        page = struct.unpack_from('<I', data, at + 36)[0]
        xs, ys = corners[0::2], corners[1::2]
        x0, y0 = round(min(xs) * size), round(min(ys) * size)
        sprites.append(Sprite(name_hash, x0, y0, round(max(xs) * size) - x0,
                              round(max(ys) * size) - y0, page))
        at += 40
    return path, sprites


def _swizzle_tables() -> tuple[np.ndarray, np.ndarray]:
    """Per-coordinate byte offsets inside a block; offset = xt[x] ^ yt[y]."""
    xt = np.zeros(BLOCK, dtype=np.int64)
    yt = np.zeros(BLOCK, dtype=np.int64)
    idx = np.arange(BLOCK, dtype=np.int64)
    for addr_bit, (axis, src_bit) in _SWIZZLE_32BPP.items():
        part = ((idx >> src_bit) & 1) << addr_bit
        if axis == 'x':
            xt |= part
        else:
            yt |= part
    return xt, yt


def detile_64kb_32bpp(raw: bytes | np.ndarray, width: int, height: int) -> np.ndarray:
    """Linear (height, width, 4) uint8 image from standard-64KiB-tiled 32 bpp data."""
    if width % BLOCK or height % BLOCK:
        raise ValueError('width and height must be multiples of 128')
    buf = np.frombuffer(raw, dtype=np.uint8) if not isinstance(raw, np.ndarray) else raw.reshape(-1)
    if buf.size < width * height * 4:
        raise ValueError('tiled data is shorter than the image')
    xt, yt = _swizzle_tables()
    x = np.arange(width, dtype=np.int64)
    y = np.arange(height, dtype=np.int64)
    blocks_per_row = width // BLOCK
    block_x = (x // BLOCK) * BLOCK_BYTES
    block_y = (y // BLOCK) * (blocks_per_row * BLOCK_BYTES)
    offset = (block_y[:, None] + block_x[None, :]
              + (yt[y % BLOCK][:, None] ^ xt[x % BLOCK][None, :]))
    texels = buf[: width * height * 4].view(np.uint32)
    return texels[offset // 4].view(np.uint8).reshape(height, width, 4)


def tile_64kb_32bpp(image: np.ndarray) -> bytes:
    """Inverse of :func:`detile_64kb_32bpp` (used by the tests)."""
    height, width = image.shape[:2]
    xt, yt = _swizzle_tables()
    x = np.arange(width, dtype=np.int64)
    y = np.arange(height, dtype=np.int64)
    blocks_per_row = width // BLOCK
    offset = ((y // BLOCK)[:, None] * (blocks_per_row * BLOCK_BYTES) + ((x // BLOCK) * BLOCK_BYTES)[None, :]
              + (yt[y % BLOCK][:, None] ^ xt[x % BLOCK][None, :]))
    out = np.zeros(width * height, dtype=np.uint32)
    out[(offset // 4).reshape(-1)] = np.ascontiguousarray(image).view(np.uint32).reshape(-1)
    return out.tobytes()


def read_page(path: str | Path, page: int, width: int = 4096, height: int = 4096) -> np.ndarray:
    """Decode one RGBA page of an atlas ``.ctxr`` without reading the others."""
    page_bytes = width * height * 4
    path = Path(path)
    total = path.stat().st_size - CTXR_DATA
    if total <= 0 or total % page_bytes:
        raise ValueError(f'{path.name}: {total} data bytes is not a whole number of '
                         f'{width}x{height} 32 bpp pages')
    if not 0 <= page < total // page_bytes:
        raise ValueError(f'{path.name}: page {page} is out of range')
    with path.open('rb') as handle:
        handle.seek(CTXR_DATA + page * page_bytes)
        raw = handle.read(page_bytes)
    return detile_64kb_32bpp(raw, width, height)
