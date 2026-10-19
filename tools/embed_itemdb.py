#!/usr/bin/env python3
"""Embed every category-scoped catalog entry into the offline HTML editor.

Use --stdout to emit only the replacement script block (useful for build tools).
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


def catalog_block(doc: dict) -> str:
    rows = [[entry['id'], entry['name'], CATS.get(entry['category'], '?')] for entry in doc['items']]
    # Escaping < prevents a localized name from terminating the inline script.
    encoded = [json.dumps(row, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
               .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029') for row in rows]
    return START + '\nconst ITEMDB = [\n' + ',\n'.join(encoded) + '\n];\n' + END + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=HERE / 'itemdb.json')
    parser.add_argument('--html', type=Path, default=HERE / 'des_editor.html')
    parser.add_argument('--stdout', action='store_true')
    args = parser.parse_args()
    doc = json.loads(args.db.read_text(encoding='utf-8'))
    block = catalog_block(doc)
    if args.stdout:
        sys.stdout.write(block)
    else:
        html = args.html.read_text(encoding='utf-8')
        if START in html and END in html:
            start, end = html.index(START), html.index(END) + len(END)
            updated = html[:start] + block.rstrip('\n') + html[end:]
        else:
            pattern = r'^const ITEMDB = \[.*?\];'
            updated, count = re.subn(pattern, lambda _: block.rstrip('\n'), html, count=1, flags=re.M | re.S)
            if count != 1:
                raise ValueError('Could not locate one ITEMDB declaration')
        args.html.write_text(updated, encoding='utf-8')
    print(f"Embedded {len(doc['items'])} category-scoped entries (all ID widths)", file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
