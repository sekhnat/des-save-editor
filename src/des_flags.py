"""Event flags: the numbered flags the game's Lua scripts read and write.

Every ``SetEventFlag(id, ...)`` / ``IsCompleteEvent(id)`` in the game's scripts
addresses one bit, LSB first (flag 4096 = byte 512, bit 0), in one of two
numberings (docs/research-event-flags.md):

* **local flags** (ids 0..3199 and 8192..12287): each map (``m01`` Nexus ..
  ``m08``) has its own copy of both ranges, so the same number means different
  things in different map scripts. Each range has its per-area bank: ids below
  3200 at bit ``area * 3200 + id`` of ``0af4946a``, ids 8192..12287 at bit
  ``area * 4096 + (id - 8192)`` of ``78a5c2d7``. The primary blob holds a
  working copy of the *current* area's slots at bit ``id`` (the area of
  ``MAPUID``). Every sampled save keeps that copy identical to its slots, and
  the game refills the copy from the slot when it loads (checked on Kyty).
* **global flags** (every other id): one save-wide set, at bit ``id`` of the
  primary blob - bosses, NPC quest states, tutorial, shop stock, counters.

    ===========  ======  ===============================  =====================
    blob (key)   bytes   layout                           evidence
    ===========  ======  ===============================  =====================
    ``522ad995`` 2256    bit = id; 0..3199 and            bosses, NPC states,
                         8192..12287 are copies of the    NG+ semantics, the
                         current area's local slots       mirror invariant
    ``0af4946a`` 3200    8 areas x 3200 local flags       matches the primary
                         (bit = area * 3200 + id)         copy on every save
    ``78a5c2d7`` 4096    8 areas x 4096 local flags       matches the primary
                         (bit = area * 4096 + id - 8192)  copy on every save
    ===========  ======  ===============================  =====================

``area`` is the map number minus one (m01 -> 0); ``MAPUID``'s top byte is the
current map number. Editing a local flag writes its area slot and, when that
area is the current one, the primary copy too, so the two never disagree.

What the flags mean comes from the game's own scripts and parameter tables,
compiled into ``flagdb.json`` by ``tools/build_flagdb.py``: boss-death flags
(each with the one-shot "soul" pickup flag beside it), per-NPC quest-state
machines (one state flag set at a time, plus a +1000 twin holding the previous
state, which the game restores when you seek forgiveness), per-map local-flag descriptions, shop-stock
flag groups and one-time drop flags.

Edits are bit flips inside an existing blob, so sizes and offsets never move.
"""
from __future__ import annotations

from pathlib import Path
import re

import des_save

DATA_DIR = Path(__file__).resolve().parent.parent      # flagdb.json lives in the repo root

# blob key -> (capacity in bits, role)
PRIMARY = 0x522AD995
BANK_C = 0x0AF4946A
BANK_B = 0x78A5C2D7
LOCAL = BANK_C
BLOBS = {
    PRIMARY: (18048, "global flags + current area's local flags"),
    BANK_C: (25600, "per-area local flags 0..3199 (8 areas x 3200)"),
    BANK_B: (32768, "per-area local flags 8192..12287 (8 areas x 4096)"),
}
LOCAL_SIZE = 3200           # local flags per area in the low range
AREAS = 8                   # m01 .. m08
BANK_B_AREA = 4096          # bits per area in BANK_B
# the two local ranges: (first id, end id, per-area bank, bits per area slot)
RANGES = ((0, LOCAL_SIZE, BANK_C, LOCAL_SIZE),
          (8192, 8192 + BANK_B_AREA, BANK_B, BANK_B_AREA))
