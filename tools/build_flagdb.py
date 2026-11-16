#!/usr/bin/env python3
"""Build the event-flag database: flag ID -> meaning, from the game's own scripts.

The event system (see docs/research-event-flags.md) numbers its flags, and the
scripts themselves say what most of them mean:

* ``event_define.lua`` lists every NPC's quest-state flags with comments, and
  defines ``NPC_STATE_BACKUP_OFFSET`` (state flags have a +1000 backup twin).
* ``global_event.lua``'s ``GetBossFlagCount`` holds the authoritative table of
  boss-death flags, grouped by world with comments (King's Castle, Jail, ...).
* every map script documents its own events as ``--■ 123 ■ description``
  (machine-translated), next to the ``SetEventFlag``/``IsCompleteEvent`` calls
  that read and write them.
* ``IsSuccessQWC`` (tendency) call sites sit next to the event flags they gate
  (Miralda's removal, the execution-ground door, ...); those pairs are what the
  Tendency view needs to finish the tendency feature.

Output ``flagdb.json``: ``areas`` (area id -> name/map), ``npcs`` (state
machines), ``bosses`` (death flags with names), ``events`` (per-map flag
descriptions) and ``tendency_pairs`` (judge -> flags). The CLI and the page use
it read-only; nothing here edits game files.

    python3 tools/build_flagdb.py GAME [-o flagdb.json] [--check]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
#  Areas: the scripts address flags per world ("SetAreaEventFlag(02, ...)"),
#  numbered exactly like the maps (01 Nexus .. 06 Stonefang, 07 the northern
#  limit, 08 the tutorial). Confirmed by the area ids in SeekForgiveness's
#  other_reset_flags tables and by m07/m08 script ranges.
AREAS = {
    1: ("Nexus", "m01"),
    2: ("Boletarian Palace", "m02"),
    3: ("Shrine of Storms", "m03"),
    4: ("Tower of Latria", "m04"),
    5: ("Valley of Defilement", "m05"),
    6: ("Stonefang Tunnel", "m06"),
    7: ("Northern Limit (the old one)", "m07"),
    8: ("Tutorial", "m08"),
}

# Boss-death flags, verbatim from GetBossFlagCount's tables, with the boss
# names the groups describe (block_boss = per-world "soul acquired" count).
# Boss-death flags, verbatim from GetBossFlagCount's tables, with the boss
# names the groups describe (block_boss = per-world "soul acquired" count).
# The soul flag is the one-shot pickup event that hands over the demon soul
# (the map scripts' "Get Soul" handlers: OnEvent_4103_1 -> GetRateItem(10110)
# in 1-1, SetEventFlag(5121, 1) in 3-1, ...). Clearing death + soul lets the
# boss be fought again and its soul re-collected.
# (flag, area, boss name, world comment, soul flag)
BOSSES = [
    (4096, 2, "Phalanx", "King's Castle", 4103),
    (4224, 2, "Tower Knight", "King's Castle", 4252),
    (4360, 2, "Penetrator", "King's Castle", 4372),
    (4480, 2, "False King Allant", "King's Castle", 4503),
    (5123, 4, "Fool's Idol", "Jail", 5121),
    (5251, 4, "Maneater", "Jail", 5261),
    (5380, 4, "Old Monk", "Jail", 5381),
    (5650, 5, "Leechmonger", "Uncleanness", 5653),
    (5770, 5, "Dirty Colossus", "Uncleanness", 5773),
    (5888, 5, "Maiden Astrea", "Uncleanness", 5893),
    (4756, 3, "Adjudicator", "Old fort", 4804),
    (4895, 3, "Old Hero", "Old fort", 4874),
    (4992, 3, "Storm King", "Old fort", 4996),
    (6174, 6, "Armor Spider", "Gallery", 6193),
    (6272, 6, "Flamelurker", "Gallery", 6283),
    (6400, 6, "Dragon God", "Gallery", 6403),
]
# Boss flags whose number the table gives but no script ever writes are a
# bug in this table; every entry must appear in some script.
CONST_LINE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\d+)\s*;?'
                        r'\s*(?:--\s*(.*))?$', re.M)
FLAG_LIST = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)flag_list\s*=\s*\{(.*?)\}',
                      re.S)
LIST_MEMBER = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)')
BOSS_TABLE = re.compile(r'boss_actionId_list\s*=\s*\{(.*?)\}', re.S)
NUMBER = re.compile(r'\b(\d{1,7})\b')
# --■ 4096 ■ Opening the door ... ■ (the scripts' per-event documentation)
COMMENT = re.compile(r'--■\s*(\d+)\s*■\s*([^■\n]*)')
FLAG_USE = re.compile(r'(SetEventFlag|IsCompleteEvent|IsCompleteEventValue|'
                      r'SetAreaEventFlag|SetEventCount|GetEventCount|'
                      r'SingleReset)\s*\(\s*([A-Za-z0-9_]+)')
QWC_USE = re.compile(r'IsSuccessQWC\s*\(\s*(\d+)')


def _read(path: Path) -> str:
    return path.read_bytes().decode('cp932', 'replace')


def strip_comment(text: str) -> str:
    """One clean line for a machine-translated comment."""
    text = (text or '').replace('--', '').strip()
    text = re.sub(r'\s+', ' ', text)
    # prefer the machine-translated English; keep Japanese-only text as-is
    if text and sum(ord(c) > 0x2FFF for c in text) > len(text) / 2:
        return ''
    return text.strip(' ();\t')


def parse_event_define(text: str) -> dict:
    """NPC state constants and state lists from event_define.lua."""
    consts = {}
    for m in CONST_LINE.finditer(text):
        consts[m.group(1)] = (int(m.group(2)), strip_comment(m.group(3)))
    lists = []
    for m in FLAG_LIST.finditer(text):
        members = [(name, consts[name][0], consts[name][1])
                   for name in LIST_MEMBER.findall(m.group(2))
                   if name in consts]
        lists.append({"list": m.group(1) + "flag_list", "states": members})
    backup = int(re.search(r'NPC_STATE_BACKUP_OFFSET\s*=\s*(\d+)', text).group(1))
    return {"consts": consts, "lists": lists, "backup_offset": backup}


def parse_boss_table(text: str) -> list[int]:
    m = BOSS_TABLE.search(text)
    return [int(n) for n in NUMBER.findall(m.group(1))]


def parse_map(path: Path) -> dict:
    """Per-map event documentation: flag -> descriptions and call sites."""
    text = _read(path)
    descs = collections.defaultdict(list)
    for m in COMMENT.finditer(text):
        descs[int(m.group(1))].append(strip_comment(m.group(2)))
    uses = collections.defaultdict(list)
    for m in FLAG_USE.finditer(text):
        name = m.group(1) if m.group(1) != 'SingleReset' else 'SingleReset'
        uses[m.group(2)].append(name)
    # tendency judges mentioned near a flag use (within the same ~8 lines)
    lines = text.splitlines()
    pairs = []
    for i, line in enumerate(lines):
        for m in QWC_USE.finditer(line):
            window = '\n'.join(lines[max(0, i - 8):i + 9])
            flags = {int(x) for x in re.findall(r'SingleReset\w*\(\s*proxy\s*,\s*(\d+)', window)}
            flags |= {int(x) for x in re.findall(r'SetEventFlag\s*\(\s*(\d+)', window)}
            for flag in sorted(flags):
                pairs.append({"judge": int(m.group(1)), "flag": flag,
                              "file": path.name, "line": i + 1})
    return {"descs": {k: v for k, v in descs.items()},
            "uses": {k: v for k, v in uses.items()},
            "qwc_pairs": pairs}


def build(game: Path) -> dict:
    script_dir = game / 'cp11demonssouls' / 'dvdroot' / 'script'
    define = parse_event_define(_read(script_dir / 'event_define.lua'))
    global_text = _read(script_dir / 'global_event.lua')
    table_flags = parse_boss_table(global_text)

    # ---- sanity: the hardcoded boss table must match the game's own ----------
    assert sorted(table_flags) == sorted(f for f, *_ in BOSSES), \
        f"boss table mismatch: game={sorted(table_flags)}"

    maps = {}
    for path in sorted(script_dir.glob('*.lua')):
        if 'testroom' in path.name or 'eventboss' in path.name \
                or path.name == 'event_define.lua':
            continue
        maps[path.name] = parse_map(path)
    # per-map area assignment from the map id (m02_* -> area 02)
    def area_of(file_name: str) -> int | None:
        m = re.match(r'm(\d\d)_', file_name)
        return int(m.group(1)) if m else None

    # ---- flag events: every documented flag with its per-area meanings ------
    events = {}
    for file_name, data in maps.items():
        area = area_of(file_name)
        for flag, descs in data['descs'].items():
            entry = events.setdefault(flag, {"id": flag, "areas": {}})
            entry['areas'].setdefault(str(area if area is not None else 0), [])
            seen = entry['areas'][str(area if area is not None else 0)]
            for d in descs:
                if d and d not in seen:
                    seen.append(d)
        for arg, funcs in data['uses'].items():
            if not arg.isdigit():
                continue
            entry = events.setdefault(int(arg), {"id": int(arg), "areas": {}})
            entry.setdefault('uses', []).extend(
                f"{file_name}:{fn}" for fn in sorted(set(funcs)))

    # ---- NPC state machines --------------------------------------------------
    npcs = []
    for lst in define['lists']:
        npcs.append({
            "list": lst['list'],
            "states": [{"name": n, "id": fid, "desc": desc}
                       for n, fid, desc in lst['states']],
        })
    state_ids = {fid for lst in define['lists'] for _, fid, _ in lst['states']}

    # ---- tendency pairs (dedup) ---------------------------------------------
    pairs, seen_pairs = [], set()
    for file_name, data in maps.items():
        for pair in data['qwc_pairs']:
            key = (pair['judge'], pair['flag'])
            if key not in seen_pairs:
                seen_pairs.add(key)
                pairs.append(pair)

    return {
        "areas": {str(k): {"name": v[0], "map": v[1]} for k, v in AREAS.items()},
        "backup_offset": define['backup_offset'],
        "bosses": [{"id": fid, "area": area, "name": name, "world": world,
                    "soul": soul}
                   for fid, area, name, world, soul in BOSSES],
        "npcs": npcs,
        "npc_state_ids": sorted(state_ids),
        "events": [events[k] for k in sorted(events)],
        "tendency_pairs": sorted(pairs, key=lambda p: (p['judge'], p['flag'])),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game', type=Path, help='PPSA01341-app0 game folder')
    ap.add_argument('-o', '--out', type=Path, default=HERE / 'flagdb.json')
    ap.add_argument('--check', action='store_true',
                    help='verify the committed flagdb.json matches a rebuild')
    args = ap.parse_args(argv)

    db = build(args.game)
    text = json.dumps(db, indent=1, ensure_ascii=False, sort_keys=False) + '\n'

    if args.check:
        current = args.out.read_text(encoding='utf-8') if args.out.exists() else ''
        if current == text:
            print(f"{args.out} matches the game files "
                  f"({len(db['events'])} flags, {len(db['npcs'])} NPCs, "
                  f"{len(db['bosses'])} bosses)")
            return 0
        print(f"{args.out} is stale; rebuild with "
              f"python3 tools/build_flagdb.py {args.game}", file=sys.stderr)
        return 1

    args.out.write_text(text, encoding='utf-8')
    print(f"{args.out}: {len(db['events'])} documented flags, "
          f"{len(db['npcs'])} NPC state machines, "
          f"{len(db['bosses'])} boss flags, "
          f"{len(db['tendency_pairs'])} tendency pairings")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
