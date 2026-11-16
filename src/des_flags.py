"""Event flags: the numbered flags the game's Lua scripts read and write.

Every ``SetEventFlag(id, ...)`` / ``IsCompleteEvent(id)`` in the game's scripts
addresses one bit of a fixed-size blob stored in the save, at

    bit position = flag id          (LSB first; flag 4096 = byte 512, bit 0)

The identification evidence (docs/research-event-flags.md) is threefold and
independent: the boss-death flags match the demon souls each save holds, the
NPC quest states match each save's story progress with exactly one state set
per NPC, and a New Game+ wipes the world flags while keeping the Nexus's.

Three blobs exist; the primary one is proven:

    ===========  ======  ===================  ==============================
    blob (key)   bytes   flags                evidence
    ===========  ======  ===================  ==============================
    ``522ad995`` 2256    0 .. 18047           bosses, NPC states, tutorial,
                                              "been to", NG+ semantics
    ``0af4946a`` 3200    0 .. 25599           same bit-per-flag layout; bank
                                              selector not identified yet
    ``78a5c2d7`` 4096    0 .. 32767           same layout; wiped on NG+;
                                              empty for a fresh character
    ===========  ======  ===================  ==============================

The script flag ids reach ~17800 (plus two 20xxx outliers), so everything the
scripts address lives in the primary blob; the other two are exposed for
inspection and saved untouched unless explicitly edited.

What the flags mean comes from the game's own scripts, compiled into
``flagdb.json`` by ``tools/build_flagdb.py``: boss-death flags (each with the
one-shot "soul" pickup flag beside it), per-NPC quest-state machines (one
state flag set at a time, plus a +1000 backup twin the scripts use to undo
temporary hostility), and per-map event descriptions.

Edits are bit flips inside an existing blob, so sizes and offsets never move.
"""
from __future__ import annotations

from pathlib import Path
import re

import des_save

DATA_DIR = Path(__file__).resolve().parent.parent      # flagdb.json lives in the repo root

# blob key -> (capacity in flags, role)
PRIMARY = 0x522AD995
BANK_C = 0x0AF4946A
BANK_B = 0x78A5C2D7
BLOBS = {
    PRIMARY: (18048, "event flags (bosses, NPC quests, doors, pickups)"),
    BANK_C: (25600, "second flag bank (selector not identified)"),
    BANK_B: (32768, "third flag bank (wiped on New Game+)"),
}

_DEFAULT: list = []         # cached [FlagDB] (empty list = not loaded yet)