MAPUID = 'MAPUID'

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
        self.local = {int(area): {e['id']: e for e in rows}
                      for area, rows in doc.get('local', {}).items()}
        self.globals = {e['id']: e for e in doc.get('global', [])}
        self.scripts = {e['id']: e for e in doc.get('scripts', [])}
        self.local_any = {e['id']: e for e in doc.get('local_any', [])}
        self.shop_flags = {}
        for shop in doc.get('shops', []):
            for n in range(shop.get('count', 8)):
                self.shop_flags[shop['flag'] + n] = (shop, n)
        self.lot_flags: dict[int, list[dict]] = {}
        for lot in doc.get('itemlots', []):
            self.lot_flags.setdefault(lot['flag'], []).append(lot)
        self.tendency_pairs = doc.get('tendency_pairs', [])
        self.forgiveness = doc.get('forgiveness', [])
        # area (0-based) -> {flag: {level, map, items}} of map pickups (treasure
        # parts in the map layouts); items are [category, id, count, name]
        self.pickup_items = {int(area) - 1: {int(flag): row for flag, row in rows.items()}
                             for area, rows in doc.get('pickups', {}).items()}
        self.pickups = {area: sorted(rows) for area, rows in self.pickup_items.items()}
        self.npc_flags: dict[int, str] = {}
        for npc in self.npcs:
            for state in npc['states']:
                label = state.get('label') or state['name'].split('_STATE_')[-1]
                name = npc.get('name', npc['list'])
                self.npc_flags.setdefault(state['id'], f"{name}: {label}")
                self.npc_flags.setdefault(state['id'] + self.backup_offset,
                                          f"{name}: previous state was \"{label}\"")

    def area_name(self, area: int) -> str:
        """``area`` is 0-based (m01 -> 0)."""
        info = self.areas.get(area + 1)
        return f"m{area + 1:02d} {info['name']}" if info else f"m{area + 1:02d}"

    def event_label(self, flag: int, area: int | None = None) -> str | None:
        """Human description of a flag.

        Local flags (see RANGES) need their 0-based ``area``; without it only
        the descriptions from non-map scripts and map-independent tables (talk,
        one-time drops) are known. Global flags are named by boss, curated
        labels, script comments (several maps may document one flag; up to
        three distinct texts are joined), shop stock or one-time drops.
        """
        texts: list[str] = []
        if is_local(flag):
            entry = self.local.get(area + 1, {}).get(flag) if area is not None else None
            texts = list(entry.get('descs', [])) if entry else []
            for source in (self.scripts, self.local_any):
                if not texts and flag in source:
                    texts = list(source[flag].get('descs', []))
            for lot in self.lot_flags.get(flag, [])[:1]:
                if not texts:
                    texts.append(f"One-time drop: {lot.get('name') or lot['lot']}")
        else:
            boss = self.boss_by_id.get(flag)
            if boss:
                return f"{boss['name']} defeated"
            souls = [b for b in self.bosses if b.get('soul') == flag]
            if souls:
                texts.append(f"{souls[0]['name']}'s demon soul taken")
            if flag in self.npc_flags:
                texts.append(self.npc_flags[flag])
            entry = self.globals.get(flag) or {}
            for text in entry.get('descs', []):
                if text and text not in texts:
                    texts.append(text)
            for key in sorted(entry.get('areas') or {}, key=int):
                for text in entry['areas'][key]:
                    if text and text not in texts:
                        texts.append(text)
            if flag in self.shop_flags:
                shop, n = self.shop_flags[flag]
                texts.append(f"Shop stock: {shop.get('name') or shop['item']} "
                             f"(shop row {shop['row']}, counter bit {n + 1} of "
                             f"{shop.get('count', 8)})")
            for lot in self.lot_flags.get(flag, [])[:1]:
                texts.append(f"One-time drop: {lot.get('name') or lot['lot']}")
        if not texts:
            return None
        return ' | '.join(texts[:3]) + (' …' if len(texts) > 3 else '')

    def documented_local(self, area: int) -> list[int]:
        return sorted(self.local.get(area + 1, {}))

    def find_boss(self, name: str) -> dict:
        key = name.strip().lower()
        matches = [b for b in self.bosses if key in b['name'].lower()]
        if len(matches) != 1:
            names = ', '.join(sorted(b['name'] for b in self.bosses))
            raise ValueError(f"boss '{name}' matches {len(matches)} bosses "
                             f"(known: {names})")
        return matches[0]

    def find_npc(self, name: str) -> dict:
        """An NPC state list by its list name, display name or a state-name fragment."""
        key = name.strip().lower().replace(' ', '_')
        for npc in self.npcs:
            if key in npc['list'].lower():
                return npc
        for npc in self.npcs:
            if key in npc.get('name', '').lower().replace(' ', '_'):
                return npc
        for npc in self.npcs:
            if any(key in state['name'].lower() for state in npc['states']):
                return npc
        names = ', '.join(npc['list'] for npc in self.npcs)
        raise ValueError(f"no NPC state list matches '{name}' (known: {names})")

    def find_state(self, npc: dict, state: str) -> dict:
        """A quest state of `npc` by a fragment of its constant or its label."""
        key = state.strip().lower().replace(' ', '_')
        states = exclusive_states(npc)
        matches = [s for s in states if key in s['name'].lower()]
        if not matches:
            matches = [s for s in states
                       if key in s.get('label', '').lower().replace(' ', '_')]
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


