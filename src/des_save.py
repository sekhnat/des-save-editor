"""
Demon's Souls (PS5 / PPSA01341) save-file container.

File layout (little endian):

    +0x00  u32  version      always 7
    +0x04  u32  checksum     FNV-1a 32 of the payload (everything after the header)
    +0x08  u32  payload size
    +0x0C  u32  field count? always 1
    +0x10  ...  payload      sequence of fields

Each field is:

    u32  key     FNV-1a 32 of the (UPPERCASE) field name
    u8   type
    ...  value

    type 0x02  u8
    type 0x03  u16
    type 0x04  4 opaque bytes (never assume an integer byte order)
    type 0x06  container: LEB128 child count, then that many fields
    type 0x08  i32
    type 0x0A  f32
    type 0x0C  u8 (bool)
    type 0x0D  string: LEB128 byte length + UTF-8 bytes
    type 0x0E  blob:   LEB128 byte length + bytes

Field names are recovered by hashing candidate names with FNV-1a 32,
e.g. fnv1a("PLAYER_SOULS") == 0x76FD62AF.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import stat
import tempfile
import struct

MAGIC_VERSION = 7
MAX_FILE_SIZE = 16 * 1024 * 1024

MASK32 = 0xFFFFFFFF
FNV_PRIME = 0x01000193
FNV_INV = pow(FNV_PRIME, -1, 1 << 32)      # undoes one FNV-1a multiply

SIZES = {0x02: 1, 0x03: 2, 0x04: 4, 0x08: 4, 0x0A: 4, 0x0C: 1}

T_U8 = 0x02
T_U16 = 0x03
T_RAW4 = 0x04
T_CONTAINER = 0x06
T_I32 = 0x08
T_F32 = 0x0A
T_BOOL = 0x0C
T_STR = 0x0D
T_BLOB = 0x0E


# --------------------------------------------------------------------------- #
#  FNV-1a 32
# --------------------------------------------------------------------------- #
def fnv1a(data: bytes, h: int = 0x811C9DC5) -> int:
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & MASK32
    return h


def name_key(name: str) -> int:
    """Key used in the save file for field `name`."""
    return fnv1a(name.upper().encode())


# --------------------------------------------------------------------------- #
#  LEB128 helpers
# --------------------------------------------------------------------------- #
def _read_varint(buf: bytes, i: int, end: int | None = None) -> tuple[int, int]:
    end = len(buf) if end is None else end
    value = 0
    for n in range(5):
        if i >= end:
            raise ValueError("truncated LEB128 length")
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << (7 * n)
        if value > 0xFFFFFFFF:
            raise ValueError("LEB128 length exceeds uint32")
        if not b & 0x80:
            return value, i
    raise ValueError("LEB128 length exceeds five bytes")


def _write_varint(value: int) -> bytes:
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("LEB128 length must be a uint32")
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        out.append(b | (0x80 if value else 0))
        if not value:
            return bytes(out)


# --------------------------------------------------------------------------- #
#  Field model
# --------------------------------------------------------------------------- #
class Field:
    """One key / type / value entry of the save tree."""

    __slots__ = ("key", "type", "raw", "children", "offset", "name")

    def __init__(self, key: int, ftype: int, raw: bytes = b"",
                 children: list["Field"] | None = None, offset: int = 0):
        self.key = key
        self.type = ftype
        self.raw = raw
        self.children = children
        self.offset = offset
        self.name = None            # resolved field name, if known

    # -- kinds -------------------------------------------------------------
    @property
    def is_container(self) -> bool:
        return self.type == T_CONTAINER

    @property
    def is_float(self) -> bool:
        return self.type == T_F32

    @property
    def is_text(self) -> bool:
        return self.type in (T_STR, T_BLOB)

    @property
    def is_int(self) -> bool:
        return self.type in (T_U8, T_U16, T_I32, T_BOOL)

    # -- values ------------------------------------------------------------
    @property
    def value(self):
        if self.is_container:
            return self.children
        if self.type == T_F32:
            return struct.unpack("<f", self.raw)[0]
        if self.is_int:
            return int.from_bytes(self.raw, "little", signed=self.type == T_I32)
        return self.raw

    @value.setter
    def value(self, v) -> None:
        if self.is_container:
            raise ValueError("containers cannot be assigned scalar values")
        if self.type == T_F32:
            v = float(v)
            if not math.isfinite(v):
                raise ValueError("float edits must be finite")
            try:
                raw = struct.pack("<f", v)
            except (OverflowError, struct.error) as error:
                raise ValueError("value exceeds float32 range") from error
        elif self.is_int:
            if not isinstance(v, int):
                raise ValueError("integer edits must be whole numbers")
            raw = v.to_bytes(SIZES[self.type], "little", signed=self.type == T_I32)
        elif self.type == T_RAW4:
            raw = bytes.fromhex(v) if isinstance(v, str) else bytes(v)
            if len(raw) != 4:
                raise ValueError("type 0x04 needs exactly 4 bytes")
        else:
            raw = v.encode("utf-8") if isinstance(v, str) else bytes(v)
        self.raw = raw

    def text(self) -> str:
        return self.raw.decode("utf-8", "replace")

    def __repr__(self) -> str:                       # pragma: no cover
        if self.is_container:
            return f"<{self.key:#010x} container[{len(self.children)}]>"
        return f"<{self.key:#010x} t{self.type:02x} {self.value!r}>"


# --------------------------------------------------------------------------- #
#  Serialisation
# --------------------------------------------------------------------------- #
def parse(payload: bytes, start: int = 0, end: int | None = None,
          count: int | None = None, _depth: int = 0,
          _budget: list[int] | None = None) -> tuple[list[Field], int]:
    """Parse count-bounded records; reject truncated data and excessive nesting."""
    end = len(payload) if end is None else end
    if not 0 <= start <= end <= len(payload):
        raise ValueError("invalid record bounds")
    if _depth > 64:
        raise ValueError("container nesting exceeds 64 levels")
    budget = [100_000] if _budget is None else _budget
    out = []
    i = start
    while i < end and (count is None or len(out) < count):
        if end - i < 5:
            raise ValueError(f"truncated record header at {i:#x}")
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("too many records")
        offset = i
        key, ftype = struct.unpack_from("<IB", payload, i)
        i += 5
        if ftype == T_CONTAINER:
            n, i = _read_varint(payload, i, end)
            if n > (end - i) // 5:
                raise ValueError("container count exceeds remaining payload")
            children, i = parse(payload, i, end, n, _depth + 1, budget)
            out.append(Field(key, ftype, b"", children, offset))
            continue
        if ftype in SIZES:
            n = SIZES[ftype]
        elif ftype in (T_STR, T_BLOB):
            n, i = _read_varint(payload, i, end)
        else:
            raise ValueError(f"unknown field type {ftype:#04x} at {offset:#x}")
        if n > end - i:
            raise ValueError(f"truncated field payload at {offset:#x}")
        out.append(Field(key, ftype, payload[i:i + n], None, offset))
        i += n
    if count is not None and len(out) != count:
        raise ValueError(f"container wants {count} children, found {len(out)}")
    return out, i


def serialize(records: list[Field]) -> bytes:
    out = bytearray()
    _serialize_into(records, out)
    return bytes(out)


def _serialize_into(records: list[Field], out: bytearray) -> None:
    for f in records:
        if f.type in SIZES and len(f.raw) != SIZES[f.type]:
            raise ValueError(f"type {f.type:#04x} requires {SIZES[f.type]} bytes")
        out += f.key.to_bytes(4, "little")
        out.append(f.type)
        if f.type == T_CONTAINER:
            out += _write_varint(len(f.children))
            _serialize_into(f.children, out)
        elif f.type in (T_STR, T_BLOB):
            out += _write_varint(len(f.raw))
            out += f.raw
        else:
            out += f.raw


def walk_records(records: list[Field]):
    """Yield every record under `records`, depth first, containers before their children."""
    for f in records:
        yield f
        if f.is_container:
            yield from walk_records(f.children)


# --------------------------------------------------------------------------- #
#  Whole file
# --------------------------------------------------------------------------- #
class SaveFile:
    """A single USR-DATA file."""

    def __init__(self, data: bytes | None = None):
        self.version = MAGIC_VERSION
        self.field_c = 1
        self.records: list[Field] = []
        self._orig_checksum = 0
        self._orig_payload = b""
        if data is not None:
            self.load(data)

    # -- io ----------------------------------------------------------------
    def load(self, data: bytes) -> "SaveFile":
        if not 16 <= len(data) <= MAX_FILE_SIZE:
            raise ValueError("save must be 16 bytes–16 MiB")
        version, checksum, size, field_c = struct.unpack("<IIII", data[:16])
        if version != MAGIC_VERSION or field_c != 1:
            raise ValueError("unsupported save header (expected version 7 / marker 1)")
        payload = data[16:]
        if len(payload) != size:
            raise ValueError(f"payload size mismatch: header says {size}, "
                             f"file holds {len(payload)}")
        records, endpos = parse(payload)
        if endpos != len(payload):
            raise ValueError(f"parse stopped at {endpos:#x}, "
                             f"payload is {len(payload):#x} bytes")
        self.version = version
        self.field_c = field_c
        self.records = records
        self._orig_checksum = checksum
        self._orig_payload = payload
        return self

    def payload(self) -> bytes:
        return serialize(self.records)

    def build(self) -> bytes:
        payload = self.payload()
        header = struct.pack("<IIII", self.version, fnv1a(payload),
                             len(payload), self.field_c)
        return header + payload

    def checksum_ok(self) -> bool:
        return fnv1a(self._orig_payload) == self._orig_checksum

    # -- queries -----------------------------------------------------------
    def walk(self, records: list[Field] | None = None, depth: int = 0):
        for f in (self.records if records is None else records):
            yield f, depth
            if f.is_container:
                yield from self.walk(f.children, depth + 1)

    def key_index(self) -> dict[int, list[Field]]:
        """Non-container records by key, in file order; built fresh on every call.

        Use it to answer many `find` questions with one pass over the tree. It is
        deliberately not cached: records are renamed and inserted in place.
        """
        index: dict[int, list[Field]] = {}
        for f in walk_records(self.records):
            if not f.is_container:
                index.setdefault(f.key, []).append(f)
        return index

    def find(self, key: int | str) -> Field | None:
        if isinstance(key, str):
            key = name_key(key)
        for f, _ in self.walk():
            if f.key == key and not f.is_container:
                return f
        return None

    def find_all(self, key: int | str) -> list[Field]:
        if isinstance(key, str):
            key = name_key(key)
        return [f for f, _ in self.walk() if f.key == key]

    def get(self, name: str, default=None):
        f = self.find(name)
        return default if f is None else f.value

    def set(self, name: str, value) -> bool:
        f = self.find(name)
        if f is None:
            return False
        f.value = value
        return True

    # -- convenience -------------------------------------------------------
    def summary(self) -> dict:
        """Human readable overview of a player profile (best effort)."""
        from des_fields import ATTRS
        get = self.get
        name = get("PLAYER_NAME")
        if isinstance(name, (bytes, bytearray)):
            name = name.decode("utf-8", "replace")
        out = {"name": name, "souls": get("PLAYER_SOULS")}
        stats = {a.lower(): get(f"PLAYER_CURRENT{a}") for a in ATTRS}
        out["attributes"] = stats
        if all(v is not None for v in stats.values()):
            out["soul_level"] = sum(stats.values()) - 80
        out["hp"] = (get("PLAYER_CURRENTHP"), get("PLAYER_CURRENTMAXHP"),
                     get("PLAYER_BASEMAXHP"))
        out["mp"] = (get("PLAYER_CURRENTMP"), get("PLAYER_CURRENTMAXMP"),
                     get("PLAYER_BASEMAXMP"))
        out["sp"] = (get("PLAYER_CURRENTSP"), get("PLAYER_CURRENTMAXSP"),
                     get("PLAYER_BASEMAXSP"))
        pt = get("PLAYTIME")
        out["playtime_ms"] = pt
        out["playtime_s"] = (pt / 1000.0) if isinstance(pt, float) else None
        out["deaths"] = get("TRUEDEATHCOUNT")
        return out


# --------------------------------------------------------------------------- #
def read_bytes(path: str) -> bytes:
    """File contents, capped one byte past MAX_FILE_SIZE so oversized saves are rejected."""
    with open(path, "rb") as fh:
        return fh.read(MAX_FILE_SIZE + 1)


def load(path: str) -> SaveFile:
    return SaveFile(read_bytes(path))


def save(sf: SaveFile, path: str) -> None:
    """Validate, fsync, then atomically replace a file; callers handle backups."""
    data = sf.build()
    rebuilt = SaveFile(data)
    if not rebuilt.checksum_ok() or rebuilt.build() != data:
        raise ValueError("edited save failed round-trip verification")
    target = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if target.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(target.stat().st_mode))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":                            # pragma: no cover
    import sys
    for p in sys.argv[1:]:
        raw = read_bytes(p)
        s = SaveFile(raw)
        rebuilt = s.build()
        print(f"{p}\n  {len(raw)} bytes, {sum(1 for _ in s.walk())} fields, "
              f"checksum {'OK' if s.checksum_ok() else 'BAD'}, "
              f"round-trip {'identical' if rebuilt == raw else 'DIFFERS'}")
