#!/usr/bin/env python3
"""Parse the developer loadout scripts in misc/loadouts and check them against the catalog.

Loadouts are automation scripts the developers used to build test characters:

    *stage "Inventory"
        cp11_addWeapon   id = 20200   quantity = 1   durability = 200   // Longsword
        cp11_numSpellSlotsUnlocked   1
    *endstage

They are ground truth for what a character *contains* (IDs, quantities,
durability, equipment slots, stats), not for how a save encodes it. The packaged
game does not appear to apply them (no log line shows "Applying player
loadout"), so they cannot be used to create test saves.

The parser is strict: anything it does not recognise is reported with its file
and line. Checks:

* every added or learned ID exists in the catalog under the matching category;
* premade files named ``..._slNNN...`` have base stats summing to NNN + 80,
  the soul-level formula the editor uses.

    python3 tools/parse_loadouts.py GAME [--json]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re
import shlex
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'src'))
import des_items  # noqa: E402

DIRECTIVES = {'waitForLevelLoading', '*go', '*endstage'}
# loadout command -> catalog category of its id argument
ID_CATEGORY = {'cp11_addWeapon': 'Weapon', 'cp11_equipWeapon': 'Weapon',
               'cp11_addArmor': 'Armor', 'cp11_equipArmor': 'Armor',
               'cp11_addGoods': 'Goods', 'cp11_equipGoods': 'Goods',
               'cp11_addAccessory': 'Ring', 'cp11_equipAccessory': 'Ring',
               'cp11_learnMagic': 'Spell', 'cp11_rememberMagic': 'Spell'}
STATS = ('vitality', 'intelligence', 'endurance', 'strength', 'dexterity', 'magic', 'faith', 'luck')
LEVEL = re.compile(r'_sl(\d+)')


def _value(text: str):
    try:
        return int(text, 0)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse(text: str, source: str = '<loadout>', errors: list | None = None) -> list[dict]:
    """Statements of one loadout file.

    A line that cannot be parsed raises ValueError naming it, unless an
    ``errors`` list is given: then the problem is recorded there, the line is
    skipped and parsing continues.
    """
    out, stage = [], None
    for number, line in enumerate(text.splitlines(), 1):
        code, _, comment = line.partition('//')
        code = code.strip()
        if not code:
            continue
        # 42 files join "*go" and the next directive on one line
        parts = ['*go', code[3:]] if code.startswith('*go') and code != '*go' else [code]
        for part in parts:
            where = f'{source}:{number}'
            try:
                tokens = shlex.split(part)
            except ValueError as error:
                if errors is None:
                    raise ValueError(f'{where}: {error}') from error
                errors.append(f'{where}: {error}: {part!r}')
                continue
            head, rest = tokens[0], tokens[1:]
            if head in DIRECTIVES and not rest:
                if head == '*endstage':
                    stage = None
                continue
            if head == '*stage' and len(rest) == 1:
                stage = rest[0]
                continue
            if head == 'print' and len(rest) == 1:
                continue
            if head == 'wait' and len(rest) == 1:
                continue
            if not head.startswith('cp11_'):
                if errors is None:
                    raise ValueError(f'{where}: unrecognised statement {head!r}')
                errors.append(f'{where}: unrecognised statement {head!r}')
                continue
            args, positional, i = {}, [], 0
            while i < len(rest):
                if i + 1 < len(rest) and rest[i + 1] == '=':
                    if i + 2 >= len(rest):
                        raise ValueError(f'{where}: {rest[i]} has no value')
                    args[rest[i]] = _value(rest[i + 2])
                    i += 3
                else:
                    positional.append(_value(rest[i]))
                    i += 1
            out.append({'source': where, 'stage': stage, 'command': head, 'args': args,
                        'positional': positional, 'comment': comment.strip() or None})
    return out


def load(game: Path, errors: list | None = None) -> dict[str, list[dict]]:
    root = Path(game) / 'misc/loadouts'
    return {path.relative_to(root).as_posix(): parse(path.read_text(encoding='utf-8', errors='strict'),
                                                     path.relative_to(root).as_posix(), errors)
            for path in sorted(root.rglob('*.txt'))}


def check(loadouts: dict[str, list[dict]], catalog: list[dict], errors: list | None = None) -> dict:
    known = {(entry['category'], entry['id']) for entry in catalog}
    missing = collections.Counter()
    ids = 0
    for statements in loadouts.values():
        for statement in statements:
            category = ID_CATEGORY.get(statement['command'])
            item = statement['args'].get('id')
            if category and isinstance(item, int) and item >= 0:
                ids += 1
                if (category, item) not in known:
                    missing[(category, item, statement['comment'])] += 1
    levels = []
    for name, statements in loadouts.items():
        match = LEVEL.search(name)
        base = {}
        for statement in statements:
            if statement['command'] == 'cp11_setBaseStats':
                base.update({k: v for k, v in statement['args'].items() if k in STATS})
        if match and len(base) == len(STATS):
            levels.append({'file': name, 'named': int(match.group(1)),
                           'computed': sum(base[k] for k in STATS) - 80})
    return {'files': len(loadouts), 'unparsed_lines': list(errors or []),
            'statements': sum(len(s) for s in loadouts.values()),
            'ids_checked': ids,
            'missing_ids': [{'category': c, 'id': i, 'comment': n, 'uses': k}
                            for (c, i, n), k in sorted(missing.items(), key=lambda kv: kv[0][:2])],
            'soul_levels': levels,
            'soul_level_mismatches': [row for row in levels if row['named'] != row['computed']]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game', type=Path, help='PPSA01342-app folder')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    errors: list[str] = []
    try:
        loadouts = load(args.game, errors)
    except (OSError, UnicodeDecodeError) as error:
        print(f'loadout parse failed: {error}', file=sys.stderr)
        return 2
    report = check(loadouts, des_items.load_catalog(), errors)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"{report['files']} loadouts, {report['statements']} statements, "
          f"{report['ids_checked']} item/spell ids checked against the catalog")
    print(f"  lines that could not be parsed: {len(report['unparsed_lines'])}")
    for line in report['unparsed_lines'][:10]:
        print(f"    {line}")
    print(f"  ids missing from the catalog: {len(report['missing_ids'])}")
    for row in report['missing_ids'][:20]:
        print(f"    {row['category']:<6} {row['id']:>7}  x{row['uses']:<3} {row['comment'] or ''}")
    print(f"  soul level from file name vs base stats: {len(report['soul_levels'])} files, "
          f"{len(report['soul_level_mismatches'])} mismatches")
    for row in report['soul_level_mismatches'][:20]:
        print(f"    {row['file']}: named SL {row['named']}, stats give {row['computed']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
