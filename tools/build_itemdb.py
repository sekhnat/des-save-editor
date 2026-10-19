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
import re
import struct
import sys

BND_TABLES = {
    'EquipParamGoods.param': 'Goods', 'EquipParamWeapon.param': 'Weapon',
    'EquipParamProtector.param': 'Armor', 'EquipParamAccessory.param': 'Ring',
    'Magic.param': 'Spell', 'Skill.param': 'Skill',
}
TEXT_TABLES = {'goods': 'Goods', 'weapon': 'Weapon', 'protector': 'Armor',
               'accessory': 'Ring', 'magic': 'Spell', 'skill': 'Skill'}


def parse_bnd3(data: bytes) -> list[tuple[str, bytes]]:
    """Read the observed BND3 layout (0x20-byte header, 0x18-byte entries).

    Each entry starts with flags; size, offset, ID, and name offset follow.
    Unrecognized layouts and out-of-bounds data are refused, not guessed.
    """
    if len(data) < 0x20 or data[:4] != b'BND3':
        raise ValueError('not a complete BND3 container')
    count = struct.unpack_from('<I', data, 0x10)[0]
    if count > 10000 or 0x20 + count * 0x18 > len(data):
        raise ValueError('BND3 entry table exceeds file bounds')
    files = []
    for index in range(count):
        size, offset, _, nameoff = struct.unpack_from('<IIII', data, 0x24 + index * 0x18)
        if offset > len(data) or size > len(data) - offset or nameoff >= len(data):
            raise ValueError(f'BND3 entry {index} exceeds file bounds')
        end = data.find(b'\0', nameoff)
        if end == -1:
            raise ValueError(f'BND3 entry {index} name is unterminated')
        name = data[nameoff:end].decode('ascii', 'strict').replace('\\', '/').rsplit('/', 1)[-1]
        files.append((name, data[offset:offset + size]))
    return files


def parse_param(data: bytes) -> set[int]:
    """Return exact PARAM row IDs; unverified internal-name offsets are ignored."""
    if len(data) < 0x30:
        raise ValueError('PARAM header is truncated')
    rows = struct.unpack_from('<H', data, 0x0A)[0]
    if 0x30 + rows * 12 > len(data):
        raise ValueError('PARAM row index exceeds file bounds')
    return {struct.unpack_from('<I', data, 0x30 + index * 12)[0] for index in range(rows)}


def parse_ctxt(path: str | Path, table: str) -> dict[int, str]:
    path = Path(path)
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8-sig')
    pattern = re.compile(re.escape(table.upper()) + r'_NAME_(\d+):[0-9a-fA-F]+=([^\r\n]*)')
    return {int(match[1]): match[2].strip() for match in pattern.finditer(text)}


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
