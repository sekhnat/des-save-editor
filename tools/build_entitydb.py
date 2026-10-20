#!/usr/bin/env python3
"""Build the entity index: world-state GUID -> the game file that defines it.

World-state entries (see des_world.py) are keyed by 16-byte entity GUIDs from
the game's prefab files. This tool finds GUIDs in ``scripts/**/*.cgpr`` by two
observed layouts and in the shipped baseline saves:

1. index tables: runs of ``u32 n, GUID`` with n counting up by one;
2. references: ``GUID, 8 bytes, 0x01, u32, FF FF FF FF, 00``;
3. ``misc/cachedsavedata/<section>.txt`` entries, mapped to that section.

Only RFC 4122 version-4/5 GUIDs (variant 10) are taken from the prefabs. The
first source to name a GUID wins. Level labels ("Boletaria 1-2") come from the
majority label per world folder in ``misc/dspointsofinterest.txt``.

Output (gzip, reproducible): magic ``DESE``, u32 version, u32 count,
u32 text length, UTF-8 text (paths, then a blank line, then
``world-folder<TAB>label`` lines), six byte-planes of the sorted 6-byte GUID
prefixes, and a u16 path-index column (0xFFFF marks an ambiguous prefix).
Storing the sorted prefixes as byte-planes lets gzip compress the leading
bytes, which repeat.

    python3 tools/build_entitydb.py GAME [-o entitydb.bin] [--max-mb 6]
"""
from __future__ import annotations

import argparse
import collections
import gzip
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import des_world  # noqa: E402

PREFIX = 6
AMBIGUOUS = 0xFFFF
_GUID = rb'.{7}[\x40-\x5f][\x80-\xbf].{7}'
TABLE = re.compile(rb'(?=..\x00\x00' + _GUID + rb'..\x00\x00' + _GUID + rb'..\x00\x00' + _GUID + rb')', re.S)
REFERENCE = re.compile(rb'(?=(.{16}).{8}\x01.{4}\xff\xff\xff\xff\x00)', re.S)
POI = re.compile(r'name="([^"]+)".*?scripts/worlds/(m\d\d_\d\d)_')


def _is_guid(guid: bytes) -> bool:
    return guid[7] >> 4 in (4, 5) and guid[8] >> 6 == 2


def scan_prefab(data: bytes) -> list[bytes]:
    """GUIDs in one prefab file, tables first, in file order."""
    found = []
    for match in TABLE.finditer(data):
        at = match.start()
        a, b, c = (struct.unpack_from('<I', data, at + step)[0] for step in (0, 20, 40))
        if b == a + 1 and c == b + 1:
            found += [data[at + offset:at + offset + 16] for offset in (4, 24, 44)]
    found += [m.group(1) for m in REFERENCE.finditer(data) if _is_guid(m.group(1))]
    return found


def level_labels(poi_file: Path) -> dict[str, str]:
    """World folder (m02_01) -> label (Boletaria 1-2), by majority vote."""
    numbers: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    areas: dict[str, set] = collections.defaultdict(set)
    totals: collections.Counter = collections.Counter()
    if not poi_file.exists():
        return {}
    for line in poi_file.read_text(encoding='utf-8', errors='replace').splitlines():
        match = POI.search(line)
        if not match:
            continue
        name, world = match.groups()
        areas[world[:3]].add(name.split()[0])
        totals[world] += 1
        number = re.search(r'\b[T\d]-\d\b', name)
        if number:
            numbers[world][number.group()] += 1
        else:
            numbers[world]  # registers the folder with no number (the Nexus)
    labels = {}
    for world, counts in numbers.items():
        area = max(areas[world[:3]], key=len)
        area = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', area).replace(' Of ', ' of ')
        number, votes = counts.most_common(1)[0] if counts else ('', 0)
        if votes * 2 < totals[world]:                 # a stray number, not the level's
            number = ''
        labels[world] = f'{area} {number}'.strip()
    return labels


def build(game: Path) -> tuple[bytes, dict]:
    scripts = game / 'scripts'
    owner: dict[bytes, str] = {}
    sources = collections.Counter()
    for path in sorted(scripts.rglob('*.cgpr')):
        relative = path.relative_to(scripts).with_suffix('').as_posix()
        for guid in scan_prefab(path.read_bytes()):
            if guid not in owner:
                owner[guid] = relative
                sources['prefab'] += 1
    for path in sorted((game / 'misc/cachedsavedata').glob('*.txt')):
        groups = des_world.decode(path.read_bytes())
        for _, _, entry in des_world.entries(groups or []):
            if entry.guid not in owner:
                owner[entry.guid] = f'cachedsavedata/{path.stem}'
                sources['baseline'] += 1
    if not owner:
        raise ValueError('no entity GUIDs found; is this the PPSA01342-app folder?')

    paths = sorted(set(owner.values()))
    index = {path: i for i, path in enumerate(paths)}
    by_prefix: dict[bytes, int] = {}
    for guid, path in owner.items():
        key = guid[:PREFIX]
        previous = by_prefix.get(key)
        by_prefix[key] = index[path] if previous in (None, index[path]) else AMBIGUOUS
    prefixes = sorted(by_prefix)
    labels = level_labels(game / 'misc/dspointsofinterest.txt')
    text = ('\n'.join(paths) + '\n\n' + '\n'.join(f'{k}\t{v}' for k, v in sorted(labels.items()))).encode()
    planes = b''.join(bytes(prefix[plane] for prefix in prefixes) for plane in range(PREFIX))
    column = struct.pack(f'<{len(prefixes)}H', *(by_prefix[p] for p in prefixes))
    raw = (b'DESE' + struct.pack('<III', 1, len(prefixes), len(text)) + text + planes + column)
    stats = {'guids': len(owner), 'prefixes': len(prefixes), 'paths': len(paths),
             'ambiguous': sum(1 for p in prefixes if by_prefix[p] == AMBIGUOUS),
             'levels': len(labels), **sources}
    return gzip.compress(raw, compresslevel=9, mtime=0), stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game', type=Path, help='PPSA01342-app folder')
    parser.add_argument('-o', '--out', type=Path, default=HERE / 'entitydb.bin')
    parser.add_argument('--max-mb', type=float, default=6.0,
                        help='refuse to write an index larger than this (default 6)')
    args = parser.parse_args(argv)
    try:
        blob, stats = build(args.game)
    except (OSError, ValueError) as error:
        print(f'entity index build failed: {error}', file=sys.stderr)
        return 2
    size = len(blob) / (1 << 20)
    print(f"{stats['guids']} GUIDs ({stats.get('prefab', 0)} from prefabs, "
          f"{stats.get('baseline', 0)} from baselines) in {stats['paths']} files, "
          f"{stats['ambiguous']} ambiguous prefixes, {stats['levels']} level labels, "
          f"{size:.2f} MiB", file=sys.stderr)
    if size > args.max_mb:
        print(f'index exceeds {args.max_mb} MiB; not written', file=sys.stderr)
        return 1
    args.out.write_bytes(blob)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
