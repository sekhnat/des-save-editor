"""World-state containers: per-entity records keyed by 16-byte GUIDs.

The largest blob in a played profile (key ``6d87f588``) is not an opaque
payload. It is a sequence of *groups*::

    u32 version (3)  u32 count  count x entry

and every entry is::

    16-byte entity GUID  u32 kind  u32 length  <length bytes>

The entry bytes are an ordinary typed record stream, in the same
``key | type | value`` format and FNV key space as the outer save, so
``des_save.parse`` reads them. Kinds 7, 8 and 13 have been observed; their
meaning is not known and they are preserved as-is.

The GUIDs are entity IDs from the game's prefab files (``scripts/**/*.cgpr``):
the archstone entity ``b13668df…`` is defined in ``o0300_archstone.cgpr``.
The baseline files ``misc/cachedsavedata/*.txt`` shipped with the game use
the same framing, one group per level section.

Decoding is strict. A blob is treated as world state only when the framing
consumes it exactly. An entry whose bytes do not parse as a record stream
(types this parser does not know, header-only containers) keeps its raw bytes
and is never interpreted. Encoding reuses the stored bytes, so an unedited
blob always rebuilds byte-identically.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field as dc_field
import gzip
import math
from pathlib import Path
import re
import struct

import des_fields
import des_save
from des_save import (Field, T_BLOB, T_BOOL, T_CONTAINER, T_F32, T_I32, T_RAW4,
                      T_STR, T_U16, T_U8)

GROUP_VERSION = 3
GUID_SIZE = 16
ENTRY_HEADER = GUID_SIZE + 8           # guid, u32 kind, u32 length
MAX_ENTRIES = 100_000
EDITABLE = (T_U8, T_U16, T_I32, T_F32, T_BOOL)


@dataclass
class Entry:
    guid: bytes
    kind: int
    offset: int                         # payload offset inside the blob
    payload: bytes
    records: list[Field] | None = None  # None: bytes kept raw, not interpreted

    @property
    def guid_hex(self) -> str:
        return self.guid.hex()


@dataclass
class Group:
    version: int
    offset: int
    entries: list[Entry] = dc_field(default_factory=list)


def _parse_payload(raw: bytes, start: int, end: int) -> list[Field] | None:
    """Parse one entry as a record stream, or None when it is not one."""
    try:
        records, stop = des_save.parse(raw, start, end)
    except ValueError:
        return None
    if stop != end:
        return None
    # Only interpret what rebuilds exactly; anything else stays raw.
    if des_save.serialize(records) != raw[start:end]:
        return None
    return records


def decode(raw: bytes) -> list[Group] | None:
    """Decode a world-state blob, or return None when the framing does not fit.

    Never raises on malformed input: anything that is not exactly this framing
    stays an opaque blob.
    """
    if len(raw) < 8:
        return None
    groups: list[Group] = []
    total = 0
    i = 0
    while i < len(raw):
        if len(raw) - i < 8:
            return None
        version, count = struct.unpack_from('<II', raw, i)
        if version != GROUP_VERSION or count > (len(raw) - i - 8) // ENTRY_HEADER:
            return None
        group = Group(version, i)
        i += 8
        for _ in range(count):
            if len(raw) - i < ENTRY_HEADER:
                return None
            guid = raw[i:i + GUID_SIZE]
            kind, length = struct.unpack_from('<II', raw, i + GUID_SIZE)
            start = i + ENTRY_HEADER
            end = start + length
            if end > len(raw):
                return None
            group.entries.append(Entry(guid, kind, start, raw[start:end],
                                       _parse_payload(raw, start, end)))
            i = end
        total += count
        if total > MAX_ENTRIES:
            return None
        groups.append(group)
    return groups


def encode(groups: list[Group]) -> bytes:
    out = bytearray()
    for group in groups:
        out += struct.pack('<II', group.version, len(group.entries))
        for entry in group.entries:
            if len(entry.guid) != GUID_SIZE:
                raise ValueError('entity GUIDs are 16 bytes')
            out += entry.guid + struct.pack('<II', entry.kind, len(entry.payload))
            out += entry.payload
    return bytes(out)


def entries(groups: list[Group]):
    """Yield (group index, entry index, entry) in file order."""
    for gi, group in enumerate(groups):
        for ei, entry in enumerate(group.entries):
            yield gi, ei, entry


_walk = des_save.walk_records


def record_name(key: int) -> str | None:
    """Name of a key as it appears inside a world entry."""
    return des_fields.world_name(key) or des_fields.field_name(key)


def parse_guid(text: str) -> bytes:
    """Accept the 32-hex-digit storage-order form, with or without dashes."""
    clean = text.strip().replace('-', '').lower()
    if len(clean) != 32:
        raise ValueError('a GUID is 32 hex digits in storage order')
    return bytes.fromhex(clean)


def set_value(raw: bytes, guid: bytes, key: int, value, occurrence: int = 0) -> bytes:
    """Return a copy of ``raw`` with one scalar world record changed.

    The record is addressed by (entity GUID, key, occurrence in file order).
    Only fixed-size scalars can be edited, so every length and offset in the
    blob stays the same. Booleans accept 0 or 1 only.
    """
    groups = decode(raw)
    if groups is None:
        raise ValueError('blob is not a decodable world-state container')
    hits = [(entry, record) for _, _, entry in entries(groups)
            if entry.guid == guid and entry.records is not None
            for record in _walk(entry.records) if record.key == key]
    if not 0 <= occurrence < len(hits):
        raise ValueError(f'{guid.hex()} has {len(hits)} record(s) with key {key:08x}')
    entry, record = hits[occurrence]
    if record.type not in EDITABLE:
        raise ValueError(f'type {record.type:#04x} records cannot be edited in place')
    if record.type == T_BOOL and value not in (0, 1, True, False):
        raise ValueError('boolean records take 0 or 1')
    if record.type != T_F32 and isinstance(value, float):
        if not value.is_integer():
            raise ValueError('integer records need whole numbers')
        value = int(value)
    before = record.raw
    try:
        record.value = int(value) if record.type == T_BOOL else value
    except (OverflowError, ValueError) as error:
        record.raw = before
        raise ValueError(f'value {value!r} does not fit type {record.type:#04x}') from error
    payload = des_save.serialize(entry.records)
    if len(payload) != len(entry.payload):            # cannot happen for scalars
        raise ValueError('edit would change the entry size')
    entry.payload = payload
    rebuilt = encode(groups)
    if len(rebuilt) != len(raw):
        raise ValueError('edit would change the blob size')
    return rebuilt


# --------------------------------------------------------------------------- #
#  Presentation
# --------------------------------------------------------------------------- #
def _record_value(record: Field):
    if record.type == T_CONTAINER:
        return [_record_obj(child) for child in record.children]
    if record.type in (T_U8, T_U16, T_I32, T_BOOL):
        return record.value
    if record.type == T_F32:
        value = record.value
        return value if math.isfinite(value) else record.raw.hex()
    if record.type == T_STR:
        return record.text()
    if record.type in (T_RAW4, T_BLOB):
        return {'size': len(record.raw), 'hex': record.raw[:32].hex()}
    return record.raw.hex()


def _record_obj(record: Field) -> dict:
    return {'key': f'{record.key:08x}', 'name': record_name(record.key),
            'type': record.type, 'value': _record_value(record)}


def describe(groups: list[Group], index=None) -> list[dict]:
    """JSON-ready view; ``index`` (an EntityIndex) adds entity paths."""
    rows = []
    for gi, ei, entry in entries(groups):
        row = {'group': gi, 'entry': ei, 'guid': entry.guid_hex, 'kind': entry.kind,
               'size': len(entry.payload), 'offset': entry.offset,
               'entity': index.lookup(entry.guid) if index else None}
        if entry.records is None:
            row['raw'] = entry.payload[:32].hex()
        else:
            row['records'] = [_record_obj(record) for record in entry.records]
        rows.append(row)
    return rows


class EntityIndex:
    """GUID -> defining game file, from ``entitydb.bin`` (tools/build_entitydb.py).

    Lookups use the first six bytes of a GUID; prefixes shared by GUIDs from
    different files are marked ambiguous at build time and never labelled.
    """

    PREFIX = 6
    AMBIGUOUS = 0xFFFF

    def __init__(self, blob: bytes):
        raw = gzip.decompress(blob)
        if raw[:4] != b'DESE' or len(raw) < 16:
            raise ValueError('not an entity index')
        version, count, text_len = struct.unpack_from('<III', raw, 4)
        if version != 1 or 16 + text_len + count * (self.PREFIX + 2) != len(raw):
            raise ValueError('unsupported or truncated entity index')
        paths, _, levels = raw[16:16 + text_len].decode('utf-8').partition('\n\n')
        self.paths = paths.split('\n')
        self.levels = dict(line.split('\t', 1) for line in levels.splitlines() if '\t' in line)
        planes_at = 16 + text_len
        planes = [raw[planes_at + i * count:planes_at + (i + 1) * count] for i in range(self.PREFIX)]
        self.keys = [int.from_bytes(bytes(t), 'big') for t in zip(*planes)]
        column_at = planes_at + self.PREFIX * count
        self.owner = struct.unpack_from(f'<{count}H', raw, column_at)

    @classmethod
    def load(cls, path) -> 'EntityIndex':
        with open(path, 'rb') as handle:
            return cls(handle.read())

    def path(self, guid: bytes) -> str | None:
        key = int.from_bytes(guid[:self.PREFIX], 'big')
        at = bisect.bisect_left(self.keys, key)
        if at == len(self.keys) or self.keys[at] != key or self.owner[at] == self.AMBIGUOUS:
            return None
        return self.paths[self.owner[at]]

    def lookup(self, guid: bytes) -> str | None:
        """'Level · file' for display, or None when the GUID is not indexed."""
        path = self.path(guid)
        if path is None:
            return None
        world = re.search(r'm\d\d_\d\d', path)
        level = self.levels.get(world.group()) if world else None
        name = path.rsplit('/', 1)[-1]
        return f'{level} · {name}' if level else name


_DEFAULT: list = []


def default_index() -> EntityIndex | None:
    """The repository-root entity index, or None when it is absent or unreadable."""
    if not _DEFAULT:
        path = Path(__file__).resolve().parent.parent / 'entitydb.bin'
        try:
            _DEFAULT.append(EntityIndex.load(path))
        except (OSError, ValueError, EOFError, gzip.BadGzipFile, struct.error):
            _DEFAULT.append(None)
    return _DEFAULT[0]


def world_blobs(sf) -> list[tuple[Field, list[Group]]]:
    """Every blob in a save that decodes as world state, largest first."""
    found = []
    for record, _ in sf.walk():
        if record.type == T_BLOB:
            groups = decode(record.raw)
            if groups is not None and any(group.entries for group in groups):
                found.append((record, groups))
    return sorted(found, key=lambda pair: -len(pair[0].raw))
