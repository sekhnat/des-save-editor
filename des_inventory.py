"""Inventory, storage box and equipment slots, read from their named records.

The game stores these as indexed record families whose names come from printf
templates in the executable (see des_fields.FAMILIES)::

    EQUIPMENT_INVENTORY_COUNT                       before the entries
    EQUIPMENT_INVENTORY##_INDEX / _TYPE / _EQUIPID / _QUANTITY / _VARIATIONID /
        _DISPLAYID / _DURABILITY_CURRENT / _DURABILITY_ACCUMULATEDHITS
    EQUIPMENT_STORAGEBOX##_EQUIPTYPEID / _LOWQUANTITY / _HIGHQUANTITY /
        _DISPLAYID / _DURABILITY / _DURABILITY_ACCUMULATEDHITS
    EQUIPMENT_STORAGEBOX_COUNT                      after the entries
    EQUIPMENT_SLOT##_INVENTORYID / _EQUIPMENTID     sparse slot numbers

Item categories come from the top four bits: ``_TYPE`` in the inventory and
the high bits of ``_EQUIPTYPEID`` in the storage box (0 weapon, 1 armor,
2 ring, 4 goods). With that, every item in the sample saves resolves to a
catalog entry. ``_QUANTITY`` is a 4-byte record holding a little-endian count.

Editing stays conservative: inventory quantity and durability, and the
storage low-quantity byte, change values whose size never changes. Stack and
durability limits from the equip PARAMs are reported as hints and enforced only
where creation metadata demands them, because a save may legitimately hold
other values.

Item creation (experimental, not yet verified in game) is offered for catalog
rows with PARAM creation data: ``with_added_item`` returns a validated candidate
SaveFile with one more entry in the inventory or the storage box. It follows the
record layout measured from real saves — ``INDEX == VARIATIONID ==`` the lowest
free 16-bit instance reference and ``DISPLAYID = (PARAM sortId << 16) | ref``
for inventory entries (kept sorted by reference, so later entries move up one
index; equipment slots and quick items hold references and are unaffected),
the ``-1`` display sentinel for directly created storage entries — and records newly acquired rings in the trophy history.
Removing entries, replacing item IDs and repairing malformed layouts remain
unsupported.
"""
from __future__ import annotations

import des_fields
import des_items
import des_save
from des_save import T_I32, T_RAW4, T_U8

CATEGORY_BITS = {0x0: 'Weapon', 0x1: 'Armor', 0x2: 'Ring', 0x4: 'Goods'}
MAX_ENTRIES = des_fields.BOX_LAST + 1          # inventory / storage names exist up to here
MAX_SLOTS = 100                                # equipment slots: what a %02d template can address
INVENTORY_PARTS = ('INDEX', 'TYPE', 'EQUIPID', 'QUANTITY', 'VARIATIONID', 'DISPLAYID',
                   'DURABILITY_CURRENT', 'DURABILITY_ACCUMULATEDHITS')
STORAGE_PARTS = ('EQUIPTYPEID', 'LOWQUANTITY', 'HIGHQUANTITY', 'DISPLAYID', 'DURABILITY',
                 'DURABILITY_ACCUMULATEDHITS')
PART_TYPES = {'QUANTITY': T_RAW4, 'LOWQUANTITY': T_U8, 'HIGHQUANTITY': T_U8}
MAX_QUANTITY = 999
MAX_DURABILITY = 9999


def category(value: int) -> str | None:
    """Item category from the top four bits of a TYPE / EQUIPTYPEID value."""
    return CATEGORY_BITS.get((value & 0xFFFFFFFF) >> 28)


def _catalog() -> dict[tuple[str, int], dict]:
    return {(entry['category'], entry['id']): entry for entry in des_items.load_catalog()}


def _name(catalog: dict, kind, item_id):
    entry = catalog.get((kind, item_id))
    return entry['name'] if entry else None


def _limit(catalog: dict, kind, item_id, field: str):
    entry = catalog.get((kind, item_id))
    return entry.get(field) if entry else None


