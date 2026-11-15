"""World and character tendency (the game's internal name is QWC).

The game keeps two tendency axes, white/black (WB) and left/right (LR), for
the character and for each world, each clamped to -200..200 (negative is
black / left). Tendency-dependent content is gated by rows of the game's
``QwcJudge`` PARAM: a row gives an inclusive [under, top] range for character
WB, character LR, area WB and area LR, and the Lua scripts call
``proxy:IsSuccessQWC(<row>)`` to decide whether, say, a black phantom spawns.

Save layout, measured in Kyty (docs/research.md, "Tendency"):

* ``TENDENCY_PLAYER_BLACKWHITE`` is the character's white/black tendency
  (the Tendency menu shows it), ``TENDENCY_PLAYER_LEFTRIGHT`` its left/right
  axis (only spell purchases move it; it gates Nexus dialogue).
* ``TENDENCY_WORLD<slot>_LEFTRIGHT`` holds the world tendency the game uses
  and displays; on save the game copies it over ``_BLACKWHITE``. The editor
  therefore reads ``_LEFTRIGHT`` and writes the same value to both.
* Slot = remake map number - 1 (map m02 is Boletaria, slot 1).

This module is the single source for the tables; ``tools/embed_fields.py``
writes them into the page and ``tools/build_tendencydb.py --check`` verifies
the judge ranges and script call sites against the game files.
"""
from __future__ import annotations

LIMIT = 200

# slot -> world. Slot 0 (the Nexus) and slot 6 (no map) carry no world events.
WORLDS = [
    {"slot": 1, "key": "boletaria", "name": "Boletarian Palace", "map": "m02", "archstone": 1},
    {"slot": 5, "key": "stonefang", "name": "Stonefang Tunnel", "map": "m06", "archstone": 2},
    {"slot": 3, "key": "latria", "name": "Tower of Latria", "map": "m04", "archstone": 3},
    {"slot": 2, "key": "storms", "name": "Shrine of Storms", "map": "m03", "archstone": 4},
    {"slot": 4, "key": "valley", "name": "Valley of Defilement", "map": "m05", "archstone": 5},
]
EXTRA_SLOTS = {0: "Nexus (no world events)", 6: "Unused slot"}
SLOTS = 7
WORLD_BY_KEY = {w["key"]: w for w in WORLDS}
WORLD_BY_SLOT = {w["slot"]: w for w in WORLDS}
JUDGE_WORLD = {2: "boletaria", 3: "storms", 4: "latria", 5: "valley", 6: "stonefang"}  # judge // 10000

PLAYER_WB = "TENDENCY_PLAYER_BLACKWHITE"
PLAYER_LR = "TENDENCY_PLAYER_LEFTRIGHT"


def world_fields(slot: int) -> tuple[str, str]:
    """(value field the game uses, copy it rewrites on save)."""
    return f"TENDENCY_WORLD{slot:02d}_LEFTRIGHT", f"TENDENCY_WORLD{slot:02d}_BLACKWHITE"


# Bands follow the judge thresholds the scripts use: Pure Black <= -180,
# Black <= -100, Neutral -49..49, White >= 100, Pure White >= 180 (all inclusive).
# (upper bound, bound is inclusive, name); a value takes the first band it fits.
BANDS = [
    (-180, True, "Pure Black"), (-100, True, "Black"), (-49, False, "Leaning black"),
    (49, True, "Neutral"), (100, False, "Leaning white"), (180, False, "White"),
    (LIMIT, True, "Pure White"),
]
PRESETS = [("Pure Black", -200), ("Black", -120), ("Neutral", 0), ("White", 120), ("Pure White", 200)]
THRESHOLDS = [-180, -150, -100, -49, 49, 100, 150, 180]

