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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from des_gamedata import parse_bnd3, parse_ctxt, parse_param  # noqa: E402

BND_TABLES = {
    'EquipParamGoods.param': 'Goods', 'EquipParamWeapon.param': 'Weapon',
    'EquipParamProtector.param': 'Armor', 'EquipParamAccessory.param': 'Ring',
    'Magic.param': 'Spell', 'Skill.param': 'Skill',
}
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
    if not items:
        raise ValueError('No PARAM rows or localized names found in the supplied game folder')
    rows = sorted(items.values(), key=lambda entry: (entry['category'], entry['id']))
    return {'schema': 2, 'language': language, 'count': len(rows),
            'categories': dict(sorted(Counter(entry['category'] for entry in rows).items())),
            'note': 'IDs are category-specific; save-field mappings are not established by this catalog.',
            'items': rows}


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