def local_range(flag: int) -> tuple[int, int, int, int] | None:
    """The local range holding ``flag`` (first, end, bank, slot size), or None."""
    for rng in RANGES:
        if rng[0] <= flag < rng[1]:
            return rng
    return None


def is_local(flag: int) -> bool:
    return local_range(flag) is not None


def _check_area(area: int) -> None:
    if not 0 <= area < AREAS:
        raise ValueError(f"area {area} is outside 0..{AREAS - 1} (m01..m{AREAS:02d})")


def _ranges_text() -> str:
    return ' and '.join(f"{a}..{b - 1}" for a, b, _, _ in RANGES)


def _check_global(flag: int) -> None:
    capacity = BLOBS[PRIMARY][0]
    if is_local(flag):
        raise ValueError(f"flag {flag} is area-local ({_ranges_text()}); "
                         f"name its area, e.g. m02:{flag}")
    if not 0 <= flag < capacity:
        raise ValueError(f"flag {flag} is outside the flags (0..{capacity - 1})")


def _local_bit(area: int, flag: int) -> tuple[int, int]:
    """(bank key, bit) of local flag ``flag`` in ``area``'s slot."""
    _check_area(area)
    rng = local_range(flag)
    if rng is None:
        raise ValueError(f"flag {flag} is not area-local ({_ranges_text()})")
    first, _, bank, slot = rng
    return bank, area * slot + flag - first


def current_area(sf: des_save.SaveFile) -> int | None:
    """0-based area of the map the character is on (MAPUID's top byte - 1)."""
    field = sf.find(MAPUID)
    raw = getattr(field, 'raw', None) if field is not None else None
    if not raw or len(raw) != 4:
        return None
    area = raw[3] - 1
    return area if 0 <= area < AREAS else None


def parse_area(text: str) -> int:
    """``m02`` / ``2`` / ``m02_00_00_00`` -> 0-based area 1."""
    m = re.fullmatch(r'm?0*(\d{1,2})(?:_[\d_]*)?', text.strip().lower())
    if not m or not 1 <= int(m.group(1)) <= AREAS:
        raise ValueError(f"bad area {text!r} (expected m01..m{AREAS:02d})")
    return int(m.group(1)) - 1


def get_flag(sf: des_save.SaveFile, flag: int) -> bool:
    """A global flag (any id outside the local RANGES)."""
    _check_global(flag)
    return get(_blob_field(sf, PRIMARY).raw, flag)


def set_flag(sf: des_save.SaveFile, flag: int, value: bool) -> None:
    """Flip one global flag bit in place (same-size edit; the caller saves)."""
    _check_global(flag)
    field = _blob_field(sf, PRIMARY)
    field.raw = set_bit(field.raw, flag, value)


def get_local(sf: des_save.SaveFile, area: int, flag: int) -> bool:
    """Local flag ``flag`` of 0-based ``area``, read from its area slot."""
    bank, bit = _local_bit(area, flag)
    return get(_blob_field(sf, bank).raw, bit)


def set_local(sf: des_save.SaveFile, area: int, flag: int, value: bool,
              mirror: bool = True) -> None:
    """Set a local flag in its area slot, and in the primary copy when ``area``
    is the current one (``mirror=False`` skips that; only for experiments)."""
    bank_key, bit = _local_bit(area, flag)
    bank = _blob_field(sf, bank_key)
    bank.raw = set_bit(bank.raw, bit, value)
    if mirror and area == current_area(sf):
        primary = _blob_field(sf, PRIMARY)
        primary.raw = set_bit(primary.raw, flag, value)


