#!/usr/bin/env python3
"""Read the tendency (QWC) tables from the game files and check des_tendency.py.

    python3 tools/build_tendencydb.py GAME            print judges and script call sites
    python3 tools/build_tendencydb.py GAME --check    fail if des_tendency.py disagrees

GAME is the PPSA01341-app0 folder. Judge ranges come from QwcJudge.param in
gameparam.parambnd (decoded through its PARAMDEF by des_gamedata); call sites
are the uncommented ``IsSuccessQWC(<id>)`` calls in the Lua scripts of
cp11demonssouls/dvdroot/script (plain text, CP932). The check requires every
catalog judge to match the PARAM row, every catalog source to be a live call
of that judge, and every live call to be in the catalog.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'src'))
import des_gamedata  # noqa: E402
import des_tendency  # noqa: E402

FIELDS = ('pcJudgeUnderWB', 'pcJudgeTopWB', 'pcJudgeUnderLR', 'pcJudgeTopLR',
          'areaJudgeUnderWB', 'areaJudgeTopWB', 'areaJudgeUnderLR', 'areaJudgeTopLR')
CALL = re.compile(r'IsSuccessQWC\s*\(\s*(\d+)\s*\)')


def judges(game: Path) -> dict[int, tuple]:
    table = des_gamedata.load_params(game).get('QWC_JUDGE_PARAM_ST')
    if table is None:
        raise SystemExit('QwcJudge.param not found or not decodable')
    return {row: tuple(values[f] for f in FIELDS) for row, values in table.items()}


def live_calls(game: Path) -> list[tuple[str, int, int]]:
    """(file, line, judge) for calls outside Lua comments."""
    out = []
    for path in sorted((game / 'cp11demonssouls/dvdroot/script').glob('*.lua')):
        text = path.read_bytes().decode('cp932', 'replace')
        in_block = False
        for number, line in enumerate(text.splitlines(), 1):
            code, rest = '', line
            while rest:
                if in_block:
                    end = rest.find(']]')
                    if end < 0:
                        rest = ''
                        break
                    in_block, rest = False, rest[end + 2:]
                    continue
                start = rest.find('--')
                if start < 0:
                    code += rest
                    break
                code += rest[:start]
                if rest.startswith('--[[', start):
                    in_block, rest = True, rest[start + 4:]
                else:
                    break                          # line comment
            out.extend((path.name, number, int(m.group(1))) for m in CALL.finditer(code))
    return out


def check(game: Path) -> list[str]:
    errors = []
    params = judges(game)
    for judge, row in des_tendency.JUDGES.items():
        if params.get(judge) != tuple(float(v) for v in row):
            errors.append(f'judge {judge}: catalog {row}, game {params.get(judge)}')
    calls = live_calls(game)
    by_site = {(f, n): j for f, n, j in calls}
    covered = set()
    for event in des_tendency.EVENTS:
        own = {event['judge'], *event.get('also', [])}
        for judge in own:
            if judge not in des_tendency.JUDGES:
                errors.append(f'event {event["judge"]}: judge {judge} has no range in JUDGES')
        for source in event['sources']:
            name, _, line = source.rpartition(':')
            judge = by_site.get((name, int(line)))
            if judge not in own:
                errors.append(f'event {event["judge"]}: {source} is not a live call of {sorted(own)} '
                              f'(found {judge})')
            covered.add((name, int(line)))
    for name, line, judge in calls:
        if (name, line) not in covered:
            errors.append(f'{name}:{line} calls IsSuccessQWC({judge}), not in the catalog')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        errors = check(args.game)
        for error in errors:
            print(error, file=sys.stderr)
        print('des_tendency.py matches the game files' if not errors else f'{len(errors)} mismatch(es)')
        return 1 if errors else 0
    params = judges(args.game)
    print('# QwcJudge rows: pc WB, pc LR, area WB, area LR (under, top)')
    for judge, row in sorted(params.items()):
        print(f'    {judge}: ({", ".join(f"{v:g}" for v in row)}),')
    print('\n# live IsSuccessQWC call sites')
    for name, line, judge in live_calls(args.game):
        print(f'{judge:6} {name}:{line}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
