#!/usr/bin/env python3
"""Extract the game's inventory icons and map them to catalog items.

The remake keeps every inventory icon in its UI atlas (see src/des_uiatlas.py).
Each icon sprite is named ``Tex_InvIcon_<key>``; the key comes from fields the
remake added to the equip PARAMs:

    Goods, Ring   bpPreviewKey
    Spell         a string pointer at row offset 48 (beyond the 48-byte PARAMDEF)
    Weapon        wp_a_<equipModelId:04d>_<bpPreviewSuffix>
    Armor         <hd|bd|am|lg>_<m|f>_<equipModelId:04d>_<bpPreviewSuffix[_Female]>,
                  or _a_ (gender-neutral) for the enemy sets

Rows those rules miss fall back to the asset names listed in
``ui/_cmn/ui_3d_preview.calt`` that share the row's model prefix, when exactly
one of them names an icon. The output (``iconpack.json``) holds the icons as
small WebP images and maps ``cat:id`` keys to image indexes (armour: [male,
female]); tools/embed_icons.py puts it into the editor.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import io
import json
import os
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'src'))
from des_gamedata import (load_params, param_rows, param_string_at, param_strings,  # noqa: E402
                          param_type, parse_bnd3, parse_paramdef, placeholder_items, read_param)
from des_uiatlas import fnv1a_upper, parse_ctal, read_page  # noqa: E402

ICON_SIZE = (260, 300)            # most inventory icons; large weapons use bigger tiles
MAX_ICON_SIDE = 512
OUT_SIZE = (80, 92)               # embedded canvas (the tile's aspect)
INSET = 2
CATS = {'Goods': 'G', 'Weapon': 'W', 'Armor': 'A', 'Ring': 'R', 'Spell': 'S'}
PARAMS = {'EquipParamGoods.param': 'Goods', 'EquipParamWeapon.param': 'Weapon',
          'EquipParamProtector.param': 'Armor', 'EquipParamAccessory.param': 'Ring',
          'Magic.param': 'Spell'}
ARMOR_PREFIX = {0: 'hd', 1: 'bd', 2: 'am', 3: 'lg'}    # protectorCategory
MAGIC_KEY_OFFSET = 48
ATLAS_TABLE = 'ui/textures/_ps5/global.ctal'
ATLAS_PAGES = 'ui/textures/_ps5/_ps5/global_pages.ctxr'
PREVIEW_LIST = 'ui/_cmn/ui_3d_preview.calt'


def icon_sprites(game: Path) -> dict:
    _, sprites = parse_ctal((game / ATLAS_TABLE).read_bytes())
    # Names decide, not the standard tile size: Dragon Bone Smasher is 300 x 420
    # and the heavy and gargoyle crossbows 500 x 500. Whole-page placeholder
    # sheets (2048 x 2048, named for two unused rings) are not icons.
    return {s.hash: s for s in sprites if max(s.w, s.h) <= MAX_ICON_SIDE}


def preview_names(game: Path) -> list[str]:
    """Asset names of the per-item 3D previews (``.../<name>_ui.cgpr``)."""
    text = (game / PREVIEW_LIST).read_bytes()
    return sorted({m.decode() for m in re.findall(rb'/\*{4}/([A-Za-z0-9_]+)_ui\.cgpr', text)})


def _tables(game: Path) -> dict[str, tuple[bytes, bytes]]:
    dvd = game / 'cp11demonssouls/dvdroot'
    defs = {parse_paramdef(d)['type']: d
            for _, d in parse_bnd3((dvd / 'paramdef/paramdef.paramdefbnd').read_bytes())}
    out = {}
    for name, data in parse_bnd3((dvd / 'param/gameparam/gameparam.parambnd').read_bytes()):
        if name in PARAMS and param_type(data) in defs:
            out[PARAMS[name]] = (defs[param_type(data)], data)
    return out


def _magic_keys(data: bytes) -> dict[int, str]:
    rows = param_rows(data)
    offsets = sorted(o for _, o in rows)
    stride = min((b - a for a, b in zip(offsets, offsets[1:])), default=0)
    if stride < MAGIC_KEY_OFFSET + 8:
        raise ValueError(f'Magic.param rows are {stride} bytes; no preview key at {MAGIC_KEY_OFFSET}')
    out = {}
    for row_id, offset in rows:
        key = param_string_at(data, struct.unpack_from('<Q', data, offset + MAGIC_KEY_OFFSET)[0])
        if key:
            out[row_id] = key
    return out


def candidates(game: Path) -> dict[str, list[list[str]]]:
    """``cat:id`` -> candidate icon keys, one list per gender slot ([male, female] for armour)."""
    tables = _tables(game)
    out: dict[str, list[list[str]]] = {}
    for cat, (definition, data) in tables.items():
        if cat == 'Spell':
            for row_id, key in _magic_keys(data).items():
                out[f'S:{row_id}'] = [[key]]
            continue
        strings = param_strings(definition, data)
        values = read_param(definition, data)
        for row_id, row in values.items():
            text = strings.get(row_id, {})
            key = f'{CATS[cat]}:{row_id}'
            if cat in ('Goods', 'Ring'):
                if text.get('bpPreviewKey'):
                    out[key] = [[text['bpPreviewKey']]]
            elif cat == 'Weapon':
                model = f"wp_a_{row['equipModelId']:04d}"
                suffix = text.get('bpPreviewSuffix')
                out[key] = [[f'{model}_{suffix}' if suffix else model, model + '_']]
            elif cat == 'Armor':
                prefix = ARMOR_PREFIX.get(row.get('protectorCategory'))
                if prefix is None:
                    continue
                model = row['equipModelId']
                male, female = text.get('bpPreviewSuffix'), text.get('bpPreviewSuffix_Female')
                # _a_ names are gender-neutral (the enemy sets); they follow the
                # gendered names so a gendered icon always wins.
                neutral = [f'{prefix}_a_{model:04d}_{male}' if male else '', f'{prefix}_a_{model:04d}_']
                out[key] = [[f'{prefix}_m_{model:04d}_{male}' if male else '', f'{prefix}_m_{model:04d}_', *neutral],
                            [f'{prefix}_f_{model:04d}_{female or male}' if (female or male) else '',
                             f'{prefix}_f_{model:04d}_', *neutral]]
    return out


def match(game: Path) -> tuple[dict[str, list[int | None]], dict]:
    """``cat:id`` -> [sprite hash per gender slot] (None when unmatched), and the icon sprites."""
    icons = icon_sprites(game)
    previews = preview_names(game)
    named = lambda key: fnv1a_upper('Tex_InvIcon_' + key)  # noqa: E731
    # Empty-slot rows ("No Equipment") get no icon: their sprites are the base
    # underclothes (or blank), which would read as real gear.
    skip = {f'{CATS[cat]}:{row_id}' for cat, row_id in placeholder_items(load_params(game))}
    result = {}
    for item, slots in candidates(game).items():
        if item in skip:
            continue
        hashes = []
        for keys in slots:
            found = None
            for key in keys:
                if not key:
                    continue
                if key.endswith('_'):          # prefix: unique preview asset with an icon
                    hits = {named(n) for n in previews if n.lower().startswith(key.lower()) and named(n) in icons}
                    if len(hits) == 1:
                        found = hits.pop()
                elif named(key) in icons:
                    found = named(key)
                if found is not None:
                    break
            hashes.append(found)
        if len(hashes) == 2 and hashes[1] is None:
            hashes[1] = hashes[0]              # no female version: the male icon
        if len(hashes) == 2 and hashes[0] is None:
            hashes[0] = hashes[1]
        result[item] = hashes
    return result, icons


def fit(icon):
    """Trim the transparent margin, then centre the art in an OUT_SIZE canvas.

    The game draws its icons small inside a 260 x 300 tile; trimmed, they stay
    readable at the editor's row size.
    """
    from PIL import Image

    box = icon.getchannel('A').point(lambda a: 255 if a > 12 else 0).getbbox()
    if box:
        pad = 4
        icon = icon.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                          min(box[2] + pad, icon.width), min(box[3] + pad, icon.height)))
    scale = min(OUT_SIZE[0] / icon.width, OUT_SIZE[1] / icon.height)
    icon = icon.resize((max(1, round(icon.width * scale)), max(1, round(icon.height * scale))), Image.LANCZOS)
    canvas = Image.new('RGBA', OUT_SIZE, (0, 0, 0, 0))
    canvas.alpha_composite(icon, ((OUT_SIZE[0] - icon.width) // 2, (OUT_SIZE[1] - icon.height) // 2))
    return canvas


def build(game: Path, quality: int = 80) -> dict:
    from PIL import Image

    mapping, icons = match(game)
    used = sorted({h for hashes in mapping.values() for h in hashes if h is not None},
                  key=lambda h: (icons[h].page, icons[h].y, icons[h].x))
    images, index = [], {}
    for page in sorted({icons[h].page for h in used}):
        pixels = read_page(game / ATLAS_PAGES, page)
        for h in (h for h in used if icons[h].page == page):
            s = icons[h]
            # A small inset drops bleed from neighbouring sprites at the edges.
            crop = Image.fromarray(pixels[s.y + INSET:s.y + s.h - INSET, s.x + INSET:s.x + s.w - INSET], 'RGBA')
            crop = fit(crop)
            buf = io.BytesIO()
            crop.save(buf, 'WEBP', quality=quality, method=6)
            index[h] = len(images)
            images.append(base64.b64encode(buf.getvalue()).decode('ascii'))
    items = {}
    for item, hashes in sorted(mapping.items(), key=lambda kv: (kv[0][0], int(kv[0][2:]))):
        idx = [index.get(h) for h in hashes]
        if all(i is None for i in idx):
            continue
        items[item] = idx[0] if len(idx) == 1 else (idx[0] if idx[0] == idx[1] else idx)
    return {'schema': 1, 'size': list(OUT_SIZE), 'format': 'webp',
            'note': ('Inventory icons extracted from the game UI atlas by tools/build_icons.py. '
                     "Demon's Souls (2020) art, (c) Sony Interactive Entertainment; for "
                     'identification only.'),
            'images': images, 'items': items}


def coverage(mapping: dict) -> Counter:
    stats = Counter()
    for item, hashes in mapping.items():
        stats[(item[0], hashes[0] is not None)] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--game', default=os.environ.get('DES_GAME_DIR'), help='game dump (DES_GAME_DIR)')
    parser.add_argument('--out', default=str(HERE / 'iconpack.json'))
    parser.add_argument('--report', action='store_true', help='list unmatched rows and stop')
    args = parser.parse_args(argv)
    if not args.game:
        parser.error('--game or DES_GAME_DIR is required')
    game = Path(args.game)
    mapping, icons = match(game)
    stats = coverage(mapping)
    for cat in 'GWARS':
        hit, miss = stats[(cat, True)], stats[(cat, False)]
        print(f'{cat}: {hit}/{hit + miss} rows have an icon')
    used = {h for hashes in mapping.values() for h in hashes if h is not None}
    standard = {h for h, s in icons.items() if (s.w, s.h) == ICON_SIZE}
    print(f'{len(used)} sprites used ({len(used & standard)} of the {len(standard)} standard {ICON_SIZE[0]}x{ICON_SIZE[1]} tiles)')
    missing = sorted((k for k, v in mapping.items() if v[0] is None), key=lambda k: (k[0], int(k[2:])))
    if args.report:
        print('unmatched:', ' '.join(missing))
        return 0
    pack = build(game)
    Path(args.out).write_text(json.dumps(pack, separators=(',', ':')) + '\n')
    print(f"wrote {args.out}: {len(pack['images'])} images, {len(pack['items'])} items")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
