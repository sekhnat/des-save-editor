"""
Known Demon's Souls (PS5) save fields.

Every key in the save file is FNV-1a 32 of the field name in UPPERCASE,
so a field is "known" once its name has been recovered::

    fnv1a("PLAYER_SOULS") == 0x76FD62AF   ->  the souls field

This module is the single source of field metadata. The CLI reads it directly
and ``tools/embed_fields.py`` writes the same table into ``des_editor.html``.
"""

from des_save import name_key

ATTRS = ["VITALITY", "INTELLIGENCE", "ENDURANCE", "STRENGTH",
         "DEXTERITY", "MAGIC", "FAITH", "LUCK"]

# (name, kind, label, lo, hi, help)
#   kind: "int" | "float" | "text" | "hex"
#   label: short UI label; help: longer explanation, may be empty
_DEFS = [
    # ---- character -------------------------------------------------------
    ("PLAYER_NAME", "text", "Character name", 0, 16,
     "The name shown on the character select screen (16 characters in game)."),
    ("PLAYER_ARCHETYPE", "int", "Class / archetype id", 0, 9,
     "Numeric archetype. The class-name mapping has not been verified; preserve it unless you know the correct id."),
    ("PLAYER_ISMALE", "int", "Gender (isMale)", 0, 1,
     "Gender flag as the game names it."),
    ("ARCHSTONEHOMEINDEX", "int", "Home archstone", 0, 20,
     "Archstone the character returns to."),
    ("PLAYER_NUMBER", "int", "Character slot", 0, 20, "Index of this character."),
    # ---- souls -----------------------------------------------------------
    ("PLAYER_SOULS", "int", "Souls", 0, 999_999_999, "Souls currently carried."),
    ("PLAYER_CUMULATIVESOULS", "int", "Souls (lifetime)", 0, 2_000_000_000,
     "Total souls ever collected with this character."),
    # ---- attributes ------------------------------------------------------
    *[(f"PLAYER_CURRENT{a}", "int", a.capitalize(), 1, 99,
       "Attribute value used by the level-up screen.") for a in ATTRS],
    *[(f"PLAYER_BASE{a}", "int", f"{a.capitalize()} (base)", 1, 99,
       "Stored base value of the same attribute.") for a in ATTRS],
    # ---- vitals ----------------------------------------------------------
    ("PLAYER_CURRENTHP", "int", "HP (current)", 0, 100_000, ""),
    ("PLAYER_CURRENTMAXHP", "int", "HP (max, effective)", 0, 100_000,
     "Max HP the game shows — reduced in soul form."),
    ("PLAYER_BASEMAXHP", "int", "HP (body form max)", 0, 100_000,
     "Body-form maximum, derived from Vitality."),
    ("PLAYER_CURRENTMP", "int", "MP (current)", 0, 100_000, ""),
    ("PLAYER_CURRENTMAXMP", "int", "MP (max, effective)", 0, 100_000, ""),
    ("PLAYER_BASEMAXMP", "int", "MP (base)", 0, 100_000, "Derived from Intelligence."),
    ("PLAYER_CURRENTSP", "int", "Stamina (current)", 0, 100_000, ""),
    ("PLAYER_CURRENTMAXSP", "int", "Stamina (max, effective)", 0, 100_000, ""),
    ("PLAYER_BASEMAXSP", "int", "Stamina (max)", 0, 100_000, ""),
    ("PLAYER_RECOVERMP", "int", "MP recovery", 0, 100_000, "Regeneration bonus."),
    ("PLAYER_RECOVERSP", "int", "Stamina recovery", 0, 100_000, "Regeneration bonus."),
    # ---- resistance ------------------------------------------------------
    ("PLAYER_RESISTANCE_POISON", "int", "Poison resistance", 0, 100_000, ""),
    ("PLAYER_RESISTANCE_PLAGUE", "int", "Plague resistance", 0, 100_000, ""),
    # ---- records / progress ---------------------------------------------
    ("PLAYTIME", "float", "Play time (ms)", 0, 1e12,
     "Milliseconds. 3 600 000 = one hour."),
    ("TRUEDEATHCOUNT", "int", "Deaths", 0, 1_000_000, ""),
    ("DEMONSKILLED", "int", "Demons killed", 0, 1_000_000, ""),
    ("CLEARSTATE", "int", "Clear state", 0, 1_000, ""),
    ("CLEARCOUNT", "int", "Clear count", 0, 1_000,
     "Number of finished playthroughs (NG+ level)."),
    ("KILLBLACK", "int", "Black phantom kills", 0, 1_000_000, ""),
    # ---- progress flags ---------------------------------------------------
    ("WORLDSTATUS_MIRRORMODE", "int", "Mirror mode", 0, 1, ""),
    ("MISC_HASUNLOCKEDNEXUSSTATUE", "int", "Nexus statue unlocked", 0, 1, ""),
    ("EQUIPMENT_STORAGEBOX_COUNT", "int", "Storage box count (read-only)", 0, 100_000,
     "Counter only. Contents and their relationship to this counter have not been decoded; changing the counter alone is unsafe."),
    # ---- advanced / not fully verified -----------------------------------
    ("PLAYER_SHOPLEVEL", "int", "Shop level (unverified)", 0, 10_000,
     "Hash name recovered, but the meaning of the value is not confirmed."),
    ("PLAYER_CLEARITEM", "int", "Clear item flag", 0, 255, ""),
    ("PLAYER_CLEARBONUS", "float", "Clear bonus", -1e9, 1e9, ""),
    ("PLAYEROFFSET", "int", "Player record offset (unverified)", -1, 1_000_000,
     "Recovered field name; value meaning is unverified."),
    # ---- options profile -------------------------------------------------
    ("BRIGHTNESS", "int", "Brightness", 0, 100, ""),
    ("DISPLAYBRIGHTNESS", "float", "Display brightness", 0, 2, ""),
    ("VOLUMEMUSIC", "float", "Music volume", 0, 1, ""),
    ("VOLUMEEFFECTS", "float", "Effects volume", 0, 1, ""),
    ("VOLUMEVOICE", "float", "Voice volume", 0, 1, ""),
    ("SUBTITLES", "int", "Subtitles", 0, 1, ""),
    ("SHOWHELMET", "int", "Show helmet", 0, 1, ""),
    ("GAMEFILTERNAME", "hex", "Colour filter", 0, 0xFFFFFFFF, "4 raw bytes."),
    ("CAMERASPEED", "int", "Camera speed", 0, 10, ""),
    ("CAMERAMODE", "int", "Camera mode", 0, 1, ""),
    ("CAMERASHAKE", "float", "Camera shake", 0, 2, "Camera shake strength."),
    ("AUTOLOCK", "int", "Camera auto-lock", 0, 1, ""),
    ("SOUNDTYPE", "int", "Sound output", 0, 8, ""),
    ("COLORBLIND", "int", "Colour-blind filter", 0, 8, ""),
    ("PASSWORD", "text", "Network password", 0, 8, ""),
]