def _entries(sf, prefix: str, parts: tuple[str, ...]) -> list[dict]:
    """Records of every present index; an entry is editable only when complete."""
    rows = []
    for index in range(MAX_ENTRIES):
        fields, ambiguous = {}, False
        for part in parts:
            found = [f for f in sf.find_all(f'{prefix}{index:02d}_{part}') if not f.is_container]
            if len(found) > 1:
                ambiguous = True
            if found:
                fields[part] = found[0]
        if not fields:
            continue
        typed = all(fields[p].type == PART_TYPES.get(p, T_I32) for p in fields)
        rows.append({'index': index, 'fields': fields,
                     'complete': len(fields) == len(parts) and typed and not ambiguous})
    return rows


def _value(fields: dict, part: str):
    field = fields.get(part)
    if field is None:
        return None
    if field.type == T_RAW4:
        return int.from_bytes(field.raw, 'little')
    return field.value


def inventory(sf, catalog: dict | None = None) -> list[dict]:
    catalog = _catalog() if catalog is None else catalog
    rows = []
    for entry in _entries(sf, 'EQUIPMENT_INVENTORY', INVENTORY_PARTS):
        f = entry['fields']
        kind = category(_value(f, 'TYPE') or 0) if 'TYPE' in f else None
        item_id = _value(f, 'EQUIPID')
        rows.append({'index': entry['index'], 'complete': entry['complete'],
                     'category': kind, 'id': item_id,
                     'name': _name(catalog, kind, item_id),
                     'max_quantity': _limit(catalog, kind, item_id, 'maxQuantity'),
                     'max_durability': _limit(catalog, kind, item_id, 'durabilityMax'),
                     'quantity': _value(f, 'QUANTITY'),
                     'durability': _value(f, 'DURABILITY_CURRENT'),
                     'hits': _value(f, 'DURABILITY_ACCUMULATEDHITS'),
                     'variation': _value(f, 'VARIATIONID'),
                     'display': _value(f, 'DISPLAYID'),
                     'ref': _value(f, 'INDEX')})
    return rows


def storage(sf, catalog: dict | None = None) -> list[dict]:
    catalog = _catalog() if catalog is None else catalog
    rows = []
    for entry in _entries(sf, 'EQUIPMENT_STORAGEBOX', STORAGE_PARTS):
        f = entry['fields']
        typed = _value(f, 'EQUIPTYPEID')
        kind = category(typed) if typed is not None else None
        item_id = (typed & 0x0FFFFFFF) if typed is not None else None
        low, high = _value(f, 'LOWQUANTITY'), _value(f, 'HIGHQUANTITY')
        rows.append({'index': entry['index'], 'complete': entry['complete'],
                     'category': kind, 'id': item_id,
                     'name': _name(catalog, kind, item_id),
                     'max_quantity': _limit(catalog, kind, item_id, 'maxStorageQuantity'),
                     'low_quantity': low, 'high_quantity': high,
                     'durability': _value(f, 'DURABILITY'),
                     'hits': _value(f, 'DURABILITY_ACCUMULATEDHITS'),
                     'display': _value(f, 'DISPLAYID')})
    return rows


def equipment(sf, catalog: dict | None = None) -> list[dict]:
    """Occupied equipment slots; names come via the referenced inventory entry."""
    catalog = _catalog() if catalog is None else catalog
    items = {row['ref']: row for row in inventory(sf, catalog)}
    rows = []
    for index in range(MAX_SLOTS):
        inv = sf.find(f'EQUIPMENT_SLOT{index:02d}_INVENTORYID')
        equip = sf.find(f'EQUIPMENT_SLOT{index:02d}_EQUIPMENTID')
        if inv is None and equip is None:
            continue
        item = items.get(inv.value) if inv is not None else None
        kind = item['category'] if item else None
        item_id = equip.value if equip is not None else None
        rows.append({'slot': index, 'inventory': inv.value if inv is not None else None,
                     'id': item_id, 'category': kind,
                     'name': _name(catalog, kind, item_id) or (item['name'] if item else None)})
    return rows


def _editable(sf, prefix: str, parts: tuple[str, ...], index: int) -> dict:
    for entry in _entries(sf, prefix, parts):
        if entry['index'] == index:
            if not entry['complete']:
                raise ValueError(f'{prefix}{index:02d} is incomplete or ambiguous; edit it by field name')
            return entry['fields']
    raise ValueError(f'{prefix}{index:02d} does not exist in this save')


