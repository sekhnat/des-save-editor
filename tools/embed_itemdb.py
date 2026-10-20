#!/usr/bin/env python3
"""Embed every category-scoped catalog entry into the offline HTML editor.

Rows keep their historical meanings and gain creation metadata for add-item:

    [id, name, cat]                                  text-only / schema-3 entry
    [id, name, cat, limit, box]                      schema-3 entry with limits
    [id, name, cat, limit, box, sort, init, ammo]    PARAM-backed entry (schema 4)

limit is maxQuantity for goods and durabilityMax for weapons and armor; sort is
the PARAM sortId (None for unusable values such as the -1 placeholder rows);
init is the initial durability of weapons and armor; ammo is 1 for arrows and
bolts. Old catalogs without the extra fields still embed unchanged, which
disables add-item but not browsing or existing edits.

Use --stdout to emit only the replacement script block (useful for build tools)
and --check to test that the page matches itemdb.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]
CATS = {'Goods': 'G', 'Weapon': 'W', 'Armor': 'A', 'Ring': 'R', 'Spell': 'S', 'Skill': 'K'}
START = '/* ITEMDB:START */'
END = '/* ITEMDB:END */'


def _row(entry: dict) -> list:
    row = [entry['id'], entry['name'], CATS.get(entry['category'], '?')]
    limit = entry.get('maxQuantity', entry.get('durabilityMax'))
    if 'sortId' not in entry:
        # Schema-3 entry (or a text-only row): keep the historical 3/5-column shape.
        if limit is not None:
            row += [limit, entry.get('maxStorageQuantity')]
        return row
    sort = entry['sortId']
    row += [limit, entry.get('maxStorageQuantity'),
            sort if isinstance(sort, int) and 0 <= sort <= 0xFFFF else None,
            entry.get('durability'),
            1 if entry.get('ammo') else 0]
    return row


def catalog_block(doc: dict) -> str:
    rows = [_row(entry) for entry in doc['items']]
    # Escaping < prevents a localized name from terminating the inline script.
    encoded = [json.dumps(row, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
               .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029') for row in rows]
    classes = json.dumps([[c['archetype'], c['name'], c['row']] for c in doc.get('classes', [])],
                         ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return (START + '\nconst ITEMDB = [\n' + ',\n'.join(encoded) + '\n];\n'
            + 'const CLASSES = ' + classes + ';\n' + END + '\n')


def embed(html: str, doc: dict) -> str:
    """Return the page with its ITEMDB/CLASSES block replaced from doc."""
    block = catalog_block(doc)
    if START in html and END in html:
        start, end = html.index(START), html.index(END) + len(END)
        return html[:start] + block.rstrip('\n') + html[end:]
    updated, count = re.subn(r'^const ITEMDB = \[.*?\];', lambda _: block.rstrip('\n'),
                             html, count=1, flags=re.M | re.S)
    if count != 1:
        raise ValueError('Could not locate one ITEMDB declaration')
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=HERE / 'itemdb.json')
    parser.add_argument('--html', type=Path, default=HERE / 'des_editor.html')
    parser.add_argument('--stdout', action='store_true')
    parser.add_argument('--check', action='store_true',
                        help='exit 1 when the page does not match itemdb.json')
    args = parser.parse_args()
    doc = json.loads(args.db.read_text(encoding='utf-8'))
    html = args.html.read_text(encoding='utf-8')
    updated = embed(html, doc)
    if args.stdout:
        sys.stdout.write(catalog_block(doc))
        return 0
    if args.check:
        if updated == html:
            print('page ITEMDB block matches itemdb.json', file=sys.stderr)
            return 0
        print('page ITEMDB block differs from itemdb.json; run tools/embed_itemdb.py',
              file=sys.stderr)
        return 1
    args.html.write_text(updated, encoding='utf-8')
    print(f"Embedded {len(doc['items'])} category-scoped entries (all ID widths)", file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())