class FlagDB:
    """The flag database (flagdb.json): names, bosses, NPC states, areas."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.areas = {int(k): v for k, v in doc.get('areas', {}).items()}
        self.bosses = doc.get('bosses', [])
        self.boss_by_id = {b['id']: b for b in self.bosses}
        self.npcs = doc.get('npcs', [])
        self.backup_offset = doc.get('backup_offset', 1000)
        self.events = {e['id']: e for e in doc.get('events', [])}
        self.tendency_pairs = doc.get('tendency_pairs', [])

    def event_label(self, flag: int) -> str | None:
        """Human description of a flag: boss, NPC state or map comment.

        Some flag numbers are documented by several map scripts (the scripts
        reuse small ids), so up to three distinct descriptions are joined.
        """
        boss = self.boss_by_id.get(flag)
        if boss:
            return f"{boss['name']} defeated"
        entry = self.events.get(flag)
        if not entry:
            return None
        texts: list[str] = []
        for area in sorted(entry.get('areas') or {}, key=lambda a: int(a)):
            for text in entry['areas'][area]:
                if text and text not in texts:
                    texts.append(text)
        if not texts:
            return None
        return ' | '.join(texts[:3]) + (' …' if len(texts) > 3 else '')

    def find_boss(self, name: str) -> dict:
        key = name.strip().lower()
        matches = [b for b in self.bosses if key in b['name'].lower()]
        if len(matches) != 1:
            names = ', '.join(sorted(b['name'] for b in self.bosses))
            raise ValueError(f"boss '{name}' matches {len(matches)} bosses "
                             f"(known: {names})")
        return matches[0]

    def find_npc(self, name: str) -> dict:
        """An NPC state list by its list name or a state-name fragment."""
        key = name.strip().lower().replace(' ', '_')
        for npc in self.npcs:
            if key in npc['list'].lower():
                return npc
        for npc in self.npcs:
            if any(key in state['name'].lower() for state in npc['states']):
                return npc
        names = ', '.join(npc['list'] for npc in self.npcs)
        raise ValueError(f"no NPC state list matches '{name}' (known: {names})")

    def find_state(self, npc: dict, state: str) -> dict:
        key = state.strip().lower().replace(' ', '_')
        matches = [s for s in npc['states'] if key in s['name'].lower()]
        if len(matches) != 1:
            names = ', '.join(s['name'] for s in npc['states'])
            raise ValueError(f"state '{state}' matches {len(matches)} states "
                             f"of {npc['list']} (known: {names})")
        return matches[0]


def load_db(path: str | None = None) -> FlagDB | None:
    """The repository flagdb.json, or None when it has not been generated."""
    if not _DEFAULT:
        import json
        path = Path(path) if path is not None else DATA_DIR / 'flagdb.json'
        try:
            _DEFAULT.append(FlagDB(json.loads(path.read_text(encoding='utf-8'))))
        except (OSError, ValueError):
            _DEFAULT.append(None)
    return _DEFAULT[0]


# --------------------------------------------------------------------------- #
#  Bit addressing
# --------------------------------------------------------------------------- #
def blob_for(flag: int) -> int:
    """The primary blob holds every flag the scripts address."""
    capacity = BLOBS[PRIMARY][0]
    if not 0 <= flag < capacity:
        raise ValueError(f"flag {flag} is outside the event-flag blob "
                         f"(0..{capacity - 1})")
    return PRIMARY


def get(raw: bytes, flag: int) -> bool:
    if not 0 <= flag or flag >> 3 >= len(raw):
        raise ValueError(f"flag {flag} is outside its {len(raw)}-byte blob")
    return bool(raw[flag >> 3] >> (flag & 7) & 1)


def set_bit(raw: bytes, flag: int, value: bool) -> bytes:
    """A copy of `raw` with one flag bit changed; length never changes."""
    if not 0 <= flag or flag >> 3 >= len(raw):
        raise ValueError(f"flag {flag} is outside its {len(raw)}-byte blob")
    out = bytearray(raw)
    if value:
        out[flag >> 3] |= 1 << (flag & 7)
    else:
        out[flag >> 3] &= ~(1 << (flag & 7)) & 0xFF
    return bytes(out)


def iter_flags(raw: bytes):
    """Every set flag id in one blob, in order."""
    for i, byte in enumerate(raw):
        for bit in range(8):
            if byte >> bit & 1:
                yield i * 8 + bit


# --------------------------------------------------------------------------- #
#  Save-level access
# --------------------------------------------------------------------------- #
def _blob_field(sf: des_save.SaveFile, key: int) -> des_save.Field:
    field = sf.find(key)
    if field is None:
        raise ValueError(f"this save has no event-flag blob {key:08x} "
                         "(options profiles do not carry one)")
    return field


def get_flag(sf: des_save.SaveFile, flag: int) -> bool:
    return get(_blob_field(sf, PRIMARY).raw, flag)


def set_flag(sf: des_save.SaveFile, flag: int, value: bool) -> None:
    """Flip one flag bit in place (same-size edit; the caller saves)."""
    field = _blob_field(sf, PRIMARY)
    field.raw = set_bit(field.raw, flag, value)


def summary(sf: des_save.SaveFile) -> dict:
    """Raw view: set-bit counts per blob."""
    out = {}
    for key, (capacity, note) in BLOBS.items():
        field = sf.find(key)
        if field is None:
            continue
        bits = sum(bin(byte).count('1') for byte in field.raw)
        out[f"{key:08x}"] = {"bytes": len(field.raw), "bits": bits,
                             "capacity": capacity, "note": note}
    return out


# --------------------------------------------------------------------------- #
#  Named views (need the database)
# --------------------------------------------------------------------------- #
def bosses(sf: des_save.SaveFile, db: FlagDB) -> list[dict]:
    """Every boss: defeated flag, soul-taken flag."""
    return [{
        "id": boss['id'], "name": boss['name'], "world": boss['world'],
        "defeated": get_flag(sf, boss['id']),
        "soul_taken": get_flag(sf, boss['soul'])
        if boss.get('soul') is not None else None,
    } for boss in db.bosses]


def npc_states(sf: des_save.SaveFile, db: FlagDB) -> list[dict]:
    """Every NPC state machine with the flags that are currently set."""
    out = []
    capacity = BLOBS[PRIMARY][0]
    for npc in db.npcs:
        states = [s['name'] for s in npc['states'] if get_flag(sf, s['id'])]
        backups = [s['name'] for s in npc['states']
                   if s['id'] + db.backup_offset < capacity
                   and get_flag(sf, s['id'] + db.backup_offset)]
        out.append({"list": npc['list'], "set": states, "backup": backups})
    return out


# --------------------------------------------------------------------------- #
#  Recipes
# --------------------------------------------------------------------------- #
def respawn_boss(sf: des_save.SaveFile, db: FlagDB, name: str) -> dict:
    """Make one boss alive again: clear its death flag and its soul-taken flag.

    The scripts re-evaluate everything on area load (the boss spawns while its
    death flag is clear, and the fog gate, boss-room collision and archstone
    state all key off the same flag), and the cleared soul flag lets the
    one-shot demon-soul pickup happen again.
    """
    boss = db.find_boss(name)
    set_flag(sf, boss['id'], False)
    cleared = [boss['id']]
    if boss.get('soul') is not None:
        set_flag(sf, boss['soul'], False)
        cleared.append(boss['soul'])
    return {"boss": boss['name'], "cleared": cleared}


def set_npc_state(sf: des_save.SaveFile, db: FlagDB, npc: str, state: str) -> dict:
    """Put one NPC into exactly one quest state.

    Sets the chosen state flag and clears every other state of that NPC - the
    invariant the scripts keep with SetNpcStateFlag - plus the +1000 backup
    twins the scripts use to undo temporary hostility.
    """
    npc_def = db.find_npc(npc)
    target = db.find_state(npc_def, state)
    ids = [s['id'] for s in npc_def['states']]
    for flag in ids:
        set_flag(sf, flag, flag == target['id'])
    capacity = BLOBS[PRIMARY][0]
    for flag in ids:
        backup = flag + db.backup_offset
        if backup < capacity:
            set_flag(sf, backup, False)
    return {"npc": npc_def['list'], "state": target['name'], "id": target['id']}


def parse_target(text: str) -> int:
    """``4096`` -> flag id."""
    if not re.fullmatch(r'\d+', text.strip()):
        raise ValueError(f"bad flag {text!r} (expected a number, e.g. 4096)")
    return int(text)