def _whole(value, lo: int, hi: int, what: str) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f'{what} must be a whole number {lo}..{hi}')
    return value


def set_quantity(sf, index: int, quantity) -> None:
    """Inventory stack size; 0 is refused because it would leave an empty entry."""
    fields = _editable(sf, 'EQUIPMENT_INVENTORY', INVENTORY_PARTS, index)
    fields['QUANTITY'].raw = _whole(quantity, 1, MAX_QUANTITY, 'quantity').to_bytes(4, 'little')


def set_durability(sf, index: int, durability) -> None:
    fields = _editable(sf, 'EQUIPMENT_INVENTORY', INVENTORY_PARTS, index)
    fields['DURABILITY_CURRENT'].value = _whole(durability, 0, MAX_DURABILITY, 'durability')


def set_storage_quantity(sf, index: int, quantity) -> None:
    """Storage stack size, written to the low byte only.

    HIGHQUANTITY is 0 in every sample, so whether it is a high byte is not
    verified; quantities that would need it are refused.
    """
    fields = _editable(sf, 'EQUIPMENT_STORAGEBOX', STORAGE_PARTS, index)
    if fields['HIGHQUANTITY'].value != 0:
        raise ValueError('HIGHQUANTITY is non-zero; its meaning is not verified')
    fields['LOWQUANTITY'].value = _whole(quantity, 1, 255, 'storage quantity')

# --------------------------------------------------------------------------- #
#  Item creation (experimental, verified in memory but not yet in game)
# --------------------------------------------------------------------------- #

CREATION_CATEGORY_BITS = {name: code << 28 for code, name in CATEGORY_BITS.items()}
MAX_STORAGE_QUANTITY = 255          # LOWQUANTITY is one byte; HIGHQUANTITY stays 0

_FAMILY_KEYS: dict[str, dict[int, tuple[int, str]]] = {}


def _family_keyset(prefix: str, parts: tuple[str, ...]) -> dict[int, tuple[int, str]]:
    """key -> (record index, part), computed once per family."""
    keyset = _FAMILY_KEYS.get(prefix)
    if keyset is None:
        keyset = {des_save.name_key(f'{prefix}{index:02d}_{part}'): (index, part)
                  for index in range(MAX_ENTRIES) for part in parts}
        _FAMILY_KEYS[prefix] = keyset
    return keyset


def _i32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, 'little')


def _record(name: str, ftype: int, raw: bytes) -> des_save.Field:
    return des_save.Field(des_save.name_key(name), ftype, raw)


def _holds(record: des_save.Field, target: des_save.Field) -> bool:
    if record is target:
        return True
    return record.is_container and any(_holds(child, target) for child in record.children)


