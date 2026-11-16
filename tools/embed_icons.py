#!/usr/bin/env python3
"""Embed the icon pack (iconpack.json, from tools/build_icons.py) into the editor.

The page gets two constants between ICONS markers:

    ICON_IMAGES   base64 WebP images (80 x 92)
    ICON_OF       Map of "cat:id" -> image index, or [male, female] for armour

Without a pack the block is written empty and the editor keeps its SVG glyphs.
Use --stdout to print only the block and --check to test that the page matches.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
START = '/* ICONS:START */'
END = '/* ICONS:END */'
ANCHOR = '/* ITEMDB:END */'


def icon_block(pack: dict | None) -> str:
    images = (pack or {}).get('images', [])
    items = (pack or {}).get('items', {})
    note = (pack or {}).get('note', 'No icon pack embedded; the editor draws its SVG glyphs.')
    lines = [START, '/* ' + note.replace('*/', '* /') + ' */', 'const ICON_IMAGES = [']
    lines.append(',\n'.join(json.dumps(image) for image in images))
    lines.append('];')
    lines.append('const ICON_OF = new Map(' + json.dumps(list(items.items()), separators=(',', ':')) + ');')
    lines.append(END)
    return '\n'.join(line for line in lines if line != '') + '\n'


def embed(html: str, pack: dict | None) -> str:
    block = icon_block(pack).rstrip('\n')
    if START in html and END in html:
        start, end = html.index(START), html.index(END) + len(END)
        return html[:start] + block + html[end:]
    if ANCHOR not in html:
        raise ValueError('Could not locate the ITEMDB block to place the icons after')
    at = html.index(ANCHOR) + len(ANCHOR)
    return html[:at] + '\n' + block + html[at:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--pack', type=Path, default=HERE / 'iconpack.json')
    parser.add_argument('--html', type=Path, default=HERE / 'des_editor.html')
    parser.add_argument('--stdout', action='store_true')
    parser.add_argument('--check', action='store_true', help='exit 1 when the page does not match the pack')
    args = parser.parse_args()
    pack = json.loads(args.pack.read_text(encoding='utf-8')) if args.pack.exists() else None
    if args.stdout:
        sys.stdout.write(icon_block(pack))
        return 0
    html = args.html.read_text(encoding='utf-8')
    updated = embed(html, pack)
    if args.check:
        if updated == html:
            print('page ICONS block matches the icon pack', file=sys.stderr)
            return 0
        print('page ICONS block differs from the icon pack; run tools/embed_icons.py', file=sys.stderr)
        return 1
    args.html.write_text(updated, encoding='utf-8')
    count = len(pack['images']) if pack else 0
    print(f'Embedded {count} icons for {len(pack["items"]) if pack else 0} items', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