# QwcJudge rows the scripts use, as stored in gameparam.parambnd:
# (pc WB under, pc WB top, pc LR under, pc LR top,
#  area WB under, area WB top, area LR under, area LR top)
JUDGES = {
    10100: (-200, 200, -200, -100, -200, 200, -200, 200),
    10200: (-200, 200, -200, -100, -200, 200, -200, 200),
    10300: (-200, 200, 100, 200, -200, 200, -200, 200),
    10400: (-200, 200, 100, 200, -200, 200, -200, 200),
    10500: (180, 200, -200, 200, -200, 200, -200, 200),
    10600: (-200, -180, -200, 200, -200, 200, -200, 200),
    20100: (-200, 200, -200, 200, -200, -100, -200, 200),
    20200: (-200, 200, -200, 200, -200, -150, -200, 200),
    20300: (-200, 200, -200, 200, -200, -180, -200, 200),
    20400: (-200, 200, -200, 200, 150, 200, -200, 200),
    20500: (-200, 200, -200, 200, 180, 200, -200, 200),
    20600: (-200, 200, -200, 200, 180, 200, -200, 200),
    30100: (-200, 200, -200, 200, -200, -100, -200, 200),
    30110: (-200, 200, -200, 200, -200, -150, -200, 200),
    30120: (-200, 200, -200, 200, -200, -180, -200, 200),
    30130: (-200, 200, -200, 200, 180, 200, -200, 200),
    30140: (-200, 200, -200, 200, 180, 200, -200, 200),
    40100: (-200, 200, -200, 200, -200, -100, -200, 200),
    40110: (-200, 200, -200, 200, -200, -150, -200, 200),
    40120: (-200, 200, -200, 200, -200, -180, -200, 200),
    40130: (-200, 200, -200, 200, 180, 200, -200, 200),
    40150: (-200, 200, -200, 200, 180, 200, -200, 200),
    40190: (-200, 200, -200, 200, -200, -180, -200, 200),
    50100: (-200, 200, -200, 200, -200, -100, -200, 200),
    50110: (-200, 200, -200, 200, -200, -150, -200, 200),
    50120: (-200, 200, -200, 200, -200, -180, -200, 200),
    50130: (-200, 200, -200, 200, 180, 200, -200, 200),
    50140: (-200, 200, -200, 200, 180, 200, -200, 200),
    50150: (-200, 200, -200, 200, 150, 200, -200, 200),
    60100: (-200, 200, -200, 200, -200, -100, -200, 200),
    60110: (-200, 200, -200, 200, -200, -150, -200, 200),
    60120: (-200, 200, -200, 200, -200, -180, -200, 200),
    60130: (-200, 200, -200, 200, 180, 200, -200, 200),
    60140: (-200, 200, -200, 200, 180, 200, -200, 200),
}

