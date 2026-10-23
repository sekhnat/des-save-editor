"""Category-aware item catalog, and the dead-enemy index list.

The catalog maps (category, id) to a name. IDs are category-specific: Goods
1000 and Spell 1000 are different items.

The u16 records once treated as a candidate inventory are
``DEADENEMIES_INDICES####`` followed by ``DEADENEMIES_COUNT``: indices of
enemies that stay dead. The real inventory is read by des_inventory.py.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

import des_fields
from des_save import FNV_PRIME as P, MASK32 as M, T_U16

DATA_DIR = Path(__file__).resolve().parent.parent      # itemdb.json lives in the repo root

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


@functools.lru_cache(maxsize=4)
def _read_itemdb(path: str, mtime_ns: int, size: int) -> dict:
    """Parsed catalog document; mtime and size in the key make a rewritten file reload."""
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def _itemdb(path: str | None) -> dict | None:
    path = Path(path) if path is not None else DATA_DIR / 'itemdb.json'
    try:
        info = path.stat()
    except OSError:
        return None
    return _read_itemdb(str(path), info.st_mtime_ns, info.st_size)


def load_catalog(path: str | None = None) -> list[dict]:
    """Catalog rows. The list is shared between calls: treat it as read-only."""
    doc = _itemdb(path)
    return [] if doc is None else doc['items']


def load_classes(path: str | None = None) -> list[dict]:
    """Starting classes from catalog schema 3 (archetype -> name, base stats)."""
    doc = _itemdb(path)
    return [] if doc is None else doc.get('classes', [])


CREATABLE_CATEGORIES = ('Weapon', 'Armor', 'Ring', 'Goods')


def creation_problem(entry: dict | None) -> str | None:
    """Why add-item cannot create this catalog entry, or None when it can.

    Creation needs a PARAM-backed row (schema 4): a usable display sort id for
    the packed display id, initial durability for weapons and armor, and a
    stack limit for goods. Text-only rows, placeholder rows (sortId -1, e.g.
    No Equipment) and unsupported categories stay reference-only.
    """
    if not isinstance(entry, dict) or 'category' not in entry:
        return 'no usable catalog data'
    if entry['category'] not in CREATABLE_CATEGORIES:
        return 'only weapons, armor, rings and goods can be added'
    if 'sortId' not in entry:
        return 'text-only or outdated catalog entry; no PARAM creation data'
    sort = entry['sortId']
    if not isinstance(sort, int) or not 0 <= sort <= 0xFFFF:
        return 'unused or placeholder PARAM row (no display sort id)'
    if entry['category'] in ('Weapon', 'Armor') and 'durability' not in entry:
        return 'weapon/armor PARAM row without durability data'
    if entry['category'] == 'Goods' and 'maxQuantity' not in entry:
        return 'goods PARAM row without quantity data'
    return None

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
