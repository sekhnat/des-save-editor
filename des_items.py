"""Category-aware item catalog and experimental observed-u16-array helpers.

A catalog ID/name match does NOT establish that a save value is an inventory ID.
The four observed key groups and trailing count are editable structurally, but
stack quantities, equipment, storage and spells are not fully mapped.
"""
from __future__ import annotations

import json
from pathlib import Path

from des_save import Field, T_U16

M = 0xFFFFFFFF
P = 0x01000193
# Measured FNV states of each 10-slot chunk.  These are the value the base name
# hashes to *before* the slot character is appended, recovered by inverting
# FNV-1a over the observed member keys:
#     state = (key * P^-1 mod 2^32) ^ ord(slot_character)
# Chunks 0 and 2 sit one below their plain prefix (prefix ^ 1), which is why the
# slot characters there run 1,0,3,2,5,4,7,6,9,8 rather than 0..9.  Both readings
# yield the same 40-key set, so only the index -> key labelling is affected.
SLOT_STATES = [0x1544B3ED, 0x1444B25A, 0x1344B0C7, 0x1244AF34]
SLOT_PREFIXES = [state ^ 1 if index in (0, 2) else state
                 for index, state in enumerate(SLOT_STATES)]
SLOT_CHUNKS = len(SLOT_STATES)
COUNT_KEY = 0xCC62FF39


def slot_key(index: int) -> int:
    """Key of one observed slot; 0..39 is an editor bound, not a game limit."""
    if type(index) is not int or not 0 <= index < 10 * SLOT_CHUNKS:
        raise ValueError('only candidate key indices 0..39 are supported')
    chunk, digit = divmod(index, 10)
    return ((SLOT_STATES[chunk] ^ (ord('0') + digit)) * P) & M




ALL_SLOT_KEYS = [slot_key(index) for index in range(10 * SLOT_CHUNKS)]
SLOT_KEY_SET = frozenset(ALL_SLOT_KEYS)


def load_catalog(path: str | None = None) -> list[dict]:
    path = Path(path) if path is not None else Path(__file__).with_name('itemdb.json')
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)['items']


def load_db(path: str | None = None) -> dict[int, dict]:
    """Legacy numeric lookup retaining all category candidates instead of overwriting."""
    grouped = {}
    for entry in load_catalog(path):
        grouped.setdefault(entry['id'], []).append(entry)
    return {item_id: {'id': item_id, 'name': ' / '.join(dict.fromkeys(e['name'] for e in candidates)),
                      'category': ' / '.join(dict.fromkeys(e['category'] for e in candidates)),
                      'candidates': candidates}
            for item_id, candidates in grouped.items()}


def item_label(db: dict[int, dict], item_id: int) -> str:
    entry = db.get(item_id)
    return (f"{entry['name']}  [candidate: {entry['category']}]" if entry
            else f'unmapped value (id {item_id})')


def find_inventory(sf) -> dict | None:
    slots = [f for f, _ in sf.walk() if f.type == T_U16 and f.key in SLOT_KEY_SET]
    count = sf.find(COUNT_KEY)
    return {'slots': slots, 'count': count} if slots or count is not None else None


def inventory_ids(sf) -> list[int]:
    array = find_inventory(sf)
    return [f.value for f in array['slots']] if array else []


def _all_lists(sf):
    yield sf.records
    for field, _ in sf.walk():
        if field.is_container:
            yield field.children


def set_inventory(sf, ids: list[int]) -> None:
    """Validate the entire array operation before touching any live records."""
    if len(ids) > SLOT_CHUNKS * 10:
        raise ValueError('at most 40 candidate array keys are supported')
    if any(type(value) is not int or not 0 <= value <= 65535 for value in ids):
        raise ValueError('observed array values must be uint16 integers (0..65535)')
    counts = [f for f, _ in sf.walk() if f.key == COUNT_KEY and not f.is_container]
    if len(counts) != 1 or counts[0].type != T_U16:
        raise ValueError('a unique u16 array count is required')
    count = counts[0]
    slots = find_inventory(sf)['slots']
    parent = next(rows for rows in _all_lists(sf) if count in rows)
    start = parent.index(count) - len(slots)
    if (start < 0 or len({f.key for f in slots}) != len(slots)
            or parent[start:parent.index(count)] != slots):
        raise ValueError('array layout is ambiguous: slots must immediately precede their count')
    if count.value != len(slots):
        raise ValueError('array count mismatch; inspect raw records before editing')
    ids = sorted(ids)
    if ids == [f.value for f in slots]:
        return
    used = {f.key for f in slots}
    spare = iter(key for key in ALL_SLOT_KEYS if key not in used)
    replacements = [Field(slots[index].key if index < len(slots) else next(spare),
                          T_U16, value.to_bytes(2, 'little')) for index, value in enumerate(ids)]
    parent[start:start + len(slots)] = replacements
    count.value = len(ids)
