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
     "Starting class: archetype N is CharaInitParam row 1000+N (both samples, archetype 9, carry that row's exact base stats). Class names come from each row's starting weapon."),
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
    # ---- counts of indexed record families (structural; read-only in the page)
    ("EQUIPMENT_INVENTORY_COUNT", "int", "Inventory entries", 0, 100,
     "Number of EQUIPMENT_INVENTORY## entries. Structural: changing it alone corrupts the inventory."),
    ("EQUIPMENT_STORAGEBOX_COUNT", "int", "Storage box entries", 0, 100,
     "Number of EQUIPMENT_STORAGEBOX## entries. Structural: changing it alone does not add items."),
    ("DEADENEMIES_COUNT", "int", "Dead enemy indices", 0, 10_000,
     "Number of DEADENEMIES_INDICES#### records (enemies that stay dead)."),
    ("TROPHIES_RING_COUNT", "int", "Rings recorded for the trophy", 0, 100,
     "Number of TROPHIES_RING## records."),
    # ---- spells and tendency ---------------------------------------------
    ("SPELLS_SLOTSUNLOCKED", "int", "Spell slots unlocked", 0, 7, ""),
    ("MIRACLES_SLOTSUNLOCKED", "int", "Miracle slots unlocked", 0, 7, ""),
    ("TENDENCY_PLAYER_BLACKWHITE", "float", "Character tendency (black/white)", -1000, 1000,
     "Observed world tendency values range from -180 to 180."),
    ("TENDENCY_PLAYER_LEFTRIGHT", "float", "Character tendency (left/right)", -1000, 1000, ""),
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
    # Recovered by hashing strings from the game's executable and UI prefabs
    # (tools/build_keydb.py); types and values corroborate a setting.
    ("ADAPTIVETRIGGERS", "int", "Adaptive triggers", 0, 1, ""),
    ("AUTOEQUIPNEWITEMS", "int", "Auto-equip new items", 0, 1, ""),
    ("HUDBACKING", "int", "HUD backing", 0, 1, ""),
    ("SUBTITLEBACKING", "int", "Subtitle backing", 0, 1, ""),
    ("MIDNIGHTMODE", "int", "Midnight mode", 0, 1, "Reduced dynamic range audio."),
    ("RENDERCONFIG", "int", "Render configuration", 0, 8,
     "Graphics mode selection; value meaning not verified."),
    ("MAPUID", "hex", "Map UID", 0, 0xFFFFFFFF, "4 raw bytes; meaning not verified."),
]
# Rejected hash matches: PLAYER_STARTINGGIFT and PLAYER_VOICETYPE match two
# container keys, but the containers' children (archstone and blob state) do
# not corroborate those names.

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
    "Progress flags": ["WORLDSTATUS_MIRRORMODE", "MISC_HASUNLOCKEDNEXUSSTATUE"],
    "Spells and tendency": [
        "SPELLS_SLOTSUNLOCKED", "MIRACLES_SLOTSUNLOCKED",
        "TENDENCY_PLAYER_BLACKWHITE", "TENDENCY_PLAYER_LEFTRIGHT",
    ],
    "Counts (read-only)": [
        "EQUIPMENT_INVENTORY_COUNT", "EQUIPMENT_STORAGEBOX_COUNT",
        "DEADENEMIES_COUNT", "TROPHIES_RING_COUNT",
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
        "PASSWORD", "ADAPTIVETRIGGERS", "AUTOEQUIPNEWITEMS", "HUDBACKING",
        "SUBTITLEBACKING", "MIDNIGHTMODE", "RENDERCONFIG", "MAPUID",
    ],
}

# Indexed record families, named by printf templates in the game executable
# (e.g. "Equipment_Inventory%02d_EquipId"). Each expands to one key per index.
# (template, highest index) - the bound covers every index the format can
# print with its width, not a verified game limit.
FAMILIES = [
    ("DEADENEMIES_INDICES%04d", 9999),
    ("EQUIPMENT_EQUIPITEM%02d", 99),
    *[(f"EQUIPMENT_INVENTORY%02d_{part}", 99) for part in (
        "DISPLAYID", "DURABILITY_ACCUMULATEDHITS", "DURABILITY_CURRENT",
        "EQUIPID", "INDEX", "QUANTITY", "TYPE", "VARIATIONID")],
    ("EQUIPMENT_SLOT%02d_EQUIPMENTID", 99),
    ("EQUIPMENT_SLOT%02d_INVENTORYID", 99),
    *[(f"EQUIPMENT_STORAGEBOX%02d_{part}", 99) for part in (
        "DISPLAYID", "DURABILITY", "DURABILITY_ACCUMULATEDHITS", "EQUIPTYPEID",
        "HIGHQUANTITY", "LOWQUANTITY")],
    ("MIRACLES_EQUIPPED%02d", 99),
    ("SPELLS_EQUIPPED%02d", 99),
    ("TENDENCY_WORLD%02d_BLACKWHITE", 99),
    ("TENDENCY_WORLD%02d_LEFTRIGHT", 99),
    ("TROPHIES_RING%02d", 99),
    ("CCSLOT_ANIMTYPE_%02d", 99),
    ("CCSLOT_FACEDATA_%02d", 99),
    ("CCSLOT_GENDER_%02d", 99),
    ("CCSLOT_VOICETYPE_%02d", 99),
]
FAMILY_KEYS: dict[int, str] = {
    name_key(template % index): template % index
    for template, last in FAMILIES for index in range(last + 1)}

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
WORLD_NAMES: list[str] = [
    "BOSS_LOOT_VISIBLE", "BROKEN", "FADEDOUT", "SCORCHEDBLENDVALUE",
    "TRANSFORM", "TRANSFORMS", "TRANSFORMCOUNT", "DISABLEDBONEMASK",
    "DISABLEDCONSTRAINTMASK", "FROZENBONEMASK", "SCALEDBONEMASK",
    "M03_01_SEC01_LIGHTNING_SAVE", "M06_00_LAVA_VFX_SAVE",
    "M06_00_WATERWHEEL_VFX_SAVE", "MAIDENBLACK_STAFF_FIRE_OFF",
    "O2110_0000_CHAINS_BOL_SAVE", "O2110_0001_CHAINS_BOL_SAVE",
    "O2320_FX_ENABLED", "SCN000006_STATUESWORDRELEASE_SAVE",
]
WORLD_KEYS: dict[int, str] = {name_key(name): name for name in WORLD_NAMES}


def world_name(key: int) -> str | None:
    return WORLD_KEYS.get(key)


def lookup(key: int) -> dict | None:
    return FIELDS.get(key)


def field_name(key: int) -> str | None:
    meta = FIELDS.get(key)
    return meta["name"] if meta else FAMILY_KEYS.get(key)


def describe(key: int) -> str:
    """The recovered name when known, otherwise just the hex key."""
    return field_name(key) or f"{key:08X}"


def known_names() -> list[str]:
    return sorted(BY_NAME)