def local_flags(sf: des_save.SaveFile, area: int) -> list[int]:
    """Set local flags of one area (from its slots), both ranges, in order."""
    _check_area(area)
    out = []
    for first, _, bank, slot in RANGES:
        field = sf.find(bank)
        if field is None:
            continue
        start = area * slot
        out += [first + f - start for f in iter_flags(field.raw)
                if start <= f < start + slot]
    return out


def global_flags(sf: des_save.SaveFile) -> list[int]:
    return [f for f in iter_flags(_blob_field(sf, PRIMARY).raw) if not is_local(f)]


def mirror_ok(sf: des_save.SaveFile) -> bool | None:
    """Whether the primary copies equal the current area's slots (None: unknown
    area or no blobs)."""
    area = current_area(sf)
    if area is None or sf.find(PRIMARY) is None:
        return None
    banks = [rng for rng in RANGES if sf.find(rng[2]) is not None]
    if not banks:
        return None
    primary = {f for f in iter_flags(sf.find(PRIMARY).raw)
               if any(a <= f < b for a, b, _, _ in banks)}
    return primary == set(local_flags(sf, area))


def sync_mirror(sf: des_save.SaveFile) -> bool:
    """Refill the primary blob's local ranges from the current area's slots
    (what the game does on load). Needed after moving a character to another
    map (MAPUID), or the old map's copy would be saved into the new map's slot.
    Returns whether anything changed."""
    area = current_area(sf)
    if area is None or sf.find(PRIMARY) is None:
        return False
    primary = _blob_field(sf, PRIMARY)
    raw = bytearray(primary.raw)
    for first, end, bank, _ in RANGES:
        if sf.find(bank) is None:
            continue
        for flag in range(first, end):
            raw[flag >> 3] &= ~(1 << (flag & 7)) & 0xFF
    for flag in local_flags(sf, area):
        raw[flag >> 3] |= 1 << (flag & 7)
    changed = bytes(raw) != primary.raw
    primary.raw = bytes(raw)
    return changed


def local_counts(sf: des_save.SaveFile) -> list[int] | None:
    """Set local flags per area (both ranges), or None without the banks."""
    if all(sf.find(bank) is None for _, _, bank, _ in RANGES):
        return None
    return [len(local_flags(sf, area)) for area in range(AREAS)]


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


def shop_counters(sf: des_save.SaveFile, db: FlagDB) -> list[dict]:
    """Each limited shop item's 8 flags read as one LSB-first byte. Observed:
    0 on items never touched, small counts after purchases (1 of 3 bought ->
    2 on one save), and 255 on some items of new characters; what the game
    counts is not confirmed (docs/research-event-flags.md)."""
    out = []
    for shop in db.doc.get('shops', []):
        value = sum(1 << n for n in range(shop.get('count', 8))
                    if get_flag(sf, shop['flag'] + n))
        out.append({"row": shop['row'], "item": shop.get('name') or shop['item'],
                    "stock": shop.get('stock'), "flag": shop['flag'], "value": value})
    return out


def npc_states(sf: des_save.SaveFile, db: FlagDB) -> list[dict]:
    """Every NPC state machine with the flags that are currently set."""
    out = []
    capacity = BLOBS[PRIMARY][0]
    for npc in db.npcs:
        states = [s['name'] for s in exclusive_states(npc) if get_flag(sf, s['id'])]
        backups = [s['name'] for s in npc['states']
                   if s['id'] + db.backup_offset < capacity
                   and get_flag(sf, s['id'] + db.backup_offset)]
        out.append({"list": npc['list'], "name": npc.get('name', npc['list']),
                    "set": states, "backup": backups})     # backup = previous state
    return out


# --------------------------------------------------------------------------- #
#  Recipes
# --------------------------------------------------------------------------- #
def exclusive_states(npc: dict) -> list[dict]:
    """The states of which exactly one is set; "marker" states (Thomas's
    "talked to you") sit beside them and are left alone."""
    return [s for s in npc['states'] if not s.get('marker')]


