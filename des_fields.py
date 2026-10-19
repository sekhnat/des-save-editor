"""
Known Demon's Souls (PS5) save fields.

Every key in the save file is FNV-1a 32 of the field name in UPPERCASE,
so a field is "known" once its name has been recovered::

    fnv1a("PLAYER_SOULS") == 0x76FD62AF   ->  the souls field

`FIELDS` maps the 32-bit key to presentation metadata used by both the
CLI and the HTML editor.
"""

from des_save import name_key

ATTRS = ["VITALITY", "INTELLIGENCE", "ENDURANCE", "STRENGTH",
         "DEXTERITY", "MAGIC", "FAITH", "LUCK"]

# category -> ordered list of field names (used for the editor layout)
LAYOUT = {
    "Character": [
        "PLAYER_NAME", "PLAYER_ISMALE", "PLAYER_ARCHETYPE", "PLAYER_NUMBER",
        "ARCHSTONEHOMEINDEX",
    ],
    "Souls": [
        "PLAYER_SOULS", "PLAYER_CUMULATIVESOULS",
    ],
    "Attributes": [f"PLAYER_CURRENT{a}" for a in ATTRS],
    "Base attributes": [f"PLAYER_BASE{a}" for a in ATTRS],
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
    "Resistance": [
        "PLAYER_RESISTANCE_POISON", "PLAYER_RESISTANCE_PLAGUE",
    ],
    "Records": [
        "PLAYTIME", "TRUEDEATHCOUNT", "DEMONSKILLED", "CLEARSTATE",
        "CLEARCOUNT", "KILLBLACK",
    ],
    "Options": [
        "BRIGHTNESS", "DISPLAYBRIGHTNESS", "VOLUMEMUSIC", "VOLUMEEFFECTS",
        "VOLUMEVOICE", "SUBTITLES", "SHOWHELMET", "CAMERASPEED", "CAMERAMODE",
        "SOUNDTYPE", "COLORBLIND", "GAMEFILTERNAME", "PASSWORD",
        "AUTOLOCK", "CAMERASHAKE",
    ],
}