# category -> ordered list of field names (the editor and `list` layout)
LAYOUT = {
    "Character": [
        "PLAYER_NAME", "PLAYER_ISMALE", "PLAYER_ARCHETYPE", "PLAYER_NUMBER",
        "ARCHSTONEHOMEINDEX",
    ],
    "Souls": ["PLAYER_SOULS", "PLAYER_CUMULATIVESOULS"],
    "Attributes": [f"PLAYER_CURRENT{a}" for a in ATTRS],
    "Attributes (base)": [f"PLAYER_BASE{a}" for a in ATTRS],
    "Vitals": [
        "PLAYER_CURRENTHP", "PLAYER_CURRENTMAXHP", "PLAYER_BASEMAXHP",
        "PLAYER_CURRENTMP", "PLAYER_CURRENTMAXMP", "PLAYER_BASEMAXMP",
        "PLAYER_CURRENTSP", "PLAYER_CURRENTMAXSP", "PLAYER_BASEMAXSP",
        "PLAYER_RECOVERMP", "PLAYER_RECOVERSP",
    ],
    "Progress flags": [
        "WORLDSTATUS_MIRRORMODE", "MISC_HASUNLOCKEDNEXUSSTATUE",
        "EQUIPMENT_STORAGEBOX_COUNT",
    ],
    "Resistance": ["PLAYER_RESISTANCE_POISON", "PLAYER_RESISTANCE_PLAGUE"],
    "Records": [
        "PLAYTIME", "TRUEDEATHCOUNT", "DEMONSKILLED", "CLEARSTATE",
        "CLEARCOUNT", "KILLBLACK",
    ],
    "Advanced (unverified)": [
        "PLAYER_SHOPLEVEL", "PLAYER_CLEARITEM", "PLAYER_CLEARBONUS", "PLAYEROFFSET",
    ],
    "Options": [
        "BRIGHTNESS", "DISPLAYBRIGHTNESS", "VOLUMEMUSIC", "VOLUMEEFFECTS",
        "VOLUMEVOICE", "SUBTITLES", "SHOWHELMET", "CAMERASPEED", "CAMERAMODE",
        "CAMERASHAKE", "AUTOLOCK", "SOUNDTYPE", "COLORBLIND", "GAMEFILTERNAME",
        "PASSWORD",
    ],
}

FIELDS: dict[int, dict] = {}
for _name, _kind, _label, _lo, _hi, _help in _DEFS:
    FIELDS[name_key(_name)] = {
        "name": _name, "kind": _kind, "label": _label, "help": _help,
        "desc": f"{_label} — {_help}" if _help else _label,
        "lo": _lo, "hi": _hi,
    }

# name (any case) -> metadata, for the CLI
BY_NAME = {v["name"]: v for v in FIELDS.values()}


# Keys that occur inside world-state entries (see des_world.py), not at the
# top level of the save. key -> name.
WORLD_NAMES: list[str] = []
WORLD_KEYS: dict[int, str] = {name_key(name): name for name in WORLD_NAMES}


def world_name(key: int) -> str | None:
    return WORLD_KEYS.get(key)


def lookup(key: int) -> dict | None:
    return FIELDS.get(key)


def field_name(key: int) -> str | None:
    meta = FIELDS.get(key)
    return meta["name"] if meta else None


def describe(key: int) -> str:
    """The recovered name when known, otherwise just the hex key."""
    meta = FIELDS.get(key)
    if not meta:
        return f"{key:08X}"
    return f'{meta["name"]}'


def known_names() -> list[str]:
    return sorted(BY_NAME)
