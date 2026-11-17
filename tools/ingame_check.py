#!/usr/bin/env python3
"""Check save edits in the real game: Demon's Souls on the Kyty emulator, inside Xvfb.

Opt-in. Needs KYTY_DIR (the KytyPS5 checkout, with its tools/local scripts and
_SaveData) and Xvfb, xdotool, ImageMagick's import and pactl. The game always
runs on this script's own Xvfb server (:97); the inherited DISPLAY and
WAYLAND_DISPLAY are never used, and there is no visible-window option.

    ingame_check.py cases                       list the cases
    ingame_check.py run CASE [CASE ...]         boot with the cases' edits, look, save, judge, restore
    ingame_check.py run CASE --dry-run          apply the edits to a scratch copy and judge that only
    ingame_check.py boot [CASE ...]             back up, edit, boot to gameplay and leave it running
    ingame_check.py boot --start MAP:SPAWN      the same with no edits, starting at an MSB player part
    ingame_check.py keys TOKEN ...              send keys to the running game (see KEYS)
    ingame_check.py shot NAME                   screenshot the running game
    ingame_check.py finish [--no-save]          save and exit, stop, judge, restore
    ingame_check.py restore                     stop everything and put the original saves back
    ingame_check.py status

Saves: `boot` renames KYTY_DIR/_SaveData aside (same disk) with a SHA-256
manifest and copies it back as the working copy. `restore` moves the working
copy into the run folder as evidence, renames the original back and checks
the manifest. Nothing is deleted.

Verdicts per case: the case's check must fail on the original, pass on the
edited file and pass on the file the game wrote after its own save. `kept`
means all three held; `dropped` means the game's save lost the edit; `no-save`
means the game never rewrote the profile; `crash` means it never reached
gameplay.

Run folders (screenshots, logs, diffs, verdict.json) go to ingame-runs/, which
git ignores.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import des_flags  # noqa: E402
import des_inventory  # noqa: E402
import des_save  # noqa: E402
import des_world  # noqa: E402

RUNS = ROOT / 'ingame-runs'
SESSION = RUNS / 'session.json'
EDITOR = ROOT / 'src/des_editor.py'
DISPLAY = ':97'
SINK = 'kyty_null'
PROFILE = 'SAVEDATA0PlayerProfile0'

KEYS = """Key tokens (Kyty's default keyboard map):
  j Cross   l Circle   Return Options   e R1   q L1   Up Down Left Right
  KEY*N     press N times
  KEY:S     hold for S seconds
  wait:S    sleep S seconds
  shot:NAME screenshot after the preceding keys"""
# Menu tabs, left to right: Equipment, Inventory, Status, Tendency, Settings.
# Every sequence starts and ends with the menu closed: Circle at the tab level
# closes it, while Circle in gameplay would roll the character.
SAVE_AND_EXIT = ['Return', 'wait:2', 'e*4', 'wait:2', 'Up', 'wait:1', 'shot:exit-menu', 'j', 'wait:2', 'j', 'wait:3']


# --- cases -----------------------------------------------------------------

_LOCAL_FLAG = 720           # m02: Ostrava ("Rendle") thanks the player - a one-off conversation
_BANK_ONLY_FLAG = 1380      # m02: Yuria ("the witch") thanks the player - likewise
_HIGH_FLAG = 10770          # m02 high range (bank 78a5c2d7): the Tower Shield pickup in 1-2
_HIGH_BANK_ONLY = 10766     # m02 high range: an Unknown Hero Soul pickup in 1-2
_REARM_FLAG = 10242         # m02: Late Moon Grass x2 in 1-1, 28 m straight ahead of spawn c0000_0001
_LOOK = ['wait:8', 'shot:look-1', 'wait:6', 'shot:look-2']


@dataclasses.dataclass
class Case:
    about: str
    edits: list[list[str]]               # des_editor.py argv after the file, `--out` is added
    check: Callable[[des_save.SaveFile], bool]
    expect: str                          # what the check asserts, for the report
    keys: list[str] = dataclasses.field(default_factory=list)
    precondition: Callable[[des_save.SaveFile], bool] | None = None
    start: tuple[str, str] | None = None      # (map, MSB player part): where the game starts


def _inventory(sf, category, item_id):
    return [row for row in des_inventory.inventory(sf) if (row['category'], row['id']) == (category, item_id)]


def _storage(sf, category, item_id):
    return [row for row in des_inventory.storage(sf) if (row['category'], row['id']) == (category, item_id)]


def _at(sf, index, category, item_id):
    rows = des_inventory.inventory(sf)
    return index < len(rows) and (rows[index]['category'], rows[index]['id']) == (category, item_id)


def _storage_at(sf, index, category, item_id):
    rows = des_inventory.storage(sf)
    return index < len(rows) and (rows[index]['category'], rows[index]['id']) == (category, item_id)


def _ring_history(sf) -> set[int]:
    keys = set(des_inventory.RING_KEYS)
    return {field.value for field, _ in sf.walk() if field.key in keys}


BROKEN_AT_START = ['7e9d1da7911f6851b976513723d2f500', '02613eccde715a549e53c9fad0bba32c',
                   '7fc278a5cc7fcc55aa98c52ca904f911', '5051b1513ffdcc568a3eda63db299832',
                   '3e394506925a905781d2b426b0be103e', '42d6aa7f5bddcc59b0459a36d9300ae6',
                   '52ef5aa979bcd15caea9f9a959a94d58']


def _broken(sf) -> dict[str, int]:
    out = {}
    for _, groups in des_world.world_blobs(sf):
        for _, _, entry in des_world.entries(groups):
            for record in entry.records or []:
                if des_world.record_name(record.key) == 'BROKEN' and entry.guid.hex() in BROKEN_AT_START:
                    out[entry.guid.hex()] = record.value
    return out


INVENTORY_KEYS = ['Return', 'wait:2', 'e', 'wait:2', 'shot:inventory', 'l', 'wait:1']
EQUIPMENT_KEYS = ['Return', 'wait:2', 'shot:equipment', 'l', 'wait:1']
# Left hand 1's weapon list shows every weapon with its durability; nothing is selected.
WEAPON_LIST_KEYS = ['Return', 'wait:2', 'Down', 'wait:1', 'j', 'wait:2', 'shot:weapons', 'l', 'wait:1', 'l', 'wait:1']
STATUS_KEYS = ['Return', 'wait:2', 'e*2', 'wait:2', 'shot:status', 'l', 'wait:1']

CASES: dict[str, Case] = {
    'qty': Case(
        'inventory quantity of a goods stack: Crescent Moon Grass 45 -> 37',
        [['inv', '--experimental', '--qty', '13=37']],
        lambda sf: [r['quantity'] for r in _inventory(sf, 'Goods', 1000)] == [37],
        'one Crescent Moon Grass stack of 37',
        INVENTORY_KEYS, lambda sf: _at(sf, 13, 'Goods', 1000)),
    'dur': Case(
        'durability of the equipped Kris Blade+5: 120 -> 61',
        [['inv', '--experimental', '--durability', '69=61']],
        lambda sf: [r['durability'] for r in _inventory(sf, 'Weapon', 10605)] == [61],
        'Kris Blade+5 durability 61',
        WEAPON_LIST_KEYS, lambda sf: _at(sf, 69, 'Weapon', 10605)),
    'upgrade': Case(
        'upgrade the equipped Large Sword of Moonlight+5 down to +2 (slot follows)',
        [['upgrade', '82', '21602', '--experimental']],
        lambda sf: len(_inventory(sf, 'Weapon', 21602)) == 1 and not _inventory(sf, 'Weapon', 21605)
        and any(row['id'] == 21602 for row in des_inventory.equipment(sf)),
        'Large Sword of Moonlight+2, still equipped', EQUIPMENT_KEYS + WEAPON_LIST_KEYS,
        lambda sf: _at(sf, 82, 'Weapon', 21605)),
    'upgrade-storage': Case(
        'upgrade the stored Bastard Sword to Bastard Sword+10',
        [['upgrade', '0', '20410', '--storage', '--experimental']],
        lambda sf: len(_storage(sf, 'Weapon', 20410)) == 1,
        'Bastard Sword+10 in storage', [],
        lambda sf: _storage_at(sf, 0, 'Weapon', 20400)),
    'ngplus': Case(
        'NG+ cycle: CLEARCOUNT 1 -> 2 (the exit screen shows "Games completed")',
        [['set', 'CLEARCOUNT=2', '--no-backup']],
        lambda sf: sf.get('CLEARCOUNT') == 2,
        'CLEARCOUNT 2', [],
        lambda sf: sf.get('CLEARCOUNT') == 1),
    'clearstate': Case(
        'NG+ display: CLEARSTATE 1 -> 2 with CLEARCOUNT left at 1 (does "Games completed" follow?)',
        [['set', 'CLEARSTATE=2', '--no-backup']],
        lambda sf: sf.get('CLEARSTATE') == 2,
        'CLEARSTATE 2', [],
        lambda sf: (sf.get('CLEARSTATE'), sf.get('CLEARCOUNT')) == (1, 1)),
    'respec': Case(
        'redistribute attributes at the same soul level: VIT 50 -> 60, STR 50 -> 40',
        [['respec', 'VIT=60', 'STR=40', '--no-backup']],
        lambda sf: (sf.get('PLAYER_CURRENTVITALITY'), sf.get('PLAYER_CURRENTSTRENGTH')) == (60, 40),
        'current VIT 60 and STR 40', EQUIPMENT_KEYS + STATUS_KEYS,
        lambda sf: (sf.get('PLAYER_CURRENTVITALITY'), sf.get('PLAYER_CURRENTSTRENGTH')) == (50, 50)),
    'world': Case(
        'world state: BROKEN 1 -> 0 on the seven broken objects of the 1-1 start, next to the spawn',
        [['wset', guid, 'BROKEN=0', '--experimental'] for guid in BROKEN_AT_START],
        lambda sf: _broken(sf) == {guid: 0 for guid in BROKEN_AT_START},
        'all seven BROKEN records 0; compare the gameplay screenshot with an unedited run', [],
        lambda sf: _broken(sf) == {guid: 1 for guid in BROKEN_AT_START}),
    'add-weapon': Case(
        'add a Broadsword to the inventory',
        [['add', 'Weapon', '20100', '--experimental']],
        lambda sf: len(_inventory(sf, 'Weapon', 20100)) == 1,
        'one Broadsword in the inventory', INVENTORY_KEYS),
    'add-armor': Case(
        "add a Leather Cap to the inventory",
        [['add', 'Armor', '100300', '--experimental']],
        lambda sf: len(_inventory(sf, 'Armor', 100300)) == 1,
        'one Leather Cap in the inventory', INVENTORY_KEYS),
    'add-ring': Case(
        'add a Ring of Great Strength (and its trophy-history entry)',
        [['add', 'Ring', '100', '--experimental']],
        lambda sf: len(_inventory(sf, 'Ring', 100)) == 1 and 100 in _ring_history(sf),
        'one Ring of Great Strength, recorded in TROPHIES_RING##', INVENTORY_KEYS),
    'add-goods-new': Case(
        'add a new stack of 3 Half Moon Grass',
        [['add', 'Goods', '1001', '--quantity', '3', '--experimental']],
        lambda sf: [r['quantity'] for r in _inventory(sf, 'Goods', 1001)] == [3],
        'one Half Moon Grass stack of 3', INVENTORY_KEYS),
    'add-goods-stack': Case(
        'add 5 Throwing Knives to the existing stack of 13',
        [['add', 'Goods', '1011', '--quantity', '5', '--experimental']],
        lambda sf: [r['quantity'] for r in _inventory(sf, 'Goods', 1011)] == [18],
        'one Throwing Knife stack of 18', INVENTORY_KEYS,
        lambda sf: [r['quantity'] for r in _inventory(sf, 'Goods', 1011)] == [13]),
    'storage-qty': Case(
        'storage low-quantity byte of the Elixir stack -> 7',
        [['inv', '--experimental', '--box-qty', '25=7']],
        lambda sf: [r['low_quantity'] for r in _storage(sf, *_ELIXIR)] == [7],
        'Elixir storage stack of 7', [],
        lambda sf: _storage_at(sf, 25, *_ELIXIR)),
    'add-storage': Case(
        'add a Mail Coif to the storage box',
        [['add', 'Armor', '100400', '--to', 'storage', '--experimental']],
        lambda sf: len(_storage(sf, 'Armor', 100400)) == 1,
        'one Mail Coif in storage', []),
    # Event flags (written for the end-game LOL character, profile 1, on m02).
    'flag-respawn': Case(
        'event flags: respawn Phalanx (clear death flag 4096 and soul flag 4103)',
        [['events', '--respawn', 'phalanx', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_flag(sf, 4096) and not des_flags.get_flag(sf, 4103),
        'flags 4096 and 4103 clear', [],
        lambda sf: des_flags.get_flag(sf, 4096) and des_flags.get_flag(sf, 4103)),
    'flag-local': Case(
        'event flags: clear Boletaria local flag 720 ("Rendle thanks") in its area slot and the current-area copy',
        [['events', '--set', f'm02:{_LOCAL_FLAG}=0', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_local(sf, 1, _LOCAL_FLAG)
        and not des_flags.get(sf.find(des_flags.PRIMARY).raw, _LOCAL_FLAG),
        'flag 720 clear in the m02 slot and in the primary copy', [],
        lambda sf: des_flags.current_area(sf) == 1 and des_flags.get_local(sf, 1, _LOCAL_FLAG)
        and bool(des_flags.mirror_ok(sf))),
    'flag-local-bankonly': Case(
        'diagnostic: clear Boletaria local flag 1380 ("The witch thanks") in the area slot only, '
        'leaving the current-area copy set: kept = the game trusts the slot, dropped = it trusts the copy',
        [['events', '--set', f'm02:{_BANK_ONLY_FLAG}=0', '--bank-only', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_local(sf, 1, _BANK_ONLY_FLAG),
        'flag 1380 clear in the m02 slot after the game saves', [],
        lambda sf: des_flags.current_area(sf) == 1 and des_flags.get_local(sf, 1, _BANK_ONLY_FLAG)
        and des_flags.get(sf.find(des_flags.PRIMARY).raw, _BANK_ONLY_FLAG)),
    'flag-local-high': Case(
        'event flags: clear Boletaria high-range flag 10770 (Tower Shield pickup) in bank 78a5c2d7 and the copy',
        [['events', '--set', f'm02:{_HIGH_FLAG}=0', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_local(sf, 1, _HIGH_FLAG)
        and not des_flags.get(sf.find(des_flags.PRIMARY).raw, _HIGH_FLAG),
        'flag 10770 clear in the m02 slot of 78a5c2d7 and in the primary copy', [],
        lambda sf: des_flags.current_area(sf) == 1 and des_flags.get_local(sf, 1, _HIGH_FLAG)
        and bool(des_flags.mirror_ok(sf))),
    'flag-local-high-bankonly': Case(
        'diagnostic: clear Boletaria high-range flag 10766 in bank 78a5c2d7 only, leaving the copy set',
        [['events', '--set', f'm02:{_HIGH_BANK_ONLY}=0', '--bank-only', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_local(sf, 1, _HIGH_BANK_ONLY),
        'flag 10766 clear in the m02 slot after the game saves', [],
        lambda sf: des_flags.current_area(sf) == 1 and des_flags.get_local(sf, 1, _HIGH_BANK_ONLY)),
    'flag-respawn-visible': Case(
        'event flags: full respawn of Phalanx, starting 14 m from its core in 1-1 (screenshots show whether it is back)',
        [['events', '--respawn', 'phalanx', '--full', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_flag(sf, 4096) and not des_flags.get_flag(sf, 4103),
        'flags 4096 and 4103 clear; look at the screenshots', _LOOK,
        lambda sf: des_flags.get_flag(sf, 4096), ('m02_00_00_00', 'c0000_0006')),
    'flag-respawn-plain-visible': Case(
        'event flags: plain respawn of Phalanx (death and soul flags only), starting 14 m from its core in 1-1',
        [['events', '--respawn', 'phalanx', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_flag(sf, 4096) and not des_flags.get_flag(sf, 4103),
        'flags 4096 and 4103 clear; look at the screenshots', _LOOK,
        lambda sf: des_flags.get_flag(sf, 4096), ('m02_00_00_00', 'c0000_0006')),
    'flag-npc-visible': Case(
        'event flags: put the (dead) Crestfallen Warrior back "in the Nexus", starting in the Nexus facing his spot',
        [['events', '--npc', 'heartbreak=stone_pillar', '--experimental', '--no-backup']],
        lambda sf: des_flags.get_flag(sf, 16420) and not des_flags.get_flag(sf, 16422),
        'state flag 16420 set, 16422 clear; look at the screenshots', _LOOK,
        lambda sf: des_flags.get_flag(sf, 16422), ('m01_00_00_00', 'c0000_0001')),
    'flag-rearm-pickup': Case(
        'event flags: re-arm the Late Moon Grass pickup (m02 10242) straight ahead of the 1-1 start',
        [['events', '--set', f'm02:{_REARM_FLAG}=0', '--experimental', '--no-backup']],
        lambda sf: not des_flags.get_local(sf, 1, _REARM_FLAG),
        'flag 10242 clear in the m02 slot; look at the screenshots for the item glow', _LOOK,
        lambda sf: des_flags.get_local(sf, 1, _REARM_FLAG), ('m02_00_00_00', 'c0000_0001')),
    'flag-defeat-visible': Case(
        'event flags: mark False King Allant defeated (death + soul flags, False King Demon Soul to the '
        'inventory), starting at 1-4 spawn c0000_0000, 5 m from his MSB part (c7230_0001, entity 821)',
        [['events', '--defeat', 'allant', '--experimental', '--no-backup']],
        lambda sf: des_flags.get_flag(sf, 4480) and des_flags.get_flag(sf, 4503)
        and bool(_inventory(sf, 'Goods', 7)),
        'flags 4480 and 4503 set and the False King Demon Soul in the inventory; look at the screenshots',
        _LOOK + ['Return', 'wait:2', 'e', 'wait:2', 'shot:inventory', 'l', 'wait:2'],
        lambda sf: not des_flags.get_flag(sf, 4480), ('m02_03_00_00', 'c0000_0000')),
}
_ELIXIR = ('Goods', None)        # filled from the catalog at start-up


def _resolve_elixir() -> None:
    global _ELIXIR
    for row in json.loads((ROOT / 'itemdb.json').read_text())['items']:
        if row.get('category') == 'Goods' and row.get('name') == 'Elixir':
            _ELIXIR = ('Goods', row['id'])
            return


# --- helpers ---------------------------------------------------------------

def die(message: str) -> None:
    raise SystemExit(f'ingame_check: {message}')


def kyty_dir() -> Path:
    value = os.environ.get('KYTY_DIR')
    if not value:
        die('set KYTY_DIR to the KytyPS5 checkout (e.g. /mnt/1T/Games/KytyPS5)')
    path = Path(value)
    for need in ('run-linux.sh', 'tools/local/demons-souls-smoke.py', '_SaveData/PPSA01341'):
        if not (path / need).exists():
            die(f'{path / need} is missing')
    return path


def tools_present() -> None:
    missing = [tool for tool in ('Xvfb', 'xdotool', 'import', 'pactl', 'xwininfo') if not shutil.which(tool)]
    if missing:
        die('missing tools: ' + ', '.join(missing))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(folder: Path) -> dict[str, str]:
    return {str(path.relative_to(folder)): sha256(path)
            for path in sorted(folder.rglob('*')) if path.is_file() and not path.is_symlink()}


def game_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ('WAYLAND_DISPLAY', 'DISPLAY')}
    env.update(DISPLAY=DISPLAY, SDL_VIDEODRIVER='x11', PULSE_SINK=SINK)
    return env


def load_session() -> dict:
    if not SESSION.exists():
        die('no session; run `boot` first')
    return json.loads(SESSION.read_text())


def save_session(session: dict) -> None:
    SESSION.write_text(json.dumps(session, indent=2))


def log(session: dict, message: str) -> None:
    line = f'{datetime.datetime.now():%H:%M:%S} {message}'
    print(line, flush=True)
    with open(Path(session['run']) / 'log.txt', 'a') as stream:
        stream.write(line + '\n')


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return Path(f'/proc/{pid}').exists() and 'Z' not in Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1][:3]


def own_xvfb(session: dict) -> bool:
    pid = session.get('xvfb')
    if not alive(pid):
        return False
    argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    return Path(argv[0].decode()).name == 'Xvfb' and DISPLAY.encode() in argv


# --- edits and judging -----------------------------------------------------

def apply_edits(source: Path, cases: list[str], out: Path) -> list[str]:
    """Apply every case's edits to `source`, writing `out`. Returns the CLI lines run."""
    current = source
    ran = []
    cases = [name for name in CASES if name in cases]   # index edits run before any insertion
    with tempfile.TemporaryDirectory() as scratch:
        for number, edit in enumerate(edit for name in cases for edit in CASES[name].edits):
            target = Path(scratch) / f'step{number}'
            argv = [sys.executable, str(EDITOR), edit[0], str(current), *edit[1:], '--out', str(target)]
            result = subprocess.run(argv, capture_output=True, text=True)
            ran.append(' '.join(edit) + '\n' + result.stdout + result.stderr)
            if result.returncode:
                die(f'edit failed: {" ".join(edit)}\n{result.stdout}{result.stderr}')
            current = target
        shutil.copyfile(current, out)
    return ran


def move_to(kyty: Path, path: Path, profile: str, map_name: str, spawn: str) -> str:
    """Start the character on another map at an MSB player part (Kyty's
    demons-souls-save.py set-map), then refill the primary flag copy from the
    new map's slots so the game does not save the old map's copy over it."""
    tool = kyty / 'tools/local/demons-souls-save.py'
    game = os.environ.get('DES_GAME_DIR')
    if not game and (kyty / 'game-path.txt').exists():
        game = (kyty / 'game-path.txt').read_text().strip()
    if not game:
        die('moving the character needs the game folder: set DES_GAME_DIR')
    with tempfile.TemporaryDirectory() as scratch:
        src, dst = Path(scratch) / 'src', Path(scratch) / 'dst'
        (src / 'PPSA01341' / profile).mkdir(parents=True)
        shutil.copyfile(path, src / 'PPSA01341' / profile / 'USR-DATA')
        result = subprocess.run([sys.executable, str(tool), 'set-map', str(src), str(dst), map_name,
                                 '--profile', profile, '--spawn', spawn, '--game', game],
                                capture_output=True, text=True)
        if result.returncode:
            die(f'set-map failed: {result.stdout}{result.stderr}')
        sf = des_save.load(str(dst / 'PPSA01341' / profile / 'USR-DATA'))
    synced = des_flags.sync_mirror(sf)
    des_save.save(sf, str(path))
    return (f'set-map {map_name} --spawn {spawn}\n{result.stdout}'
            f'primary flag copy refilled from the new map: {"changed" if synced else "unchanged"}\n')


def judge(cases: list[str], original: Path, edited: Path, written: Path | None) -> dict:
    before, after = des_save.load(str(original)), des_save.load(str(edited))
    game = des_save.load(str(written)) if written else None
    out = {}
    for name in cases:
        case = CASES[name]
        row = {'about': case.about, 'expect': case.expect,
               'original': case.check(before), 'edited': case.check(after),
               'game': case.check(game) if game else None}
        if row['original'] or not row['edited']:
            row['verdict'] = 'bad-case'
        elif game is None:
            row['verdict'] = 'no-save'
        else:
            row['verdict'] = 'kept' if row['game'] else 'dropped'
        out[name] = row
    return out


def diff(a: Path, b: Path, out: Path) -> None:
    result = subprocess.run([sys.executable, str(EDITOR), 'diff', str(a), str(b)], capture_output=True, text=True)
    out.write_text(result.stdout + result.stderr)


# --- the game --------------------------------------------------------------

def start_xvfb(session: dict) -> None:
    if Path(f'/tmp/.X11-unix/X{DISPLAY[1:]}').exists() or Path(f'/tmp/.X{DISPLAY[1:]}-lock').exists():
        die(f'display {DISPLAY} is already in use; stop that server or run `restore`')
    stream = open(Path(session['run']) / 'xvfb.log', 'w')
    process = subprocess.Popen(['Xvfb', DISPLAY, '-screen', '0', '1280x720x24', '-ac', '-nolisten', 'tcp'],
                               stdout=stream, stderr=stream, start_new_session=True)
    session['xvfb'] = process.pid
    save_session(session)
    for _ in range(50):
        if Path(f'/tmp/.X11-unix/X{DISPLAY[1:]}').exists():
            break
        time.sleep(.1)
    if not own_xvfb(session):
        die('Xvfb did not start')
    log(session, f'Xvfb {DISPLAY} pid {process.pid}')


def start_sink(session: dict) -> None:
    sinks = subprocess.run(['pactl', 'list', 'short', 'sinks'], capture_output=True, text=True).stdout
    if re.search(rf'\s{SINK}\s', sinks):
        return
    result = subprocess.run(['pactl', 'load-module', 'module-null-sink', f'sink_name={SINK}'],
                            capture_output=True, text=True)
    if result.returncode == 0:
        session['sink_module'] = result.stdout.strip()
        save_session(session)


def start_game(session: dict, kyty: Path) -> None:
    if not own_xvfb(session):
        die(f'refusing to start the game: {DISPLAY} is not this run\'s Xvfb')
    live = Path(session['run']) / 'live.txt'
    live.write_text('')
    # run-linux.sh leaves a watcher running that keeps its stdout open, so the
    # output goes to a file (never a pipe) and the pid line is read from it.
    launch = Path(session['run']) / 'launch.txt'
    with open(launch, 'w') as stream:
        launcher = subprocess.Popen(['./run-linux.sh', '--set', f'KYTY_LIVE_FILE={live}'], cwd=kyty,
                                    env=game_env(), stdout=stream, stderr=subprocess.STDOUT,
                                    start_new_session=True)
    session['launcher'] = launcher.pid
    save_session(session)
    deadline = time.monotonic() + 600
    match = None
    while time.monotonic() < deadline and not match:
        match = re.search(r'pid (\d+); logs: (\S+)', launch.read_text())
        if not match and launcher.poll() not in (None, 0):
            break
        time.sleep(1)
    if not match:
        die('run-linux.sh printed no pid; see launch.txt')
    session['game'], session['game_logs'] = int(match[1]), match[2]
    save_session(session)
    log(session, f'game pid {session["game"]}, logs {match[2]}')


def reach_gameplay(session: dict, kyty: Path) -> bool:
    # The smoke script's OCR can read the title menu mid-fade and miss Continue;
    # a later attempt, after the fade, finds it.
    for attempt in (1, 2, 3):
        if attempt > 1:
            time.sleep(8)
        result = subprocess.run([sys.executable, 'tools/local/demons-souls-smoke.py', '--resume',
                                 '--stop-at', 'gameplay', '--pid', str(session['game'])],
                                cwd=kyty, env=game_env(), capture_output=True, text=True, timeout=1200)
        (Path(session['run']) / f'smoke{attempt}.txt').write_text(result.stdout + result.stderr)
        if result.returncode == 0 and 'Gameplay HUD detected' in result.stdout:
            log(session, 'gameplay reached')
            return True
        log(session, f'smoke attempt {attempt} did not reach gameplay')
        if not alive(session['game']):
            return False
    return False


def stop_game(session: dict) -> None:
    pid = session.get('game')
    if alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            if not alive(pid):
                break
            time.sleep(.1)
        if alive(pid):
            os.kill(pid, signal.SIGKILL)
        log(session, f'game {pid} stopped')
    if session.get('launcher'):
        try:
            os.killpg(session['launcher'], signal.SIGTERM)    # the launcher's leftover watcher
        except ProcessLookupError:
            pass
        session['launcher'] = None
    if own_xvfb(session):
        os.killpg(session['xvfb'], signal.SIGTERM)
        log(session, 'Xvfb stopped')
    if session.get('sink_module'):
        subprocess.run(['pactl', 'unload-module', session['sink_module']], capture_output=True)
        session['sink_module'] = None
    save_session(session)


def xdo(*args: str) -> str:
    return subprocess.run(['xdotool', *args], env=game_env(), capture_output=True, text=True, timeout=20).stdout


def send_keys(session: dict, tokens: list[str]) -> None:
    if not own_xvfb(session) or not alive(session.get('game')):
        die('the game is not running on this run\'s Xvfb')
    windows = xdo('search', '--name', "Demon").split()
    if windows:
        xdo('windowfocus', '--sync', windows[0])
    for token in tokens:
        if token.startswith('wait:'):
            time.sleep(float(token[5:]))
            continue
        if token.startswith('shot:'):
            screenshot(session, token[5:])
            continue
        key, count, hold = token, 1, .15
        if '*' in key:
            key, count = key.split('*'); count = int(count)
        if ':' in key:
            key, hold = key.split(':'); hold = float(hold)
        for _ in range(count):
            xdo('keydown', key); time.sleep(hold); xdo('keyup', key); time.sleep(.45)
    log(session, 'keys ' + ' '.join(tokens))


def screenshot(session: dict, name: str) -> Path:
    shots = Path(session['run']) / 'shots'
    shots.mkdir(exist_ok=True)
    path = shots / f'{len(list(shots.iterdir())):02d}-{name}.png'
    subprocess.run(['import', '-window', 'root', '-resize', '1280x720>', str(path)],
                   env=game_env(), check=True, timeout=20)
    print(path, flush=True)
    return path


# --- commands --------------------------------------------------------------

def cmd_boot(cases: list[str], profile: str, start: tuple[str, str] | None = None) -> dict:
    kyty = kyty_dir()
    tools_present()
    if SESSION.exists():
        die('a session is open; `finish` or `restore` it first')
    saves = kyty / '_SaveData'
    if list(kyty.glob('_SaveData.ingame-*')):
        die('an earlier backup is still beside _SaveData; run `restore` or inspect it by hand')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    run = RUNS / f'{stamp}-{"+".join(cases) or "explore"}'
    run.mkdir(parents=True)
    backup = kyty / f'_SaveData.ingame-{stamp}'
    session = {'run': str(run), 'kyty': str(kyty), 'backup': str(backup), 'profile': profile,
               'cases': cases, 'xvfb': None, 'game': None, 'sink_module': None}
    profile_file = saves / 'PPSA01341' / profile / 'USR-DATA'
    if not profile_file.exists():
        die(f'{profile_file} does not exist')
    for name in cases:
        pre = CASES[name].precondition
        if pre and not pre(des_save.load(str(profile_file))):
            die(f'{name}: the profile does not hold what the case expects')

    (run / 'manifest.json').write_text(json.dumps(manifest(saves), indent=1))
    shutil.copyfile(profile_file, run / 'original-USR-DATA')
    saves.rename(backup)
    save_session(session)              # from here on `restore` can put things back
    shutil.copytree(backup, saves, symlinks=True)
    log(session, f'saves backed up to {backup.name}; working copy in place')
    if start and not cases:                  # explore from another spot, no edits
        shutil.copyfile(run / 'original-USR-DATA', run / 'edited-USR-DATA')
        (run / 'edits.txt').write_text(move_to(kyty, run / 'edited-USR-DATA', profile, *start))
        shutil.copyfile(run / 'edited-USR-DATA', profile_file)
    if cases:
        ran = apply_edits(run / 'original-USR-DATA', cases, run / 'edited-USR-DATA')
        starts = {CASES[name].start for name in cases} - {None}
        if len(starts) > 1:
            die(f'the cases start in different places: {sorted(starts)}')
        if starts:
            ran.append(move_to(kyty, run / 'edited-USR-DATA', profile, *starts.pop()))
        (run / 'edits.txt').write_text('\n'.join(ran))
        shutil.copyfile(run / 'edited-USR-DATA', profile_file)
        diff(run / 'original-USR-DATA', run / 'edited-USR-DATA', run / 'diff-edit.txt')
        log(session, f'edited {profile}: {", ".join(cases)}')
    session['edited_sha'] = sha256(profile_file)
    save_session(session)

    start_xvfb(session)
    start_sink(session)
    start_game(session, kyty)
    session['gameplay'] = reach_gameplay(session, kyty)
    save_session(session)
    screenshot(session, 'gameplay' if session['gameplay'] else 'stuck')
    return session


def wait_for_write(path: Path, before: str, timeout: float = 90) -> bool:
    """Wait for the profile to differ from `before` and then hold still for one poll."""
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        current = sha256(path) if path.exists() else None
        if current and current != before:
            if current == last:
                return True
            last = current
        time.sleep(3)
    return False


def cmd_finish(save: bool, exit_keys: list[str]) -> dict:
    session = load_session()
    run, kyty = Path(session['run']), Path(session['kyty'])
    profile_file = kyty / '_SaveData/PPSA01341' / session['profile'] / 'USR-DATA'
    written = None
    if save and session.get('gameplay') and alive(session.get('game')):
        # The game also autosaves while menus are open, so the exit save is the
        # first write after the exit keys, not the first write after the edit.
        before = sha256(profile_file)
        send_keys(session, exit_keys)
        screenshot(session, 'after-exit')
        if wait_for_write(profile_file, before):
            log(session, 'the game saved the profile on exit')
        elif before != session['edited_sha']:
            log(session, 'no write after the exit keys; judging the game\'s earlier autosave')
        else:
            log(session, 'the game did not rewrite the profile')
        if sha256(profile_file) != session['edited_sha']:
            written = run / 'game-USR-DATA'
            shutil.copyfile(profile_file, written)
    stop_game(session)
    result = {}
    if session['cases']:
        result = judge(session['cases'], run / 'original-USR-DATA', run / 'edited-USR-DATA', written)
        if not session.get('gameplay'):
            for row in result.values():
                row['verdict'] = 'crash' if row['verdict'] != 'bad-case' else row['verdict']
    if written:
        diff(run / 'edited-USR-DATA', written, run / 'diff-game.txt')
    (run / 'verdict.json').write_text(json.dumps(result, indent=2))
    cmd_restore()
    for name, row in result.items():
        print(f'{name:16} {row["verdict"]:8} {row["expect"]}')
    print(f'evidence: {run}')
    return result


def cmd_restore() -> None:
    session = load_session()
    stop_game(session)
    kyty, backup, run = Path(session['kyty']), Path(session['backup']), Path(session['run'])
    saves = kyty / '_SaveData'
    if backup.exists():
        if saves.exists():
            saves.rename(run / 'saves-after')
        backup.rename(saves)
    expected = json.loads((run / 'manifest.json').read_text())
    actual = manifest(saves)
    if actual != expected:
        changed = sorted(set(expected) ^ set(actual) | {k for k in expected if actual.get(k) != expected[k]})
        die('RESTORED SAVES DO NOT MATCH THE MANIFEST: ' + ', '.join(changed[:10]))
    log(session, 'original saves restored and verified against the manifest')
    SESSION.unlink()


def cmd_run(cases: list[str], profile: str, dry_run: bool, exit_keys: list[str]) -> int:
    if dry_run:
        kyty = kyty_dir()
        source = kyty / '_SaveData/PPSA01341' / profile / 'USR-DATA'
        with tempfile.TemporaryDirectory() as scratch:
            edited = Path(scratch) / 'edited'
            print('\n'.join(apply_edits(source, cases, edited)))
            for name, row in judge(cases, source, edited, None).items():
                print(f'{name:16} original={row["original"]} edited={row["edited"]} '
                      f'{"ok" if row["verdict"] == "no-save" else row["verdict"]}  {row["expect"]}')
        return 0
    try:
        session = cmd_boot(cases, profile)
        if session.get('gameplay'):
            sent = []
            for name in cases:
                keys = CASES[name].keys
                if keys and keys not in sent:          # cases sharing a screen look once
                    send_keys(session, keys)
                    sent.append(keys)
        result = cmd_finish(True, exit_keys)
    except BaseException:
        if SESSION.exists():
            cmd_restore()
        raise
    return 0 if result and all(row['verdict'] == 'kept' for row in result.values()) else 1


def main() -> int:
    _resolve_elixir()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('cases')
    for name in ('run', 'boot'):
        p = sub.add_parser(name)
        p.add_argument('cases', nargs='*' if name == 'boot' else '+', choices=sorted(CASES), metavar='CASE')
        p.add_argument('--profile', default=PROFILE)
        if name == 'boot':
            p.add_argument('--start', metavar='MAP:SPAWN',
                           help='start on another map at an MSB player part (e.g. m02_00_00_00:c0000_0006)')
        if name == 'run':
            p.add_argument('--dry-run', action='store_true')
            p.add_argument('--exit-keys', nargs='+', default=SAVE_AND_EXIT)
    p = sub.add_parser('keys', epilog=KEYS, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('tokens', nargs='+')
    p = sub.add_parser('shot')
    p.add_argument('name')
    p = sub.add_parser('finish')
    p.add_argument('--no-save', action='store_true')
    p.add_argument('--exit-keys', nargs='+', default=SAVE_AND_EXIT)
    sub.add_parser('restore')
    sub.add_parser('status')
    a = parser.parse_args()

    if a.command == 'cases':
        for name, case in CASES.items():
            print(f'{name:16} {case.about}')
    elif a.command == 'run':
        return cmd_run(a.cases, a.profile, a.dry_run, a.exit_keys)
    elif a.command == 'boot':
        try:
            start = tuple(a.start.split(':', 1)) if a.start else None
            session = cmd_boot(a.cases, a.profile, start)
        except BaseException:
            if SESSION.exists():
                cmd_restore()
            raise
        print(f'gameplay: {session["gameplay"]}; session left running (finish or restore it)')
    elif a.command == 'keys':
        send_keys(load_session(), a.tokens)
    elif a.command == 'shot':
        screenshot(load_session(), a.name)
    elif a.command == 'finish':
        cmd_finish(not a.no_save, a.exit_keys)
    elif a.command == 'restore':
        cmd_restore()
    elif a.command == 'status':
        session = load_session()
        print(json.dumps({**session, 'xvfb_alive': own_xvfb(session),
                          'game_alive': alive(session.get('game'))}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
