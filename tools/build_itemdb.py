#!/usr/bin/env python3
"""Build a category-aware catalog from PARAM row IDs and localized name tables.

Numeric IDs belong to their table's namespace, NOT to one global item namespace.
Catalog extraction does not establish how a particular save record encodes an item.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from des_gamedata import load_params, parse_bnd3, parse_ctxt, parse_param  # noqa: E402

# Creation metadata (add-item): display sort id, initial durability and the
# stackable-ammunition classification, read from the equip PARAMs.
CREATION_TABLES = {'Weapon': 'EQUIP_PARAM_WEAPON_ST', 'Armor': 'EQUIP_PARAM_PROTECTOR_ST',
                   'Ring': 'EQUIP_PARAM_ACCESSORY_ST', 'Goods': 'EQUIP_PARAM_GOODS_ST'}
AMMO_CATEGORIES = (13, 14)          # weaponCategory: arrows and bolts
BND_TABLES = {
    'EquipParamGoods.param': 'Goods', 'EquipParamWeapon.param': 'Weapon',
    'EquipParamProtector.param': 'Armor', 'EquipParamAccessory.param': 'Ring',
    'Magic.param': 'Spell', 'Skill.param': 'Skill',
}
# Per-category limits read through the PARAMDEFs (field names are the game's own).
LIMITS = {
    'Goods': ('EQUIP_PARAM_GOODS_ST', {'maxQuantity': 'maxQuantity',
                                       'maxStorageQuantity': 'maxStorageQuantity'}),
    'Weapon': ('EQUIP_PARAM_WEAPON_ST', {'durabilityMax': 'durabilityMax',
                                         'originEquipWep': 'origin'}),
    'Armor': ('EQUIP_PARAM_PROTECTOR_ST', {'durabilityMax': 'durabilityMax'}),
}
# CharaInitParam rows 1000-1009 are the ten starting classes. The rows carry
# no class name, so each is identified by its starting right-hand weapon,
# which is unique per class in the original game.
CLASS_ROW_BASE = 1000
CLASS_BY_WEAPON = {
    'Broadsword': 'Soldier', 'Long Sword': 'Knight', 'Battle Axe': 'Hunter',
    'Mace': 'Priest', 'Short Sword': 'Magician', 'Falchion': 'Wanderer',
    'Club': 'Barbarian', 'Dagger': 'Thief', 'Halberd': 'Temple Knight',
    'Rapier': 'Royalty',
}
STATS = ('baseVit', 'baseWil', 'baseEnd', 'baseStr', 'baseDex', 'baseMag', 'baseFai', 'baseLuc')
TEXT_TABLES = {'goods': 'Goods', 'weapon': 'Weapon', 'protector': 'Armor',
               'accessory': 'Ring', 'magic': 'Spell', 'skill': 'Skill'}


def build_catalog(game: str | Path, language: str = 'en-gb') -> dict:
    game = Path(game)
    dvd = game / 'cp11demonssouls/dvdroot'
    textdirs = (game / 'text/ds/_cmn', dvd / 'text/ds/_cmn')
    textdir = next((path for path in textdirs if path.is_dir()), None)
    items = {}
    if textdir:
        for table, category in TEXT_TABLES.items():
            for item_id, name in parse_ctxt(textdir / f'{table}_name.{language}.ctxt', table).items():
                items[category, item_id] = {'id': item_id, 'category': category,
                                            'name': name or f'Unlabelled {category} {item_id}',
                                            'hasParam': False}
    bnd = dvd / 'param/gameparam/gameparam.parambnd'
    if bnd.exists():
        for name, payload in parse_bnd3(bnd.read_bytes()):
            category = BND_TABLES.get(name)
            if not category:
                continue
            for item_id in parse_param(payload):
                entry = items.setdefault((category, item_id),
                                         {'id': item_id, 'category': category,
                                          'name': f'Unlabelled {category} {item_id}'})
                entry['hasParam'] = True
    try:
        tables = load_params(game)
    except (OSError, ValueError):
        tables = {}
    for category, (table, wanted) in LIMITS.items():
        for (kind, item_id), entry in items.items():
            row = tables.get(table, {}).get(item_id) if kind == category else None
            if row:
                for source, target in wanted.items():
                    value = row.get(source)
                    if value is not None and not (target == 'origin' and value < 0):
                        entry[target] = value
    # Creation metadata for add-item: display sort position and initial durability
    # come from the same equip PARAMs, so nothing here is hard-coded per item.
    # weaponCategory 13/14 mark stackable arrows/bolts.
    for (kind, item_id), entry in items.items():
        row = tables.get(CREATION_TABLES.get(kind, ''), {}).get(item_id)
        if not row:
            continue
        if 'sortId' in row:
            entry['sortId'] = row['sortId']
        if 'durability' in row and kind in ('Weapon', 'Armor'):
            entry['durability'] = row['durability']
        if row.get('weaponCategory') in AMMO_CATEGORIES:
            entry['ammo'] = True
    classes = _classes(tables.get('CHARACTER_INIT_PARAM', {}), items)
    if not items:
        raise ValueError('No PARAM rows or localized names found in the supplied game folder')
    rows = sorted(items.values(), key=lambda entry: (entry['category'], entry['id']))
    return {'schema': 4, 'language': language, 'count': len(rows),
            'categories': dict(sorted(Counter(entry['category'] for entry in rows).items())),
            'note': 'IDs are category-specific. Limits, sort ids, durability and the '
                    'ammunition classification come from the equip PARAMs via their PARAMDEFs.',
            'classes': classes, 'items': rows}


def _classes(rows: dict[int, dict], items: dict) -> list[dict]:
    """Starting classes: archetype N is CharaInitParam row 1000+N."""
    out = []
    for archetype in range(10):
        row = rows.get(CLASS_ROW_BASE + archetype)
        if not row:
            continue
        weapon = items.get(('Weapon', row['equip_Wep_Right']), {}).get('name')
        stats = [row[name] for name in STATS]
        out.append({'archetype': archetype, 'row': CLASS_ROW_BASE + archetype,
                    'name': CLASS_BY_WEAPON.get(weapon), 'startingWeapon': weapon,
                    'baseStats': stats, 'soulLevel': sum(stats) - 80,
                    'source': 'CharaInitParam row; class identified by its starting weapon'})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', help='PPSA01342-app folder')
    parser.add_argument('-o', '--out', default='itemdb.json', help='output path; - for stdout')
    parser.add_argument('--lang', default='en-gb')
    args = parser.parse_args(argv)
    try:
        doc = build_catalog(args.game, args.lang)
        text = json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
        if args.out == '-':
            sys.stdout.write(text)
        else:
            Path(args.out).write_text(text, encoding='utf-8')
        print(f"{doc['count']} catalog entries: {doc['categories']}", file=sys.stderr)
        return 0
    except (OSError, ValueError) as error:
        print(f'catalog build failed: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