# What each judge controls, read from the call sites in
# cp11demonssouls/dvdroot/script (English comments are the game's machine
# translations). "effect" always describes the state while the condition
# holds. "sources" are the live (uncommented) IsSuccessQWC call sites.
# Map -> area: m02_00 1-1 ... m02_03 1-4, m06_00 2-1, m04_00 3-1, m03_01 4-1,
# m03_02 4-2, m03_03 4-3, m05_00 5-1 (from misc/dspointsofinterest.txt).
EVENTS = [
    # ---- character (checked in the Nexus) --------------------------------
    {"judge": 10600, "world": "character", "title": "Mephistopheles comes to the Nexus",
     "effect": "Once Yurt is dead, Mephistopheles moves to the Nexus stone pillar.",
     "areas": ["Nexus"], "sources": ["m01_00_00_00.lua:1296"]},
    {"judge": 10500, "world": "character", "title": "Nexus dialogue flag 8044",
     "effect": "Event flag 8044 is set for NPC conversations (Pure White character).",
     "areas": ["Nexus"], "sources": ["m01_00_00_00.lua:1745"]},
    {"judge": 10100, "world": "character", "title": "Nexus dialogue flags 8040 and 8041",
     "effect": "Event flags 8040 and 8041 are set for NPC conversations (left/right axis -100 or lower).",
     "areas": ["Nexus"], "sources": ["m01_00_00_00.lua:1717", "m01_00_00_00.lua:1724"], "also": [10200]},
    {"judge": 10300, "world": "character", "title": "Nexus dialogue flags 8042 and 8043",
     "effect": "Event flags 8042 and 8043 are set for NPC conversations (left/right axis 100 or higher).",
     "areas": ["Nexus"], "sources": ["m01_00_00_00.lua:1731", "m01_00_00_00.lua:1738"], "also": [10400]},
    # ---- Boletarian Palace ----------------------------------------------
    {"judge": 20600, "world": "boletaria", "title": "Execution-ground door opens (white)",
     "effect": "The door to the execution ground starts open.",
     "areas": ["1-1"], "sources": ["m02_00_00_00.lua:212"]},
    {"judge": 20500, "world": "boletaria", "title": "Executioner Miralda appears",
     "effect": "Miralda is present at the execution ground (until she dies).",
     "areas": ["1-1"], "sources": ["m02_00_00_00.lua:995"]},
    {"judge": 20400, "world": "boletaria", "title": "The dragon stops patrolling 1-1",
     "effect": "The flying dragon's 1-1 behaviour is disabled.",
     "areas": ["1-1"], "sources": ["m02_00_00_00.lua:311"]},
    {"judge": 20300, "world": "boletaria", "title": "Miralda black phantom; execution-ground door opens",
     "effect": "The execution-ground door starts open and Miralda appears as a hostile black phantom (until killed).",
     "areas": ["1-1"], "sources": ["m02_00_00_00.lua:213", "m02_00_00_00.lua:1043"]},
    {"judge": 20200, "world": "boletaria", "title": "Ore spirit in 1-3",
     "effect": "The ore spirit appears (until killed).",
     "areas": ["1-3"], "sources": ["m02_02_00_00.lua:1104"]},
    {"judge": 20100, "world": "boletaria", "title": "Soul monsters",
     "effect": "The scripts' tendency \"soul monsters\" appear (until killed).",
     "areas": ["1-1", "1-2", "1-3"],
     "sources": ["m02_00_00_00.lua:4621", "m02_01_00_00.lua:781", "m02_02_00_00.lua:1124"]},
    # ---- Stonefang Tunnel -----------------------------------------------
    {"judge": 60130, "world": "stonefang", "title": "Scirvir, the Wanderer appears",
     "effect": "Scirvir (\"Half-hand\" in the scripts) is present.",
     "areas": ["2-2"], "sources": ["m06_01_00_00.lua:521"]},
    {"judge": 60140, "world": "stonefang", "title": "\"Gram\" object hidden in 2-3",
     "effect": "Object 1433 (\"gram\" in the scripts) is not shown; its meaning is unverified.",
     "areas": ["2-3"], "sources": ["m06_02_00_00.lua:237"]},
    {"judge": 60120, "world": "stonefang", "title": "Scirvir black phantom",
     "effect": "Scirvir appears as a black phantom (until killed).",
     "areas": ["2-2"], "sources": ["m06_01_00_00.lua:555"]},
    {"judge": 60110, "world": "stonefang", "title": "Ore spirit in 2-1",
     "effect": "The ore spirit appears (until killed).",
     "areas": ["2-1"], "sources": ["m06_00_00_00.lua:681"]},
    {"judge": 60100, "world": "stonefang", "title": "Soul monsters",
     "effect": "The scripts' tendency \"soul monsters\" appear.",
     "areas": ["2-1", "2-2"], "sources": ["m06_00_00_00.lua:705", "m06_01_00_00.lua:506"]},
    # ---- Tower of Latria ------------------------------------------------
    {"judge": 40130, "world": "latria", "title": "Vileidel's cell is cleared",
     "effect": "The rubble blocking Vileidel is removed.",
     "areas": ["3-1"], "sources": ["m04_00_00_00.lua:1035"]},
    {"judge": 40150, "world": "latria", "title": "Iron plate stays in 3-2",
     "effect": "The iron plate (object 1210) is kept until you pass it; otherwise it is removed.",
     "areas": ["3-2"], "sources": ["m04_01_00_00.lua:576"]},
    {"judge": 40120, "world": "latria", "title": "Vileidel black phantom",
     "effect": "Vileidel (the NPC) is gone and his black phantom appears (until killed).",
     "areas": ["3-1"], "sources": ["m04_00_00_00.lua:1071", "m04_00_00_00.lua:1161"]},
    {"judge": 40190, "world": "latria", "title": "Sodden ring treasure",
     "effect": "Treasure 9919 replaces treasure 9920 (a remake addition; the code comment says \"Sodden ring\").",
     "areas": ["3-2"], "sources": ["m04_01_00_00.lua:788"]},
    {"judge": 40110, "world": "latria", "title": "Ore spirit in 3-2",
     "effect": "The ore spirit appears (until killed).",
     "areas": ["3-2"], "sources": ["m04_01_00_00.lua:617"]},
    {"judge": 40100, "world": "latria", "title": "Soul monsters",
     "effect": "The scripts' tendency \"soul monsters\" appear.",
     "areas": ["3-1", "3-2"], "sources": ["m04_00_00_00.lua:1189", "m04_01_00_00.lua:602"]},
    # ---- Shrine of Storms -----------------------------------------------
    {"judge": 30140, "world": "storms", "title": "Makoto on the ground",
     "effect": "The Makoto lies on the ground instead of in its usual place.",
     "areas": ["4-2"], "sources": ["m03_02_00_00.lua:1270"]},
    {"judge": 30130, "world": "storms", "title": "Master Satsuki leaves (white)",
     "effect": "The friendly Satsuki searching for his sword is absent; a Satsuki already turned hostile is restored hostile.",
     "areas": ["4-1"], "sources": ["m03_01_00_00.lua:588", "m03_01_00_00.lua:641"]},
    {"judge": 30120, "world": "storms", "title": "Satsuki black phantom",
     "effect": "The friendly Satsuki is absent and Satsuki appears as a black phantom (until killed).",
     "areas": ["4-1"], "sources": ["m03_01_00_00.lua:587", "m03_01_00_00.lua:692"]},
    {"judge": 30110, "world": "storms", "title": "Ore spirit in 4-2",
     "effect": "The ore spirit appears (until killed).",
     "areas": ["4-2"], "sources": ["m03_02_00_00.lua:523"]},
    {"judge": 30100, "world": "storms", "title": "Soul monsters and black phantoms",
     "effect": "The scripts' tendency \"soul monsters\" appear in 4-1 and three black phantoms in 4-2.",
     "areas": ["4-1", "4-2"], "sources": ["m03_01_00_00.lua:718", "m03_02_00_00.lua:1145"]},
    # ---- Valley of Defilement -------------------------------------------
    {"judge": 50130, "world": "valley", "title": "Selen Vinland appears",
     "effect": "Selen Vinland is present.",
     "areas": ["5-2"], "sources": ["m05_01_00_00.lua:381"]},
    {"judge": 50140, "world": "valley", "title": "Garl Vinland black phantom",
     "effect": "Garl Vinland appears as a black phantom before Maiden Astraea (until killed).",
     "areas": ["5-3"], "sources": ["m05_02_00_00_eventboss.lua:106"]},
    {"judge": 50150, "world": "valley", "title": "Ladder in 5-1",
     "effect": "The tendency ladder is available.",
     "areas": ["5-1"], "sources": ["m05_00_00_00.lua:410"]},
    {"judge": 50120, "world": "valley", "title": "Selen black phantom",
     "effect": "Selen appears as a black phantom (until killed).",
     "areas": ["5-2"], "sources": ["m05_01_00_00.lua:405"]},
    {"judge": 50110, "world": "valley", "title": "Ore spirit in 5-2",
     "effect": "The ore spirit appears (until killed).",
     "areas": ["5-2"], "sources": ["m05_01_00_00.lua:358"]},
    {"judge": 50100, "world": "valley", "title": "Soul monsters",
     "effect": "The scripts' tendency \"soul monsters\" appear.",
     "areas": ["5-1", "5-2"], "sources": ["m05_00_00_00.lua:744", "m05_01_00_00.lua:489"]},
]
EVENT_BY_JUDGE = {e["judge"]: e for e in EVENTS}