def respawn_boss(sf: des_save.SaveFile, db: FlagDB, name: str, full: bool = False) -> dict:
    """Make one boss alive again: clear its death flag and its soul-taken flag.

    The scripts re-evaluate everything on area load (the boss spawns while its
    death flag is clear, and the fog gate, boss-room collision and archstone
    state all key off the same flag), and the cleared soul flag lets the
    one-shot demon-soul pickup happen again.

    ``full`` also clears what the fight itself set: the boss's flag block
    (fog, cutscene and pickup flags its map script sets just above the death
    flag) and its boss-room local flags (``block``/``room`` in flagdb.json).
    The world counters (80xx: bosses killed per world) are left alone.
    """
    boss = db.find_boss(name)
    set_flag(sf, boss['id'], False)
    cleared = [boss['id']]
    if boss.get('soul') is not None:
        set_flag(sf, boss['soul'], False)
        cleared.append(boss['soul'])
    cleared_local = []
    if full:
        for flag in boss.get('block', []):
            if get_flag(sf, flag):
                set_flag(sf, flag, False)
                cleared.append(flag)
        area = boss['area'] - 1
        for flag in boss.get('room', []):
            if sf.find(_local_bit(area, flag)[0]) is not None and get_local(sf, area, flag):
                set_local(sf, area, flag, False)
                cleared_local.append(flag)
    return {"boss": boss['name'], "cleared": cleared, "area": boss['area'] - 1,
            "cleared_local": cleared_local}


def defeat_boss(sf: des_save.SaveFile, db: FlagDB, name: str,
                give_soul: bool = True) -> tuple[des_save.SaveFile, dict]:
    """Mark one boss defeated as a kill and soul pickup would; returns a new
    save (``sf`` is never modified) and what was done.

    Sets the death flag. With ``give_soul`` and the soul not yet taken, it also
    does what the boss's "Get Soul" handler does: adds its items to the
    inventory (the demon soul, plus e.g. Maiden Astrea's ring), sets the soul
    flag, and hands over each one-time extra whose flag is clear (the Nexial
    Agent, flag 17800). The fight's fog/cutscene flags, the world counters,
    the world tendency and ARCHSTONEHOMEINDEX are left alone. Any inventory
    problem raises before anything is returned.
    """
    import des_inventory
    boss = db.find_boss(name)
    if get_flag(sf, boss['id']):
        raise ValueError(f"{boss['name']} is already defeated")
    out = des_save.SaveFile(sf.build())
    done, items = [boss['id']], []

    def give(rows: list) -> None:
        nonlocal out
        for category, item_id, count, item_name in rows:
            out = des_inventory.with_added_item(out, category, item_id, quantity=count)
            items.append(f"{item_name} ×{count}" if count > 1 else item_name)

    soul = boss.get('soul')
    if give_soul and soul is not None and not get_flag(out, soul):
        give(boss.get('soul_items', []))
        set_flag(out, soul, True)
        done.append(soul)
        for extra in boss.get('bonus', []):
            if not get_flag(out, extra['flag']):
                give(extra['items'])
                set_flag(out, extra['flag'], True)
                done.append(extra['flag'])
    set_flag(out, boss['id'], True)
    return out, {"boss": boss['name'], "set": done, "items": items}


def forgivable(sf: des_save.SaveFile, db: FlagDB, npc: dict) -> dict | None:
    """The forgiveness entry that applies to ``npc`` now (its current state is
    a hostile state the game can forgive and a previous state is kept), else None."""
    states = [s['id'] for s in npc['states']]
    current = next((f for f in states if get_flag(sf, f)), 0)
    capacity = BLOBS[PRIMARY][0]
    kept = any(f + db.backup_offset < capacity and get_flag(sf, f + db.backup_offset)
               for f in states)
    for entry in db.forgiveness:
        if entry['list'] == npc['list'] and entry['id'] == current and kept:
            return entry
    return None


