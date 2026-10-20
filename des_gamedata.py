"""Bounds-checked readers for the game files the tools learn from.

Every reader validates offsets and lengths against the buffer and refuses
layouts it does not recognise instead of guessing. Nothing here is needed to
edit a save; the tools in ``tools/`` use it to build the embedded tables.
"""
from __future__ import annotations

from pathlib import Path
import re
import struct


def parse_bnd3(data: bytes) -> list[tuple[str, bytes]]:
    """Read the observed BND3 layout (0x20-byte header, 0x18-byte entries).

    Each entry starts with flags; size, offset, ID, and name offset follow.
    Unrecognized layouts and out-of-bounds data are refused, not guessed.
    """
    if len(data) < 0x20 or data[:4] != b'BND3':
        raise ValueError('not a complete BND3 container')
    count = struct.unpack_from('<I', data, 0x10)[0]
    if count > 10000 or 0x20 + count * 0x18 > len(data):
        raise ValueError('BND3 entry table exceeds file bounds')
    files = []
    for index in range(count):
        size, offset, _, nameoff = struct.unpack_from('<IIII', data, 0x24 + index * 0x18)
        if offset > len(data) or size > len(data) - offset or nameoff >= len(data):
            raise ValueError(f'BND3 entry {index} exceeds file bounds')
        end = data.find(b'\0', nameoff)
        if end == -1:
            raise ValueError(f'BND3 entry {index} name is unterminated')
        name = data[nameoff:end].decode('ascii', 'strict').replace('\\', '/').rsplit('/', 1)[-1]
        files.append((name, data[offset:offset + size]))
    return files


def param_rows(data: bytes) -> list[tuple[int, int]]:
    """Return (row ID, data offset) pairs from a PARAM file, in file order."""
    if len(data) < 0x30:
        raise ValueError('PARAM header is truncated')
    rows = struct.unpack_from('<H', data, 0x0A)[0]
    if 0x30 + rows * 12 > len(data):
        raise ValueError('PARAM row index exceeds file bounds')
    out = []
    for index in range(rows):
        row_id, offset = struct.unpack_from('<II', data, 0x30 + index * 12)
        if offset > len(data):
            raise ValueError(f'PARAM row {row_id} data offset exceeds file bounds')
        out.append((row_id, offset))
    return out


def parse_param(data: bytes) -> set[int]:
    """Return exact PARAM row IDs; unverified internal-name offsets are ignored."""
    return {row_id for row_id, _ in param_rows(data)}


def parse_ctxt(path: str | Path, table: str) -> dict[int, str]:
    path = Path(path)
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8-sig')
    pattern = re.compile(re.escape(table.upper()) + r'_NAME_(\d+):[0-9a-fA-F]+=([^\r\n]*)')
    return {int(match[1]): match[2].strip() for match in pattern.finditer(text)}
