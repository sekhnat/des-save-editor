#!/usr/bin/env python3
"""Harvest candidate field names from the game files and match them to save keys.

Every save key is FNV-1a 32 of an uppercase name, so any string the game ships
is a candidate. This tool collects printable strings from the executable, the
prefab files, the misc/ tree and the param definitions, expands the
executable's printf-style templates (``CCSlot_Gender_%02d`` → ``_00`` … ``_99``),
and reports every candidate whose hash equals a key seen in the given saves.

A hash match is a *candidate*, not a verified name: 32-bit hashes collide.
The review table shows the observed record types so a human can check that
the name fits before adding it to des_fields.py. Nothing is accepted
automatically.

    python3 tools/build_keydb.py GAME --save USR-DATA [--save ...] [-o keydb.json]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import des_fields  # noqa: E402
import des_save  # noqa: E402
import des_world  # noqa: E402

# (relative path, file glob); paths that do not exist are skipped
SOURCES = [
    ('eboot.bin', None),
    ('scripts', '*.cgpr'),
    ('ui/scripts', '*.cgpr'),
    ('misc', '*'),
    ('coredata', '*.txt'),
    ('cp11demonssouls/dvdroot/paramdef', '*'),
    ('cp11demonssouls/dvdroot/script', '*'),
]
MAX_FILE = 64 << 20
STRING = re.compile(rb'[A-Za-z_][A-Za-z0-9_.:/ -]{2,80}')
SPLIT = re.compile(r'[ /:.\-]+')
TEMPLATE = re.compile(rb'[A-Za-z_][A-Za-z0-9_]{1,60}%(?:0?[1-4])?[diu][A-Za-z0-9_]{0,40}')
LOADOUT_VERB = re.compile(r'^cp11_(?:set|add|equip|learn|remember|num)?', re.I)


def _files(game: Path):
    for rel, pattern in SOURCES:
        path = game / rel
        if path.is_file():
            yield path
        elif path.is_dir():
            for item in sorted(path.rglob(pattern)):
                if item.is_file() and item.stat().st_size <= MAX_FILE:
                    yield item


def _expand(template: str) -> list[str]:
    match = re.search(r'%(0?[1-4])?[diu]', template)
    width = int(match.group(1) or 0) if match else 0
    head, tail = template[:match.start()], template[match.end():]
    return [f'{head}{index:0{width}d}{tail}' for index in range(100)]


def harvest(game: Path) -> dict[str, set[str]]:
    """Uppercase candidate name -> the source files it came from."""
    found: dict[str, set[str]] = collections.defaultdict(set)
    for path in _files(game):
        data = path.read_bytes()
        source = str(path.relative_to(game))
        for match in STRING.finditer(data):
            text = match.group().decode('ascii')
            names = {text, *SPLIT.split(text)}
            if text.lower().startswith('cp11_'):
                names.add(LOADOUT_VERB.sub('', text))
            for name in names:
                if len(name) >= 3:
                    found[name.upper()].add(source)
        if path.name == 'eboot.bin':
            for match in TEMPLATE.finditer(data):
                for name in _expand(match.group().decode('ascii')):
                    found[name.upper()].add(source + ' (template)')
    return found


def save_keys(paths: list[str]) -> dict[int, dict]:
    """key -> {'types': set, 'where': set, 'sample': value} over all given saves."""
    keys: dict[int, dict] = {}

    def note(record, where):
        info = keys.setdefault(record.key, {'types': set(), 'where': set(), 'sample': None})
        info['types'].add(record.type)
        info['where'].add(where)
        if info['sample'] is None and not record.is_container:
            value = record.value
            info['sample'] = value.hex()[:16] if isinstance(value, (bytes, bytearray)) else value

    for path in paths:
        sf = des_save.load(path)
        for record, _ in sf.walk():
            note(record, 'top')
        for _, groups in des_world.world_blobs(sf):
            for _, _, entry in des_world.entries(groups):
                for record in des_world._walk(entry.records or []):
                    note(record, 'world')
    return keys


def match(vocabulary: dict[str, set[str]], keys: dict[int, dict]) -> list[dict]:
    hits: dict[int, list[str]] = collections.defaultdict(list)
    for name in vocabulary:
        key = des_save.fnv1a(name.encode('ascii'))
        if key in keys:
            hits[key].append(name)
    rows = []
    for key, names in hits.items():
        info = keys[key]
        rows.append({'key': f'{key:08x}', 'names': sorted(names),
                     'types': sorted(f'0x{t:02x}' for t in info['types']),
                     'where': sorted(info['where']), 'sample': info['sample'],
                     'known': des_fields.field_name(key) or des_fields.world_name(key),
                     'sources': sorted({s for n in names for s in vocabulary[n]})[:6]})
    return sorted(rows, key=lambda row: (row['where'], row['names']))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game', type=Path, help='PPSA01342-app folder')
    parser.add_argument('--save', action='append', default=[], required=True,
                        help='USR-DATA whose keys are matched (repeatable)')
    parser.add_argument('-o', '--out', help='write the candidate list as JSON')
    args = parser.parse_args(argv)
    if not args.game.is_dir():
        print(f'not a folder: {args.game}', file=sys.stderr)
        return 2
    keys = save_keys(args.save)
    vocabulary = harvest(args.game)
    rows = match(vocabulary, keys)
    unknown = sum(1 for key in keys if not (des_fields.field_name(key) or des_fields.world_name(key)))
    print(f'{len(vocabulary)} candidate strings, {len(keys)} distinct keys '
          f'({unknown} unnamed), {len(rows)} hash matches', file=sys.stderr)
    for row in rows:
        status = 'known' if row['known'] else 'NEW'
        print(f"  {row['key']}  {status:<5} {'/'.join(row['where']):<9} "
              f"{','.join(row['types']):<9} {str(row['sample'])[:12]:<12} {' | '.join(row['names'])}")
    if args.out:
        Path(args.out).write_text(json.dumps({'schema': 1, 'candidates': rows}, indent=2) + '\n',
                                  encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