def _family_state(sf, destination: str) -> dict:
    """Validate the destination family and return everything creation needs.

    Counts must be unique 32-bit integers (top level or inside a top-level
    container) that match complete,
    unambiguously placed entries in the observed order (count before inventory
    entries, after storage entries). Anything else is refused, never repaired.
    """
    prefix, parts = {'inventory': ('EQUIPMENT_INVENTORY', INVENTORY_PARTS),
                     'storage': ('EQUIPMENT_STORAGEBOX', STORAGE_PARTS)}[destination]
    count_name = f'{prefix}_COUNT'
    count_key = des_save.name_key(count_name)
    counts = [f for f, _depth in sf.walk() if f.key == count_key and not f.is_container]
    if len(counts) != 1:
        raise ValueError(f'expected exactly one {count_name} record, found {len(counts)}')
    count = counts[0]
    if count.type != T_I32:
        raise ValueError(f'{count_name} must be a 32-bit integer record')
    # The game sometimes writes the count as the last child of a top-level
    # container that precedes the entries (container 0x4081F683 declaring 8
    # children instead of 5), so order is judged by the top-level record that
    # holds the count; the count itself is only ever updated in place.
    count_position = next(i for i, top in enumerate(sf.records) if _holds(top, count))

    keyset = _family_keyset(prefix, parts)
    top = {id(f): i for i, f in enumerate(sf.records)}
    found: dict[int, dict[str, des_save.Field]] = {}
    positions: list[int] = []
    positions = []
    for field, _depth in sf.walk():
        if field.key in keyset and not field.is_container:
            index, part = keyset[field.key]
            slot = found.setdefault(index, {})
            if part in slot:
                raise ValueError(f'{prefix}{index:02d}_{part} appears more than once')
            slot[part] = field
            if id(field) not in top:
                raise ValueError(f'{prefix}{index:02d}_{part} is nested in a container; '
                                 'that layout is not supported')
            positions.append(top[id(field)])
    indices = sorted(found)
    if indices != list(range(len(indices))):
        raise ValueError(f'{prefix} entries are not contiguous from 00: {indices[:8]}...')
    if count.value != len(indices):
        raise ValueError(f'{count_name} says {count.value}, records hold {len(indices)} entries')
    for index, slot in found.items():
        missing = [part for part in parts if part not in slot]
        if missing:
            raise ValueError(f'{prefix}{index:02d} is missing {", ".join(missing)}')
        for part, field in slot.items():
            if field.type != PART_TYPES.get(part, T_I32):
                raise ValueError(f'{prefix}{index:02d}_{part} has an unexpected record type '
                                 f'0x{field.type:02x}')
    if destination == 'inventory':
        refs = [found[i]['INDEX'].value for i in indices]
        if any(a >= b for a, b in zip(refs, refs[1:])):
            raise ValueError(f'{prefix} entries are not in ascending INDEX order; '
                             'the game keeps them sorted, so this layout is not supported')
    if indices:
        first, last = min(positions), max(positions)
        if destination == 'inventory' and count_position > first:
            raise ValueError(f'{count_name} must precede its entries')
        if destination == 'storage' and count_position < last:
            raise ValueError(f'{count_name} must follow its entries')
    return {'prefix': prefix, 'parts': parts, 'count': count, 'found': found,
            'positions': positions, 'count_position': count_position}


def _used_references(sf) -> set[int]:
    """16-bit instance references occupied in the inventory.

    The game hands out the lowest reference no inventory entry, equipment slot
    or quick item holds; storage display words may still carry a reference that
    has since been freed (the paired saves show inventory ref 49 coexisting
    with storage displays ending in 49), so they do not reserve one. Read
    leniently: only the destination family must fully validate.
    """
    used: set[int] = set()

    def add(value):
        if isinstance(value, int) and 0 <= value <= 0xFFFF:
            used.add(value)

    keyset = _family_keyset('EQUIPMENT_INVENTORY', INVENTORY_PARTS)
    for field, _depth in sf.walk():
        if field.is_container:
            continue
        hit = keyset.get(field.key)
        if hit is None:
            continue
        _index, part = hit
        if part in ('INDEX', 'VARIATIONID'):
            add(_value({part: field}, part))
        elif part == 'DISPLAYID':
            display = _value({part: field}, part)
            if display is not None and display >= 0:
                add(display & 0xFFFF)
    for index in range(MAX_SLOTS):
        field = sf.find(f'EQUIPMENT_SLOT{index:02d}_INVENTORYID')
        if field is not None and field.type == T_I32:
            add(field.value)
    for index in range(100):
        field = sf.find(f'EQUIPMENT_EQUIPITEM{index:02d}')
        if field is not None and field.type == T_I32:
            add(field.value)
    return used


def _lowest_free(used: set[int]) -> int:
    ref = 0
    while ref in used:
        ref += 1
    return ref


def _insertion_point(state: dict) -> int:
    """Position for new records: after the last entry record of the family.

    A non-empty inventory family ends before its unrelated records (the count is
    far earlier); an empty one starts right after its count. Storage entries sit
    before their count, so an empty storage family inserts at the count itself.
    """
    if state['positions']:
        return max(state['positions']) + 1
    if state['prefix'] == 'EQUIPMENT_INVENTORY':
        return state['count_position'] + 1
    return state['count_position']


