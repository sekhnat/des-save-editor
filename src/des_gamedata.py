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


# --------------------------------------------------------------------------- #
#  PARAMDEF (as shipped in paramdef.paramdefbnd)
# --------------------------------------------------------------------------- #
PARAMDEF_HEADER = 0x30
PARAMDEF_FIELD = 0xB0
SCALARS = {'s8': 'b', 'u8': 'B', 's16': 'h', 'u16': 'H', 's32': 'i', 'u32': 'I', 'f32': 'f'}


def _cstr(raw: bytes) -> str:
    return raw.split(b'\0', 1)[0].decode('latin-1').strip()


def parse_paramdef(data: bytes) -> dict:
    """Field list of one PARAMDEF: display name/type, byte size, internal name.

    Field records are 0xB0 bytes from offset 0x30: display name [0x40],
    display type [8], format [8], default/min/max/increment f32, edit flags,
    byte count, description offset, 4 reserved bytes, internal type [0x20] at
    0x70 and internal name [0x20] at 0x90. ``name:N`` internal names are
    bit fields of N bits.
    """
    if len(data) < PARAMDEF_HEADER:
        raise ValueError('PARAMDEF header is truncated')
    strings, header, version, count = struct.unpack_from('<IHHH', data, 0)
    if header != PARAMDEF_HEADER or strings > len(data):
        raise ValueError('unsupported PARAMDEF header')
    if PARAMDEF_HEADER + count * PARAMDEF_FIELD > len(data):
        raise ValueError('PARAMDEF fields exceed file bounds')
    fields = []
    for index in range(count):
        at = PARAMDEF_HEADER + index * PARAMDEF_FIELD
        name = _cstr(data[at + 0x90:at + 0xB0])
        base, _, bits = name.partition(':')
        fields.append({'display': _cstr(data[at:at + 0x40]),
                       'type': _cstr(data[at + 0x40:at + 0x48]),
                       'size': struct.unpack_from('<i', data, at + 0x64)[0],
                       'internal_type': _cstr(data[at + 0x70:at + 0x90]),
                       'name': base, 'bits': int(bits) if bits else None})
    return {'type': _cstr(data[0x0C:0x2C]), 'version': version, 'fields': fields}


def paramdef_layout(fields: list[dict]) -> tuple[list[dict], int]:
    """Byte offset (and bit offset for bit fields) of every field, and the row size."""
    offset, bit, unit, start = 0, 0, 0, 0
    out = []
    for field in fields:
        if field['size'] <= 0:
            raise ValueError(f"field {field['name']} has no size")
        if field['bits'] is not None:
            width = field['size'] * 8
            if bit == 0 or bit + field['bits'] > unit or width != unit:
                start, bit, unit = offset, 0, width
                offset += field['size']
            out.append({**field, 'offset': start, 'bit': bit})
            bit += field['bits']
        else:
            bit = 0
            out.append({**field, 'offset': offset, 'bit': None})
            offset += field['size']
    return out, offset


def param_type(data: bytes) -> str:
    """The row-struct name stored in a PARAM header (matches its PARAMDEF)."""
    if len(data) < 0x2C:
        raise ValueError('PARAM header is truncated')
    return _cstr(data[0x0C:0x2C])


def read_param(definition: bytes, data: bytes) -> dict[int, dict]:
    """Decode every row of a PARAM using its PARAMDEF.

    The layout must account for exactly the PARAM row stride; tables whose rows
    were extended beyond their definition are refused rather than guessed.
    """
    spec = parse_paramdef(definition)
    if spec['type'] != param_type(data):
        raise ValueError(f"PARAMDEF {spec['type']} does not describe PARAM {param_type(data)}")
    layout, row_size = paramdef_layout(spec['fields'])
    rows = param_rows(data)
    offsets = sorted(offset for _, offset in rows)
    strides = {b - a for a, b in zip(offsets, offsets[1:])}
    if strides and strides != {row_size}:
        raise ValueError(f"{spec['type']}: definition is {row_size} bytes, rows are {sorted(strides)}")
    out = {}
    for row_id, offset in rows:
        if offset + row_size > len(data):
            raise ValueError(f'PARAM row {row_id} exceeds file bounds')
        row = {}
        for field in layout:
            code = SCALARS.get(field['type'])
            if code is None:
                continue                      # padding, strings
            value = struct.unpack_from('<' + code, data, offset + field['offset'])[0]
            if field['bit'] is not None:
                value = (value >> field['bit']) & ((1 << field['bits']) - 1)
            row[field['name']] = value
        out[row_id] = row
    return out


def load_params(game: Path) -> dict[str, dict[int, dict]]:
    """Every gameparam table whose definition matches its rows, by PARAMDEF type."""
    dvd = Path(game) / 'cp11demonssouls/dvdroot'
    definitions = {parse_paramdef(data)['type']: data
                   for _, data in parse_bnd3((dvd / 'paramdef/paramdef.paramdefbnd').read_bytes())}
    tables = {}
    for _, data in parse_bnd3((dvd / 'param/gameparam/gameparam.parambnd').read_bytes()):
        kind = param_type(data)
        if kind in definitions:
            try:
                tables[kind] = read_param(definitions[kind], data)
            except ValueError:
                continue                      # extended rows: refused, see read_param
    return tables