AXES = ("pc_wb", "pc_lr", "area_wb", "area_lr")


# ---------------------------------------------------------------- values
def clamp(value: float) -> float:
    return max(-LIMIT, min(LIMIT, value))


def band(value: float) -> str:
    for upper, inclusive, name in BANDS:
        if value < upper or (inclusive and value == upper):
            return name
    return BANDS[-1][2]


def read(sf) -> dict:
    """Character and per-world values; worlds whose fields are missing are None."""
    worlds = {}
    for slot in range(SLOTS):
        used, copy = world_fields(slot)
        value, mirror = sf.get(used), sf.get(copy)
        worlds[slot] = None if value is None else {"value": value, "copy": mirror}
    return {"pc_wb": sf.get(PLAYER_WB), "pc_lr": sf.get(PLAYER_LR), "worlds": worlds}


def ranges(judge: int) -> dict[str, tuple[float, float]]:
    row = JUDGES[judge]
    return {axis: (row[i * 2], row[i * 2 + 1]) for i, axis in enumerate(AXES)}


def event_world_slot(event: dict) -> int | None:
    world = WORLD_BY_KEY.get(event["world"])
    return world["slot"] if world else None


def judge_holds(judge: int, pc_wb: float, pc_lr: float, area: float | None) -> bool:
    """IsSuccessQWC: every axis inside its inclusive range. ``area`` is the
    world's tendency (both area axes hold it); None outside a world."""
    values = {"pc_wb": pc_wb, "pc_lr": pc_lr, "area_wb": area, "area_lr": area}
    for axis, (lo, hi) in ranges(judge).items():
        value = values[axis]
        if value is None:
            if (lo, hi) != (-LIMIT, LIMIT):
                return False
            continue
        if not lo <= value <= hi:
            return False
    return True