def forgive_npc(sf: des_save.SaveFile, db: FlagDB, name: str) -> dict:
    """What the game does when you seek forgiveness (SeekForgiveness /
    RestoreBackupNpcStateFlag in global_event.lua), for one NPC.

    For each of the NPC's entries in the forgiveness table, in order: if the
    current state (first set flag of the list) is that entry's hostile state,
    the first state whose +1000 twin is set becomes current again, the hostile
    state is cleared, the entry's area-local flags are cleared, and then every
    twin of the list is cleared.
    """
    npc = db.find_npc(name)
    entries = [e for e in db.forgiveness if e['list'] == npc['list']]
    if not entries:
        raise ValueError(f"{npc.get('name', npc['list'])} cannot be forgiven "
                         "(not in the game's forgiveness table)")
    states = [s['id'] for s in npc['states']]
    capacity = BLOBS[PRIMARY][0]
    restored, cleared_local = None, []
    for entry in entries:
        now = next((f for f in states if get_flag(sf, f)), 0)
        if now != entry['id']:
            continue
        for flag in states:
            twin = flag + db.backup_offset
            if twin < capacity and get_flag(sf, twin):
                set_flag(sf, flag, True)
                set_flag(sf, now, False)
                for area, flags in entry.get('reset', {}).items():
                    for local_flag in flags:
                        set_local(sf, int(area) - 1, local_flag, False)
                        cleared_local.append((int(area) - 1, local_flag))
                restored = flag
                break
        for flag in states:
            if flag + db.backup_offset < capacity:
                set_flag(sf, flag + db.backup_offset, False)
    return {"npc": npc.get('name', npc['list']), "restored": restored,
            "cleared_local": cleared_local}


def reset_map(sf: des_save.SaveFile, area: int) -> int:
    """Clear every local flag of one area (both ranges, and the primary copy
    when it is the current area): the map as on a new game. Returns the count."""
    flags = local_flags(sf, area)
    for flag in flags:
        set_local(sf, area, flag, False)
    return len(flags)


def rearm_pickups(sf: des_save.SaveFile, db: FlagDB, area: int) -> list[int]:
    """Clear the taken-flags of one area's map pickups so they can be picked
    up again. Returns the flags cleared."""
    _check_area(area)
    cleared = [f for f in db.pickups.get(area, []) if get_local(sf, area, f)]
    for flag in cleared:
        set_local(sf, area, flag, False)
    return cleared


def set_npc_state(sf: des_save.SaveFile, db: FlagDB, npc: str, state: str) -> dict:
    """Put one NPC into exactly one quest state, the way the game does.

    Mirrors the scripts' SetNpcStateFlag (global_event.lua): the current state
    is the first set flag in list order; on a change every +1000 "previous
    state" twin is cleared, the current state's twin is set (SeekForgiveness
    restores it if the NPC is later made hostile), the new state is set and the
    rest are cleared. Choosing the state an NPC is already in changes nothing.
    Marker states (see exclusive_states) are not touched.
    """
    npc_def = db.find_npc(npc)
    target = db.find_state(npc_def, state)
    ids = [s['id'] for s in exclusive_states(npc_def)]
    capacity = BLOBS[PRIMARY][0]
    current = [flag for flag in ids if get_flag(sf, flag)]
    previous = current[0] if current else None
    result = {"npc": npc_def['list'], "state": target['name'], "id": target['id'],
              "previous": previous}
    if current == [target['id']]:
        return result
    for flag in ids:
        if flag + db.backup_offset < capacity:
            set_flag(sf, flag + db.backup_offset, False)
    for flag in ids:
        set_flag(sf, flag, flag == target['id'])
    if previous is not None and previous != target['id'] \
            and previous + db.backup_offset < capacity:
        set_flag(sf, previous + db.backup_offset, True)
    return result


def parse_target(text: str) -> tuple[int | None, int]:
    """``4096`` -> (None, 4096); ``m02:200`` / ``2:200`` -> (1, 200)."""
    area_text, sep, flag_text = text.strip().rpartition(':')
    if not re.fullmatch(r'\d+', flag_text):
        raise ValueError(f"bad flag {text!r} (expected a number, e.g. 4096, "
                         "or AREA:ID for a local flag, e.g. m02:200)")
    return (parse_area(area_text) if sep else None), int(flag_text)
