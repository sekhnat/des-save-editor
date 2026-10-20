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

Editing is limited to values whose meaning is corroborated and whose size
never changes: inventory quantity and durability, and the storage low-quantity
byte. Adding or removing entries and changing item IDs are not offered,
because the roles of DISPLAYID and VARIATIONID are not verified.
"""
from __future__ import annotations

import des_items
from des_save import T_I32, T_RAW4, T_U8

CATEGORY_BITS = {0x0: 'Weapon', 0x1: 'Armor', 0x2: 'Ring', 0x4: 'Goods'}
MAX_ENTRIES = 100                              # what a %02d template can address
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


def _catalog() -> dict[tuple[str, int], str]:
    return {(entry['category'], entry['id']): entry['name'] for entry in des_items.load_catalog()}


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
                     'name': catalog.get((kind, item_id)),
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
                     'name': catalog.get((kind, item_id)),
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
    for index in range(MAX_ENTRIES):
        inv = sf.find(f'EQUIPMENT_SLOT{index:02d}_INVENTORYID')
        equip = sf.find(f'EQUIPMENT_SLOT{index:02d}_EQUIPMENTID')
        if inv is None and equip is None:
            continue
        item = items.get(inv.value) if inv is not None else None
        kind = item['category'] if item else None
        item_id = equip.value if equip is not None else None
        rows.append({'slot': index, 'inventory': inv.value if inv is not None else None,
                     'id': item_id, 'category': kind,
                     'name': catalog.get((kind, item_id)) or (item['name'] if item else None)})
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
