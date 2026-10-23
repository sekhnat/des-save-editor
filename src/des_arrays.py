"""Recovered fixed-slot arrays and blob-container introspection.

The save is not only a bag of scalars. Besides the u16 dead-enemy list handled
by :mod:`des_items`, it holds several *fixed-slot* arrays whose members share a
generated key family: every member key is ``(state ^ ord(digit)) * P`` for one
per-array FNV state.  That makes the arrays discoverable without knowing any
name, which is what this module does.

Discovery works by inverting FNV-1a: for an observed key ``k`` the pre-suffix
state is ``k * P^-1``, and the suffix character is ``state ^ ord(digit)``.
Grouping keys that resolve to the same state under a digit recovers the whole
array without knowing its base name. Most of these arrays have since been
named from the executable's templates (see des_fields.FAMILIES); listings
show those names next to the canonical slot letters.

Only structurally verified arrays (contiguous records, ascending offsets) are
reported as arrays.  Everything else stays opaque on purpose.
"""

from __future__ import annotations

import collections
import re

from des_save import (Field, FNV_INV as P_INV, FNV_PRIME as P, MASK32 as M,
                      T_BLOB, T_BOOL, T_F32, T_I32, T_U16, T_U8, name_key)
import des_fields
import des_items
import des_world

DIGITS = '0123456789'
EMPTY = -1                     # observed "empty slot" sentinel in i32 arrays


# --------------------------------------------------------------------------- #
#  Generic discovery
# --------------------------------------------------------------------------- #
def candidate_states(sf) -> dict[int, list[Field]]:
    """Map each inverse-FNV state to the unnamed, non-inventory fields under it."""
    known = {name_key(name) for name in des_fields.known_names()}
    scalars = (T_U8, T_U16, T_I32, T_F32, T_BOOL)
    buckets: dict[int, list[Field]] = collections.defaultdict(list)
    for field, _ in sf.walk():
        if field.type not in scalars:
            continue                       # blobs and strings are not slots
        if field.key in known or field.key in des_items.SLOT_KEY_SET:
            continue
        buckets[(field.key * P_INV) & M].append(field)
    return buckets


def canonical_state(members, state: int) -> int:
    """Pick the state that labels the slots 0..n-1.

    The trailing character of a member key is only defined up to an XOR of the
    whole alphabet: ``(state ^ c)`` and ``(state ^ k)`` describe the same keys
    with relabelled slots.  Choosing the labelling that reads 0,1,2,... makes
    the result deterministic across implementations and matches the inventory
    chunks, whose slots are genuinely labelled 0..9.
    """
    wanted = set(DIGITS[:len(members)])
    bases = [(member.key * P_INV) & M for member in members]
    candidates = []
    for base in bases:
        for char in wanted:
            candidate = base ^ ord(char)
            if {chr(one ^ candidate) for one in bases} == wanted:
                candidates.append(candidate)
    return min(candidates) if candidates else state


def discover(sf, alphabet: str = DIGITS, min_size: int = 3) -> list[dict]:
    """Find contiguous fixed-slot arrays of digit-suffixed keys.

    The returned groups are maximal: a strictly smaller group nested inside a
    larger one is dropped, because it is only a suffix of the same array.
    """
    buckets = candidate_states(sf)
    states = {state ^ ord(char) for state in buckets for char in alphabet}
    groups = []
    for state in states:
        members: list[Field] = []
        for char in alphabet:
            members.extend(buckets.get(state ^ ord(char), ()))
        if len(members) < min_size:
            continue
        offsets = sorted({field.offset for field in members})
        gaps = {b - a for a, b in zip(offsets, offsets[1:])}
        if len(gaps) != 1:
            continue                       # not a contiguous run -> not an array
        groups.append({
            'state': canonical_state(members, state),
            'stride': gaps.pop(),
            'alphabet': alphabet,
            'members': sorted(members, key=lambda field: field.offset),
            'first': offsets[0],
            'count': len(offsets),
        })
    groups.sort(key=lambda group: (-group['count'], group['first'], group['state']))
    kept: list[dict] = []
    for group in groups:
        span = {field.offset for other in kept
                for field in other['members']}
        if span & {field.offset for field in group['members']}:
            continue                       # subset of an already claimed array
        kept.append(group)
    return sorted(kept, key=lambda group: group['first'])


def key_for_state(state: int, char: str) -> int:
    """Key of one array member: the name is ``<unknown base><char>``."""
    return ((state ^ ord(char)) * P) & M


# Arrays whose recovered family name fixes the catalog category of their values.
FAMILY_CATEGORY = {'SPELLS_EQUIPPED': 'Spell', 'MIRACLES_EQUIPPED': 'Spell', 'TROPHIES_RING': 'Ring'}


def family_of(group: dict) -> str | None:
    """Common family name of an array's members, digits replaced by ##."""
    names = [des_fields.field_name(member.key) for member in group['members']]
    if not all(names):
        return None
    bases = {re.sub(r'\d+(?=_[A-Z]+$|$)', '##', name) for name in names}
    return bases.pop() if len(bases) == 1 else None