def _ring_history(sf) -> tuple[list, int, des_save.Field, list[int]]:
    """(parent list, count position in it, count field, recorded ring ids)."""
    count_key = des_save.name_key('TROPHIES_RING_COUNT')
    def find(records):
        for index, field in enumerate(records):
            if field.key == count_key and not field.is_container:
                return records, index, field
            if field.is_container:
                hit = find(field.children)
                if hit is not None:
                    return hit
        return None
    hit = find(sf.records)
    if hit is None:
        raise ValueError('this save records no ring history (TROPHIES_RING_COUNT is absent)')
    parent, position, count = hit
    if count.type != T_I32:
        raise ValueError('TROPHIES_RING_COUNT must be a 32-bit integer record')
    total = count.value if isinstance(count.value, int) else -1
    if not 0 <= total <= 99:
        raise ValueError(f'TROPHIES_RING_COUNT {count.value} is out of range')
    member_keys = {k: des_save.name_key(f'TROPHIES_RING{k:02d}') for k in range(100)}
    recorded: list[int] = []
    for k in range(100):
        hits = [f for f, _ in sf.walk() if f.key == member_keys[k] and not f.is_container]
        expected = 1 if k < total else 0
        if len(hits) != expected:
            raise ValueError(f'ring history holds {len(hits)} records for slot {k:02d}, '
                             f'expected {expected} for TROPHIES_RING_COUNT {total}')
        if expected:
            if hits[0].type != T_I32:
                raise ValueError(f'TROPHIES_RING{k:02d} must be a 32-bit integer record')
            recorded.append(hits[0].value)
    return parent, position, count, recorded


def _check_new_keys_absent(candidate, names: list[str]) -> None:
    for name in names:
        key = des_save.name_key(name)
        if candidate.find_all(key):
            raise ValueError(f'the key for {name} already appears in this save; '
                             'refusing to create a colliding record')


