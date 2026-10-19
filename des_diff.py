"""Record-level diff between two saves, for building a differential corpus.

The save is append-only in practice: a character that has played longer holds
every record a fresh one holds, plus more.  That makes a before/after pair of
the *same* character the only reliable way to learn what a record means, so
this module turns two saves into a machine-readable delta instead of a byte
wall.

Identity of a record is ``(key, occurrence)`` - the n-th record carrying that
key, in file order.  Appending records elsewhere does not renumber anything,
and a repeated key can never be confused with its sibling.  Index paths are
deliberately not used because an insertion shifts every later path.
"""

from __future__ import annotations

import collections

import des_fields
import des_save

M = 0xFFFFFFFF
P = 0x01000193
P_INV = pow(P, -1, 1 << 32)
DIGITS = '0123456789'


def _identity(field, seen: dict[int, int]) -> tuple[int, int]:
    occurrence = seen.get(field.key, 0)
    seen[field.key] = occurrence + 1
    return field.key, occurrence


def index(sf) -> dict[tuple[int, int], des_save.Field]:
    """Map every record to (key, occurrence-in-file-order)."""
    seen: dict[int, int] = {}
    return {_identity(field, seen): field for field, _ in sf.walk()}


def _shape(field) -> str:
    if field.is_container:
        return f'container[{len(field.children)}]'
    if field.type == des_save.T_BLOB:
        return f'blob {len(field.raw)}B'
    return repr(field.value)


def _arrays(records) -> list[dict]:
    """Group newly added keys into digit-suffixed arrays, name-free.

    Several states describe the same key set because the digit alphabet is not
    closed under XOR, so groups are deduplicated and any group contained in a
    larger one is dropped.
    """
    buckets: dict[int, list[int]] = collections.defaultdict(list)
    for key, _occurrence in records:
        buckets[(key * P_INV) & M].append(key)
    found: dict[frozenset[int], int] = {}
    for state in {state ^ ord(char) for state in buckets for char in DIGITS}:
        keys = []
        for char in DIGITS:
            keys.extend(buckets.get(state ^ ord(char), ()))
        if len(keys) >= 3:
            found.setdefault(frozenset(keys), state)
    groups = sorted(found.items(), key=lambda item: -len(item[0]))
    kept: list[dict] = []
    for keys, state in groups:
        if any(keys < other['keys_set'] for other in kept):
            continue
        kept.append({'state': state, 'keys_set': keys, 'keys': sorted(keys)})
    return [{key: value for key, value in group.items() if key != 'keys_set'}
            for group in kept]
def compare(before, after) -> dict:
    """Diff two parsed saves; both must be the same profile kind."""
    left = index(before)
    right = index(after)
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    changed = [identity for identity in sorted(set(left) & set(right))
               if (left[identity].type != right[identity].type
                   or left[identity].raw != right[identity].raw)]
    return {
        'before': {'size': len(before.build()), 'records': len(left),
                   'checksum_ok': before.checksum_ok},
        'after': {'size': len(after.build()), 'records': len(right),
                  'checksum_ok': after.checksum_ok},
        'added': [{'key': key, 'occurrence': occurrence,
                   'name': des_fields.field_name(key),
                   'shape': _shape(right[(key, occurrence)])}
                  for key, occurrence in added],
        'removed': [{'key': key, 'occurrence': occurrence,
                     'name': des_fields.field_name(key),
                     'shape': _shape(left[(key, occurrence)])}
                    for key, occurrence in removed],
        'changed': [{'key': key, 'occurrence': occurrence,
                     'name': des_fields.field_name(key),
                     'before': _shape(left[(key, occurrence)]),
                     'after': _shape(right[(key, occurrence)])}
                    for key, occurrence in changed],
        'added_arrays': _arrays(added),
    }


def summarise(delta: dict) -> str:
    """Human-readable digest: counts, then the interesting records."""
    lines = [
        f"before  {delta['before']['records']:>5} records  "
        f"{delta['before']['size']:>8} bytes",
        f"after   {delta['after']['records']:>5} records  "
        f"{delta['after']['size']:>8} bytes",
        f"added   {len(delta['added']):>5}   removed {len(delta['removed']):>5}"
        f"   changed {len(delta['changed']):>5}",
    ]
    if delta['added_arrays']:
        lines.append('')
        lines.append('new digit-suffixed arrays among the added records:')
        for group in delta['added_arrays']:
            lines.append(f"  state {group['state']:08x}  {len(group['keys'])} slots")
    named = [row for row in delta['changed'] if row['name']]
    if named:
        lines.append('')
        lines.append('changed records with known names:')
        for row in named:
            lines.append(f"  {row['name']:<26} {row['before']} -> {row['after']}")
    for label in ('added', 'removed'):
        rows = delta[label]
        if rows:
            lines.append('')
            lines.append(f"{label} records:")
            for row in rows[:24]:
                name = row['name'] or f"<{row['key']:08x}>"
                lines.append(f"  {name:<34} {row['shape']}")
            if len(rows) > 24:
                lines.append(f"  ... {len(rows) - 24} more")
    return '\n'.join(lines)