def event_active(event: dict, state: dict) -> bool:
    slot = event_world_slot(event)
    area = None
    if slot is not None:
        world = state["worlds"].get(slot)
        if world is None:
            return False
        area = world["value"]
    pc_wb = state["pc_wb"] if state["pc_wb"] is not None else 0.0
    pc_lr = state["pc_lr"] if state["pc_lr"] is not None else 0.0
    return all(judge_holds(j, pc_wb, pc_lr, area) for j in [event["judge"], *event.get("also", [])])


def active_events(state: dict) -> list[int]:
    return [e["judge"] for e in EVENTS if event_active(e, state)]


def requirement(event: dict) -> list[tuple[str, float, float]]:
    """The restricted axes of an event as (target, lo, hi); target is
    "character", "character_lr" or a world key."""
    out = []
    for judge in [event["judge"], *event.get("also", [])]:
        r = ranges(judge)
        if r["pc_wb"] != (-LIMIT, LIMIT):
            out.append(("character", *r["pc_wb"]))
        if r["pc_lr"] != (-LIMIT, LIMIT):
            out.append(("character_lr", *r["pc_lr"]))
        if r["area_wb"] != (-LIMIT, LIMIT):
            out.append((event["world"], *r["area_wb"]))
    return list(dict.fromkeys(out))


def describe_range(lo: float, hi: float) -> str:
    if lo == -LIMIT:
        return f"{hi:g} or lower"
    if hi == LIMIT:
        return f"{lo:g} or higher"
    return f"{lo:g} to {hi:g}"


# --------------------------------------------------------------- trigger
def current_value(state: dict, target: str) -> float:
    if target == "character":
        return state["pc_wb"] or 0.0
    if target == "character_lr":
        return state["pc_lr"] or 0.0
    world = state["worlds"].get(WORLD_BY_KEY[target]["slot"])
    return world["value"] if world else 0.0


def _nearest(value: float, lo: float, hi: float) -> float:
    """The value itself when inside, otherwise the nearest whole number at
    least 1 inside the range (the edge itself when it is the +-200 limit)."""
    if lo <= value <= hi:
        return value
    if value < lo:
        return lo if lo == -LIMIT else min(hi, lo + 1)
    return hi if hi == LIMIT else max(lo, hi - 1)