def with_added_item(sf, category: str, item_id, quantity: int = 1,
                    destination: str = 'inventory',
                    catalog: dict | None = None) -> des_save.SaveFile:
    """Return a new SaveFile with one item added; `sf` is never modified.

    Supported for catalog rows that carry PARAM creation data (weapons, armor,
    rings, goods). Weapons, armor and rings become one independent entry;
    goods and ammunition stack into the destination's single matching stack or
    start a new one. A ring not yet in TROPHIES_RING## is recorded there.
    Raises ValueError and leaves nothing behind when the save or the request
    does not fit the rules; run it on a candidate and export only if you agree
    with the result.
    """
    if destination not in ('inventory', 'storage'):
        raise ValueError("destination must be 'inventory' or 'storage'")
    if isinstance(item_id, bool) or not isinstance(item_id, int) or not 0 <= item_id <= 0x0FFFFFFF:
        raise ValueError('item id must be a whole number 0..0x0FFFFFFF')
    catalog = _catalog() if catalog is None else catalog
    if not catalog:
        raise ValueError('item catalog not available; run tools/build_itemdb.py '
                         'against the game folder')
    entry = catalog.get((category, item_id))
    if entry is None:
        raise ValueError(f'no catalog entry for {category} {item_id}')
    problem = des_items.creation_problem(entry)
    if problem:
        raise ValueError(f'cannot add {category} {item_id} ({entry.get("name", "?")}): {problem}')
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError('quantity must be a whole number')
    bits = CREATION_CATEGORY_BITS[category]
    stackable = category == 'Goods' or entry.get('ammo') is True
    if stackable:
        if destination == 'inventory':
            cap = min(entry.get('maxQuantity', MAX_QUANTITY) if category == 'Goods'
                      else MAX_QUANTITY, MAX_QUANTITY)
        else:
            cap = min(entry.get('maxStorageQuantity', MAX_STORAGE_QUANTITY)
                      if category == 'Goods' else MAX_STORAGE_QUANTITY, MAX_STORAGE_QUANTITY)
        if not 1 <= quantity <= cap:
            raise ValueError(f'quantity must be a whole number 1..{cap} for this destination')
    elif quantity != 1:
        raise ValueError('weapons, armor and rings are added one copy at a time')

    candidate = des_save.SaveFile(sf.build())
    state = _family_state(candidate, destination)
    used = _used_references(candidate)
    created_index = len(state['found'])
    if created_index + 1 > MAX_ENTRIES:
        raise ValueError(f'this save already holds {created_index} entries; the editor '
                         'bound is 2048 (not a verified PS5 limit)')

    def destination_fields(slot):
        fields = slot
        if destination == 'inventory':
            return (_value(fields, 'TYPE'), _value(fields, 'EQUIPID'))
        return (_value(fields, 'EQUIPTYPEID') & 0xF0000000, _value(fields, 'EQUIPTYPEID') & 0x0FFFFFFF)

    matches = [slot for slot in state['found'].values() if destination_fields(slot) == (bits, item_id)] \
        if stackable else []
    initial_durability = entry.get('durability', 0) if category in ('Weapon', 'Armor') else 0
    if initial_durability > MAX_DURABILITY:
        raise ValueError('durability data exceeds the editor bound')

    prefix, parts = state['prefix'], state['parts']
    if len(matches) > 1:
        raise ValueError(f'the {destination} holds {len(matches)} stacks of {entry["name"]}; '
                         'refusing to pick one for you')
    if matches:
        fields = matches[0]
        if destination == 'inventory':
            current = _value(fields, 'QUANTITY')
            if current + quantity > cap:
                raise ValueError(f'{entry["name"]} would exceed its {cap} stack limit in the inventory')
            fields['QUANTITY'].raw = _i32(current + quantity)
        else:
            if fields['HIGHQUANTITY'].value != 0:
                raise ValueError('HIGHQUANTITY is non-zero; its meaning is not verified')
            current = fields['LOWQUANTITY'].value
            if current + quantity > cap:
                raise ValueError(f'{entry["name"]} would exceed its {cap} stack limit in storage')
            fields['LOWQUANTITY'].raw = bytes([current + quantity])
        new_records, new_ref = None, None
    else:
        if destination == 'inventory':
            # The game keeps entries sorted by reference and hands out the lowest
            # free one, so the new entry slots in by reference and every later
            # entry moves up one index (slots and quick items hold references).
            new_ref = _lowest_free(used)
            if new_ref > 0xFFFF:
                raise ValueError('no free 16-bit instance reference remains')
            _check_new_keys_absent(candidate, [f'{prefix}{len(state["found"]):02d}_{part}'
                                               for part in parts])
            created_index = sum(1 for slot in state['found'].values()
                                if slot['INDEX'].value < new_ref)
            names = [f'{prefix}{created_index:02d}_{part}' for part in parts]
            top = {id(f): i for i, f in enumerate(candidate.records)}
            if created_index < len(state['found']):
                at = min(top[id(f)] for f in state['found'][created_index].values())
            else:
                at = _insertion_point(state)
            for index in range(len(state['found']) - 1, created_index - 1, -1):
                for part, field in state['found'][index].items():
                    field.key = des_save.name_key(f'{prefix}{index + 1:02d}_{part}')
            values = {'INDEX': _i32(new_ref), 'TYPE': _i32(bits), 'EQUIPID': _i32(item_id),
                      'QUANTITY': _i32(quantity), 'VARIATIONID': _i32(new_ref),
                      'DISPLAYID': _i32((entry['sortId'] << 16) | new_ref),
                      'DURABILITY_CURRENT': _i32(initial_durability),
                      'DURABILITY_ACCUMULATEDHITS': _i32(0)}
            new_records = [_record(name, PART_TYPES.get(part, T_I32), values[part])
                           for part, name in zip(parts, names)]
        else:
            names = [f'{prefix}{created_index:02d}_{part}' for part in parts]
            _check_new_keys_absent(candidate, names)
            packed = {'EQUIPTYPEID': _i32(bits | item_id), 'DISPLAYID': _i32(-1),
                      'LOWQUANTITY': bytes([quantity]), 'HIGHQUANTITY': b'\0',
                      'DURABILITY': _i32(initial_durability),
                      'DURABILITY_ACCUMULATEDHITS': _i32(0)}
            new_records = [_record(name, PART_TYPES.get(part, T_I32), packed[part])
                           for part, name in zip(parts, names)]
            at = _insertion_point(state)
        candidate.records[at:at] = new_records
        state['count'].value += 1

    if category == 'Ring':
        parent, at, count, recorded = _ring_history(candidate)
        if item_id not in recorded:
            parent.insert(at, _record(f'TROPHIES_RING{len(recorded):02d}', T_I32, _i32(item_id)))
            count.value += 1

    raw = candidate.build()
    reparsed = des_save.SaveFile(raw)
    if reparsed.build() != raw or not reparsed.checksum_ok():
        raise ValueError('created save failed round-trip verification')
    revalidated = _family_state(reparsed, destination)
    if revalidated['count'].value != len(revalidated['found']):
        raise ValueError('created save failed its own consistency check')
    return candidate
