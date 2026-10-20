"""Category-aware item catalog, and the dead-enemy index list.

The catalog maps (category, id) to a name. IDs are category-specific: Goods
1000 and Spell 1000 are different items.

The u16 records once treated as a candidate inventory are
``DEADENEMIES_INDICES####`` followed by ``DEADENEMIES_COUNT``: indices of
enemies that stay dead. The real inventory is read by des_inventory.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import des_fields
from des_save import T_U16

M = 0xFFFFFFFF
P = 0x01000193
# Measured FNV states of each 10-key chunk of DEADENEMIES_INDICES####.  These are the value the base name
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
COUNT_KEY = 0xCC62FF39                  # DEADENEMIES_COUNT


def slot_key(index: int) -> int:
    """Key of DEADENEMIES_INDICES<index>, for the 40 indices measured before the name was known."""
    if type(index) is not int or not 0 <= index < 10 * SLOT_CHUNKS:
        raise ValueError('only measured key indices 0..39 are supported')
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


def dead_enemies(sf) -> list[int]:
    """Values of DEADENEMIES_INDICES#### in file order (read-only)."""
    return [f.value for f, _ in sf.walk()
            if f.type == T_U16 and (des_fields.field_name(f.key) or '').startswith('DEADENEMIES_INDICES')]