def trigger_targets(state: dict, judges: list[int]) -> dict:
    """Values that make every selected event hold.

    Returns {"targets": {target: value}, "conflicts": [str], "turns_on": [...],
    "turns_off": [...]}; with conflicts the targets are empty."""
    bounds: dict[str, list] = {}
    for judge in judges:
        event = EVENT_BY_JUDGE[judge]
        for target, lo, hi in requirement(event):
            entry = bounds.setdefault(target, [-LIMIT, LIMIT, []])
            entry[0], entry[1] = max(entry[0], lo), min(entry[1], hi)
            entry[2].append((event["title"], lo, hi))
    conflicts = []
    for target, (lo, hi, sources) in bounds.items():
        if lo > hi:
            names = "; ".join(f"{t} ({describe_range(a, b)})" for t, a, b in sources)
            conflicts.append(f"{target_label(target)}: no value satisfies {names}")
    if conflicts:
        return {"targets": {}, "conflicts": conflicts, "turns_on": [], "turns_off": []}
    targets = {}
    for target, (lo, hi, _) in bounds.items():
        value = _nearest(current_value(state, target), lo, hi)
        if value != current_value(state, target):
            targets[target] = value
    after = with_targets(state, targets)
    before_on, after_on = set(active_events(state)), set(active_events(after))
    return {"targets": targets, "conflicts": [],
            "turns_on": sorted(after_on - before_on - set(judges)),
            "turns_off": sorted(before_on - after_on)}


def target_label(target: str) -> str:
    if target == "character":
        return "Character tendency"
    if target == "character_lr":
        return "Character left/right axis"
    return WORLD_BY_KEY[target]["name"]


def with_targets(state: dict, targets: dict) -> dict:
    worlds = {slot: (dict(w) if w else None) for slot, w in state["worlds"].items()}
    out = {"pc_wb": state["pc_wb"], "pc_lr": state["pc_lr"], "worlds": worlds}
    for target, value in targets.items():
        if target == "character":
            out["pc_wb"] = value
        elif target == "character_lr":
            out["pc_lr"] = value
        else:
            slot = WORLD_BY_KEY[target]["slot"]
            if worlds.get(slot) is not None:
                worlds[slot]["value"] = worlds[slot]["copy"] = value
    return out


def parse_target(name: str) -> str:
    """CLI names: character, character_lr, a world key or a slot number."""
    key = name.strip().lower().replace("-", "_")
    if key in ("character", "character_lr") or key in WORLD_BY_KEY:
        return key
    aliases = {"char": "character", "player": "character", "pc": "character", "lr": "character_lr",
               "shrine": "storms", "boletarian": "boletaria", "tower": "latria"}
    if key in aliases:
        return aliases[key]
    if key.isdigit() and int(key) in WORLD_BY_SLOT:
        return WORLD_BY_SLOT[int(key)]["key"]
    raise ValueError(f"unknown tendency target {name!r} (use character, character_lr or "
                     + ", ".join(WORLD_BY_KEY) + ")")


def apply(sf, targets: dict) -> list[str]:
    """Write the targets into the save. A world writes its value field and
    the copy the game would rewrite, so both agree. Returns changed names."""
    changed = []
    for target, value in targets.items():
        value = clamp(float(value))
        if target == "character":
            names = [PLAYER_WB]
        elif target == "character_lr":
            names = [PLAYER_LR]
        else:
            names = list(world_fields(WORLD_BY_KEY[target]["slot"]))
        for name in names:
            if sf.find(name) is None:
                raise ValueError(f"{name} is not in this save")
            if sf.set(name, value):
                changed.append(name)
    return changed


def page_table() -> dict:
    """The JSON the page embeds (tools/embed_fields.py)."""
    return {"limit": LIMIT, "worlds": WORLDS, "extraSlots": {str(k): v for k, v in EXTRA_SLOTS.items()},
            "bands": BANDS, "presets": PRESETS, "thresholds": THRESHOLDS,
            "judges": {str(k): list(v) for k, v in JUDGES.items()}, "events": EVENTS,
            "judgeWorld": {str(k): v for k, v in JUDGE_WORLD.items()}}
