"""Character attributes: move points between them at the same soul level.

The game shows and keeps PLAYER_CURRENT<ATTRIBUTE> (measured in Kyty on
2026-11-15: a save with VIT 60 / STR 40 written by the editor showed those
values on the Status screen and came back unchanged from the game's own
save). The PLAYER_BASE<ATTRIBUTE> records are left alone; their meaning is not
established. Max HP, MP and stamina are stored separately and the game did
not recompute them on load or save, so they keep their old values.

Soul level is sum(current attributes) - 80, so a redistribution that keeps the
sum keeps the soul level. Each attribute stays within the starting class's
value (CharaInitParam row 1000 + archetype) and 99.
"""
from __future__ import annotations

import des_fields
import des_items

ATTRS = list(des_fields.ATTRS)
SHORT = {'VIT': 'VITALITY', 'INT': 'INTELLIGENCE', 'END': 'ENDURANCE', 'STR': 'STRENGTH',
         'DEX': 'DEXTERITY', 'MAG': 'MAGIC', 'FAI': 'FAITH', 'LUC': 'LUCK'}
MAX_ATTRIBUTE = 99


def attributes(sf) -> dict[str, int | None]:
    return {name: sf.get('PLAYER_CURRENT' + name) for name in ATTRS}


def soul_level(values: dict[str, int | None]) -> int | None:
    if any(not isinstance(v, int) for v in values.values()):
        return None
    return sum(values.values()) - 80


def class_floor(sf) -> dict[str, int]:
    """The starting class's attributes, or 1 for each when the class is unknown."""
    archetype = sf.get('PLAYER_ARCHETYPE')
    for row in des_items.load_classes():
        if row.get('archetype') == archetype and len(row.get('baseStats', [])) == len(ATTRS):
            return dict(zip(ATTRS, row['baseStats']))
    return {name: 1 for name in ATTRS}


def attribute_name(text: str) -> str:
    key = text.strip().upper()
    key = SHORT.get(key, key)
    if key.startswith('PLAYER_CURRENT'):
        key = key[len('PLAYER_CURRENT'):]
    if key not in ATTRS:
        raise ValueError(f'unknown attribute {text!r}; use one of {", ".join(SHORT)}')
    return key


def redistribute(sf, changes: dict[str, int]) -> dict[str, int]:
    """Set some current attributes, keeping the soul level; nothing changes on error."""
    before = attributes(sf)
    level = soul_level(before)
    if level is None:
        raise ValueError('this save has no complete set of current attributes')
    after = dict(before)
    for text, value in changes.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'{text} must be a whole number')
        after[attribute_name(text)] = value
    floor = class_floor(sf)
    for name in ATTRS:
        if not floor[name] <= after[name] <= MAX_ATTRIBUTE:
            raise ValueError(f'{name.lower()} must be {floor[name]}..{MAX_ATTRIBUTE} '
                             f'(the starting class has {floor[name]})')
    moved = soul_level(after) - level
    if moved:
        raise ValueError(f'the new attributes are {abs(moved)} point{"s" * (abs(moved) != 1)} '
                         f'{"over" if moved > 0 else "under"} soul level {level}; '
                         'take them from or give them to another attribute')
    for name in ATTRS:
        if after[name] != before[name] and not sf.set('PLAYER_CURRENT' + name, after[name]):
            raise ValueError(f'PLAYER_CURRENT{name} is missing')
    return after
