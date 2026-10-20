#!/usr/bin/env python3
"""Embed entitydb.bin into the offline HTML editor as a base64 data block.

The block is a non-executing ``<script type="application/octet-stream">``
element, decoded by the page only when the World state view first needs it.
Without entitydb.bin the block is emptied and the page shows raw GUIDs.
Use --check to fail when the page does not carry the current index.
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]
OPEN = '<script id="entitydb" type="application/octet-stream">'
CLOSE = '</script>'
BLOCK = re.compile(re.escape(OPEN) + r'[A-Za-z0-9+/=\s]*' + re.escape(CLOSE))


def embed(html: str, blob: bytes | None) -> str:
    if len(BLOCK.findall(html)) != 1:
        raise ValueError('Could not locate one entitydb data block')
    data = base64.b64encode(blob).decode('ascii') if blob else ''
    return BLOCK.sub(lambda _: OPEN + data + CLOSE, html)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=HERE / 'entitydb.bin')
    parser.add_argument('--html', type=Path, default=HERE / 'des_editor.html')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    blob = args.db.read_bytes() if args.db.exists() else None
    html = args.html.read_text(encoding='utf-8')
    updated = embed(html, blob)
    if args.check:
        if updated != html:
            print('des_editor.html does not carry the current entitydb.bin; run tools/embed_entitydb.py',
                  file=sys.stderr)
            return 1
        return 0
    args.html.write_text(updated, encoding='utf-8')
    print(f"Embedded {len(blob) if blob else 0} bytes of entity index", file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