def label(group: dict, catalog: list[dict] | None = None) -> dict:
    """Describe an array: what it likely holds, and its decoded values.

    Small integers are *not* treated as item ids: the spell and skill tables
    also live in 0..2011, so every small number would otherwise "resolve".
    """
    values = [field.value for field in group['members']]
    if catalog is None:
        catalog = des_items.load_catalog()
    by_id: dict[int, list[dict]] = collections.defaultdict(list)
    for entry in catalog:
        by_id[entry['id']].append(entry)
    filled = [value for value in values if value != EMPTY]
    wide = [value for value in filled if value > 2011]      # outside spell/skill ids
    if not filled:
        kind, description = 'empty', 'all slots empty (-1)'
    elif EMPTY in values:
        kind = 'id slots'
        description = 'fixed-slot id list with -1 marking empty slots'
    elif wide and all(value in by_id for value in filled):
        kind = 'id slots'
        description = 'fixed-slot id list; ids exceed the spell/skill range'
    elif all(0 <= value < 256 for value in filled):
        kind = 'counters'
        description = 'fixed-slot list of small integers'
    elif all(value in by_id for value in filled):
        kind = 'id slots'
        description = 'fixed-slot id list'
    else:
        kind, description = 'values', 'fixed-slot list of 32-bit values'
    names = {}
    family = family_of(group)
    category = next((cat for prefix, cat in FAMILY_CATEGORY.items()
                     if family and family.startswith(prefix)), None)
    if category:
        lookup = {entry['id']: entry['name'] for entry in catalog if entry['category'] == category}
        for member, value in zip(group['members'], values):
            names[member.key] = 'empty' if value == EMPTY else lookup.get(value)
    elif kind == 'id slots':
        for member, value in zip(group['members'], values):
            candidates = by_id.get(value)
            names[member.key] = (
                ' / '.join(dict.fromkeys(entry['name'] for entry in candidates))
                if candidates else ('empty' if value == EMPTY else None))
    group['names'] = names
    return {'kind': kind, 'description': description, 'values': values,
            'names': names, 'filled': len(filled), 'family': family}


def suffix_of(key: int, state: int) -> str:
    """Recover the trailing character of a member key."""
    return chr(((key * P_INV) & M) ^ state)


def report(sf) -> list[dict]:
    """Every discovered array, labelled, with slots ordered by suffix character.

    The suffix character is the slot's identity: it is what ``set_slot``
    addresses.  File order is *not* suffix order, so displaying file order would
    make an editor write to a different slot than the one shown.
    """
    catalog = des_items.load_catalog()
    rows = []
    for index, group in enumerate(discover(sf)):
        info = label(group, catalog)
        slots = [{'char': suffix_of(member.key, group['state']),
                  'key': member.key,
                  'value': member.value,
                  'name': info['names'].get(member.key),
                  'field': des_fields.field_name(member.key)}
                 for member in group['members']]
        slots.sort(key=lambda slot: slot['char'])
        rows.append({'index': index, 'offset': group['first'], 'count': group['count'],
                     'stride': group['stride'], 'state': group['state'],
                     'type': group['members'][0].type, 'slots': slots, **info})
    return rows


# --------------------------------------------------------------------------- #
#  Editing
# --------------------------------------------------------------------------- #
def _parent_of(sf, field: Field):
    stack = [sf.records]
    while stack:
        rows = stack.pop()
        if any(row is field for row in rows):
            return rows
        for row in rows:
            if row.is_container:
                stack.append(row.children)
    return None


def _slot_of(sf, digest: int) -> dict:
    """Resolve a discovered array by its FNV state; reject anything else."""
    group = next((item for item in discover(sf) if item['state'] == digest), None)
    if group is None:
        raise ValueError(f'no contiguous array with state {digest:#010x}')
    return group


def set_slot(sf, state: int, char: str, value: int) -> Field:
    """Write one slot of a discovered array, creating the slot if it is absent."""
    group = _slot_of(sf, state)
    if char not in group['alphabet']:
        raise ValueError(f'slot suffix must be one of {group["alphabet"]!r}')
    if type(value) is not int:
        raise ValueError('slot values must be integers')
    key = key_for_state(state, char)
    existing = next((field for field in group['members'] if field.key == key), None)
    if existing is not None:
        existing.value = value
        return existing
    if group['members'][0].type != T_I32:
        raise ValueError('only 32-bit slot arrays can be extended')
    # Members can straddle a container boundary, so insert after the last one in
    # its own record list rather than in the list that holds the first.
    parent = _parent_of(sf, group['members'][-1])
    if parent is None:
        raise ValueError('array parent container was not found')
    added = Field(key, T_I32, value.to_bytes(4, 'little', signed=True))
    added.offset = group['members'][-1].offset + group['stride']
    parent.insert(parent.index(group['members'][-1]) + 1, added)
    return added


def clear_slot(sf, state: int, char: str) -> Field:
    """Mark a slot empty using the observed -1 sentinel."""
    return set_slot(sf, state, char, EMPTY)


# --------------------------------------------------------------------------- #
#  Blob containers
# --------------------------------------------------------------------------- #
def blobs(sf) -> list[dict]:
    """Every blob in the save; world-state containers are summarised.

    See :mod:`des_world` for the world-state framing.  Other blobs stay opaque.
    """
    rows = []
    for field, _ in sf.walk():
        if field.type != T_BLOB:
            continue
        groups = des_world.decode(field.raw)
        world = None
        if groups is not None and any(group.entries for group in groups):
            listed = [entry for _, _, entry in des_world.entries(groups)]
            world = {'groups': len(groups), 'entries': len(listed),
                     'parsed': sum(entry.records is not None for entry in listed)}
        rows.append({'key': field.key, 'name': des_fields.field_name(field.key),
                     'offset': field.offset, 'size': len(field.raw), 'world': world})
    return sorted(rows, key=lambda row: -row['size'])