# name -> (kind, description, lo, hi)
#   kind: "int" | "float" | "text" | "hex"
_DEFS = [
    # ---- character -------------------------------------------------------
    ("PLAYER_NAME", "text", "Character name (max 16 characters in game)", 0, 16),
    ("PLAYER_ARCHETYPE", "int", "Numeric archetype id (class-name mapping unverified)", 0, 9),
    ("PLAYER_NUMBER", "int", "Character slot number", 0, 20),
    ("PLAYER_ISMALE", "int", "Gender flag (isMale): 0 or 1", 0, 1),
    ("ARCHSTONEHOMEINDEX", "int", "Home archstone index (where you respawn)", 0, 20),
    # ---- souls -----------------------------------------------------------
    ("PLAYER_SOULS", "int", "Souls currently carried", 0, 999_999_999),
    ("PLAYER_CUMULATIVESOULS", "int", "Total souls collected over the character's life", 0, 2_000_000_000),
    # ---- attributes ------------------------------------------------------
    ("PLAYER_CURRENTVITALITY", "int", "Vitality (level-up screen value)", 1, 99),
    ("PLAYER_CURRENTINTELLIGENCE", "int", "Intelligence", 1, 99),
    ("PLAYER_CURRENTENDURANCE", "int", "Endurance", 1, 99),
    ("PLAYER_CURRENTSTRENGTH", "int", "Strength", 1, 99),
    ("PLAYER_CURRENTDEXTERITY", "int", "Dexterity", 1, 99),
    ("PLAYER_CURRENTMAGIC", "int", "Magic", 1, 99),
    ("PLAYER_CURRENTFAITH", "int", "Faith", 1, 99),
    ("PLAYER_CURRENTLUCK", "int", "Luck", 1, 99),
    ("PLAYER_BASEVITALITY", "int", "Vitality (base value stored with the character)", 1, 99),
    ("PLAYER_BASEINTELLIGENCE", "int", "Intelligence (base)", 1, 99),
    ("PLAYER_BASEENDURANCE", "int", "Endurance (base)", 1, 99),
    ("PLAYER_BASESTRENGTH", "int", "Strength (base)", 1, 99),
    ("PLAYER_BASEDEXTERITY", "int", "Dexterity (base)", 1, 99),
    ("PLAYER_BASEMAGIC", "int", "Magic (base)", 1, 99),
    ("PLAYER_BASEFAITH", "int", "Faith (base)", 1, 99),
    ("PLAYER_BASELUCK", "int", "Luck (base)", 1, 99),
    # ---- vitals ----------------------------------------------------------
    ("PLAYER_CURRENTHP", "int", "Current HP", 0, 100_000),
    ("PLAYER_CURRENTMAXHP", "int", "Max HP (effective, soul-form adjusted)", 0, 100_000),
    ("PLAYER_BASEMAXHP", "int", "Max HP (body form)", 0, 100_000),
    ("PLAYER_CURRENTMP", "int", "Current MP", 0, 100_000),
    ("PLAYER_CURRENTMAXMP", "int", "Max MP (effective)", 0, 100_000),
    ("PLAYER_BASEMAXMP", "int", "Max MP (body form)", 0, 100_000),
    ("PLAYER_CURRENTSP", "int", "Current stamina", 0, 100_000),
    ("PLAYER_CURRENTMAXSP", "int", "Max stamina (effective)", 0, 100_000),
    ("PLAYER_BASEMAXSP", "int", "Max stamina", 0, 100_000),
    ("PLAYER_RECOVERMP", "int", "MP regeneration bonus", 0, 100_000),
    ("PLAYER_RECOVERSP", "int", "Stamina regeneration bonus", 0, 100_000),
    # ---- resistance ------------------------------------------------------
    ("PLAYER_RESISTANCE_POISON", "int", "Poison resistance", 0, 100_000),
    ("PLAYER_RESISTANCE_PLAGUE", "int", "Plague resistance", 0, 100_000),
    # ---- records / progress ---------------------------------------------
    ("PLAYTIME", "float", "Total play time in milliseconds", 0, 1e12),
    ("TRUEDEATHCOUNT", "int", "Number of deaths", 0, 1_000_000),
    ("DEMONSKILLED", "int", "Demons killed", 0, 1_000_000),
    ("CLEARSTATE", "int", "Clear / completion state", 0, 1_000),
    ("CLEARCOUNT", "int", "Clear count (playthroughs finished)", 0, 1_000),
    ("KILLBLACK", "int", "Black phantom kills", 0, 1_000_000),
    # ---- progress flags ---------------------------------------------------
    ("WORLDSTATUS_MIRRORMODE", "int", "Mirror-mode world flag", 0, 1),
    ("MISC_HASUNLOCKEDNEXUSSTATUE", "int", "Nexus statue unlocked", 0, 1),
    ("EQUIPMENT_STORAGEBOX_COUNT", "int", "Items stored in the storage box", 0, 100_000),
    # ---- advanced / not fully verified -----------------------------------
    ("PLAYER_SHOPLEVEL", "int", "Shop level (name verified, meaning unclear)", 0, 10_000),
    ("PLAYER_CLEARITEM", "int", "Clear item flag", 0, 255),
    ("PLAYER_CLEARBONUS", "float", "Clear bonus", -1e9, 1e9),
    ("PLAYEROFFSET", "int", "Player record offset", -1, 1_000_000),
    # ---- options profile -------------------------------------------------
    ("BRIGHTNESS", "int", "Brightness", 0, 100),
    ("DISPLAYBRIGHTNESS", "float", "Display brightness", 0, 2),
    ("VOLUMEMUSIC", "float", "Music volume", 0, 1),
    ("VOLUMEEFFECTS", "float", "Effects volume", 0, 1),
    ("VOLUMEVOICE", "float", "Voice volume", 0, 1),
    ("SUBTITLES", "int", "Subtitles enabled", 0, 1),
    ("SHOWHELMET", "int", "Show helmet", 0, 1),
    ("GAMEFILTERNAME", "hex", "Colour filter (4 bytes)", 0, 0xFFFFFFFF),
    ("CAMERASPEED", "int", "Camera speed", 0, 10),
    ("CAMERAMODE", "int", "Camera mode", 0, 1),
    ("CAMERASHAKE", "float", "Camera shake strength", 0, 2),
    ("AUTOLOCK", "int", "Camera auto-lock", 0, 1),
    ("SOUNDTYPE", "int", "Sound output type", 0, 8),
    ("COLORBLIND", "int", "Colour-blind filter", 0, 8),
    ("PASSWORD", "text", "Network password", 0, 8),
]

FIELDS: dict[int, dict] = {}
for _name, _kind, _desc, _lo, _hi in _DEFS:
    FIELDS[name_key(_name)] = {
        "name": _name, "kind": _kind, "desc": _desc,
        "lo": _lo, "hi": _hi,
    }

# name (any case) -> metadata, for the CLI
BY_NAME = {v["name"]: v for v in FIELDS.values()}


def lookup(key: int) -> dict | None:
    return FIELDS.get(key)


def field_name(key: int) -> str | None:
    meta = FIELDS.get(key)
    return meta["name"] if meta else None


def describe(key: int) -> str:
    """`NAME (description)` when known, otherwise just the hex key."""
    meta = FIELDS.get(key)
    if not meta:
        return f"{key:08X}"
    return f'{meta["name"]}'


LAYOUT["Advanced"] = ["PLAYER_SHOPLEVEL", "PLAYER_CLEARITEM",
                      "PLAYER_CLEARBONUS", "PLAYEROFFSET"]


def known_names() -> list[str]:
    return sorted(BY_NAME)
