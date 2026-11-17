"""Map layouts (MSB): the parts and events of each map, read-only.

The remake keeps the original game's map-studio files
(``cp11demonssouls/dvdroot/map/mapstudio/mWW_BB_CC_DD.msb``) with 64-bit
offsets, little-endian. A file is a chain of sections::

    u32 version  u32 pad  i64 name offset  i32 count  i32 pad
    count x i64 entry offset (the last one links to the next section, 0 ends)

Sections used here:

* ``PARTS_PARAM_ST``: every placed thing. An entry is ``i64 name offset,
  i32 type, i32 type index, i32 model index, ...``; ``i64`` at +0x68 points to
  its entity block, whose first ``i32`` is the **entity id** (-1 when none).
  Part types seen: 0 map piece, 1 object, 2 enemy, 4 player, 5 collision,
  8 navmesh, 9 dummy object, 10 dummy enemy, 11 connect collision.
* ``EVENT_PARAM_ST``: ``i64 name offset, i32 index, i32 type, i32 type index``
  then ``i64`` base-data and ``i64`` type-data offsets. Type 4 is a
  **treasure**: its type data is ``i32 0, i32 0, i32 part index, i32 -1,
  i32 item lot`` with a second lot at +6 (-1 when unused).

What ties this to the save: a treasure's part (a corpse or chest object) has
an entity id in the map's local flag range (10240 + 512 per sub-map), and that
id is the flag the game sets when the pickup is taken (docs/research-event-flags.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import struct

PART_TYPES = {0: "map piece", 1: "object", 2: "enemy", 4: "player", 5: "collision",
              8: "navmesh", 9: "dummy object", 10: "dummy enemy", 11: "connect collision"}
TREASURE = 4


@dataclass
class Part:
    index: int
    name: str
    type: int
    entity: int                      # -1 when the part has none
    position: tuple[float, float, float]


@dataclass
class Treasure:
    name: str
    part: int                        # index into Msb.parts
    lots: list[int] = field(default_factory=list)


@dataclass
class Msb:
    name: str                        # m06_00_00_00
    parts: list[Part]
    treasures: list[Treasure]

    @property
    def area(self) -> int | None:
        """0-based area of the map (m06 -> 5), None for test maps."""
        m = re.match(r'm0([1-8])_', self.name)
        return int(m.group(1)) - 1 if m else None


def _cstr(data: bytes, at: int) -> str:
    return data[at:data.index(b'\0', at)].decode('cp932', 'replace')


def sections(data: bytes) -> dict[str, list[int]]:
    """Section name -> entry offsets."""
    out, at = {}, 0
    for _ in range(64):
        name_offset, count = struct.unpack_from('<qi', data, at + 8)
        offsets = struct.unpack_from(f'<{count}q', data, at + 24)
        out[_cstr(data, name_offset)] = list(offsets[:-1])
        if offsets[-1] == 0:
            return out
        at = offsets[-1]
    raise ValueError("MSB section chain does not end")


def parse(data: bytes, name: str) -> Msb:
    secs = sections(data)
    parts = []
    for index, at in enumerate(secs.get('PARTS_PARAM_ST', [])):
        name_at, ptype = struct.unpack_from('<qi', data, at)
        entity_at = struct.unpack_from('<q', data, at + 0x68)[0]
        entity = struct.unpack_from('<i', data, at + entity_at)[0] if entity_at > 0 else -1
        parts.append(Part(index, _cstr(data, at + name_at), ptype, entity,
                          struct.unpack_from('<3f', data, at + 0x20)))
    treasures = []
    for at in secs.get('EVENT_PARAM_ST', []):
        name_at, _, etype = struct.unpack_from('<qii', data, at)
        if etype != TREASURE:
            continue
        type_at = struct.unpack_from('<q', data, at + 0x20)[0]
        values = struct.unpack_from('<8i', data, at + type_at)
        lots = [v for v in (values[4], values[6]) if v > 0]
        treasures.append(Treasure(_cstr(data, at + name_at), values[2], lots))
    return Msb(name, parts, treasures)


def msb_dir(game: Path) -> Path:
    return Path(game) / 'cp11demonssouls' / 'dvdroot' / 'map' / 'mapstudio'


def load_all(game: Path) -> list[Msb]:
    """Every regular map (m01..m08) of the game, in name order."""
    return [parse(path.read_bytes(), path.stem)
            for path in sorted(msb_dir(game).glob('m0[1-8]_*.msb'))]


def treasure_flags(msb: Msb) -> dict[int, dict]:
    """Entity id of each treasure's part -> {lots, part, map}."""
    out = {}
    for t in msb.treasures:
        if not 0 <= t.part < len(msb.parts):
            continue
        part = msb.parts[t.part]
        if part.entity > 0:
            entry = out.setdefault(part.entity, {"lots": [], "part": part.name,
                                                 "map": msb.name})
            entry["lots"] += [lot for lot in t.lots if lot not in entry["lots"]]
    return out
