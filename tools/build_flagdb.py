#!/usr/bin/env python3
"""Build the event-flag database: flag ID -> meaning, from the game's own scripts.

The event system (see docs/research-event-flags.md) numbers its flags, and the
scripts themselves say what most of them mean:

* ``event_define.lua`` lists every NPC's quest-state flags with comments, and
  defines ``NPC_STATE_BACKUP_OFFSET`` (each list's +1000 twin holds the previous state).
* ``global_event.lua``'s ``GetBossFlagCount`` holds the authoritative table of
  boss-death flags, grouped by world with comments (King's Castle, Jail, ...).
* every map script documents its own events as ``--■ 123 ■ description``
  (machine-translated), next to the ``SetEventFlag``/``IsCompleteEvent`` calls
  that read and write them.
* ``IsSuccessQWC`` (tendency) call sites sit next to the event flags they gate
  (Miralda's removal, the execution-ground door, ...); those pairs are what the
  Tendency view needs to finish the tendency feature.

Flags below ``LOCAL_SIZE`` (3200) are area-local: each map has its own set,
stored in the save's per-area bank (see des_flags.py), so the same number means
different things in different map scripts. Their descriptions are kept per map
(``local``); flags from 3200 up are one save-wide numbering (``global``).
Local numbers documented only by non-map scripts (global_event.lua, test maps)
go to ``scripts``: they act on whichever area is loaded.

The game's parameter tables name two more groups of global flags:
``SHOP_LINEUP_PARAM.eventFlag`` (an 8-flag group per limited shop item) and
``ITEMLOT_PARAM_ST.eventId`` (one-time drops).

Output ``flagdb.json``: ``areas`` (area id -> name/map), ``npcs`` (state
machines with display names), ``bosses`` (death flags with names), ``local``
(area -> per-map flag descriptions), ``global``, ``scripts``, ``pickups``
(area -> treasure flag -> level and items), ``shops``, ``itemlots`` and ``tendency_pairs`` (judge -> flags). The CLI and the page use
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
sys.path.insert(0, str(HERE / 'src'))
import des_gamedata  # noqa: E402
import des_msb  # noqa: E402
import build_entitydb  # noqa: E402  (level labels: m02_01 -> "Boletaria 1-2")

LOCAL_SIZE = 3200        # flags below this are per area (des_flags.LOCAL_SIZE)
# the two area-local ranges (des_flags.RANGES): each map has its own copy
LOCAL_RANGES = ((0, LOCAL_SIZE), (8192, 8192 + 4096))
FLAG_CAPACITY = 18048    # bits of the primary blob


def is_local(flag: int) -> bool:
    return any(a <= flag < b for a, b in LOCAL_RANGES)


# Label sources, best first. A flag's "descs" keep this order and its "kind"
# names the source of the first one (the page dims "usage" labels: they say
# how the scripts use a flag, not what it means in the game).
KINDS = ("curated", "pickup", "comment", "talk", "conversation", "placed", "usage")

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
# In-game identity and plain-English states for every NPC state list in
# event_define.lua. Names are the game's own (text/ds/_cmn/npc_name.*.ctxt);
# identities come from the scripts and dialogue (talk_msg.*.ctxt):
#   rogarn = Sage Freke ("I am Freke. I have been trapped here for an age."),
#   magic_student = Freke's Apprentice ("please free Sage Freke ... in Latria"),
#   syuujin = Graverobber Blige ("You saved me ... I'm Blige", Shrine of Storms),
#   half ("Half-Hand") = Scirvir (tendency judge 60130), viraidel = Rydell
#   ("a keepsake of my late wife"), yojin (要人) = the Monumental.
# The scripts call the Nexus the "stone pillar" (石柱), Boletaria "King's
# Castle" (王城), Latria the "prison castle" (牢城), the Shrine of Storms the
# "old fort" (古砦) and Stonefang the "tunnel" (坑道).
# group orders the Events tab; "marker" states sit beside the main state
# instead of replacing it, so the state picker leaves them alone.
NPC_INFO = {
    "heroine": ("Maiden in Black", "Nexus", "Levels you up in the Nexus.", {
        "WAIT_FOR_PLAYER": "In the Nexus, levels you up (normal)",
        "WANT_TO_SETTLE": "Every world's demons slain: ready to lead you to the Old One",
        "WITH_A_FUTURE": "Leading you to the Old One",
        "DOOR_FRONT": "Standing at the door",
        "DOOR_LEAVE": "Leaving the door",
        "PRAYER": "Praying",
        "ISNOT": "Not active yet (becomes normal after your first demon kill)",
    }),
    "yojin": ("Monumental", "Nexus", "The Monumental at the top of the Nexus; cannot be harmed.", {
        "WAIT_FOR_PLAYER": "Waiting in the Nexus (normal)",
        "LASTWORD": "Has his last words for you (every world cleared)",
        "DEAD": "Dead",
    }),
    "baldwin": ("Blacksmith Boldwin", "Nexus", "The Nexus blacksmith.", {
        "WORK": "Working: upgrades and repairs (normal)",
        "HOSTILE": "Hostile (you attacked him)",
        "DEAD": "Dead",
        "ISNOT": "Not in the Nexus yet",
    }),
    "tomasu": ("Stockpile Thomas", "Nexus", "Keeps your item storage in the Nexus.", {
        "WAIT": "Keeps your storage (normal)",
        "ANGRY": "Hostile (you attacked him)",
        "DEAD": "Dead",
        "ISNOT": "Not in the Nexus yet",
        "ACTIVE": ("Has talked to you", True),
    }),
    "heartbreak_fighter": ("Crestfallen Warrior", "Nexus", "The despairing knight on the Nexus stairs.", {
        "STONE_PILLAR": "In the Nexus (normal)",
        "ANGRY": "Hostile (you attacked him)",
        "DEAD": "Dead",
        "MAYBE_DELETE": "Starting to fade away (late game)",
        "DELETE": "Faded away (the game turns this into dead)",
    }),
    "mefist": ("Mephistopheles", "Nexus", "Hires you to assassinate other Nexus NPCs after Yurt is gone.", {
        "NO_STAY": "Not in the Nexus yet",
        "STONE_PILLAR": "In the Nexus",
        "ANGRY": "Hostile",
        "DEAD": "Dead",
        "KILL_WAIT_RENDOL": "Contract: kill Ostrava",
        "KILL_WAIT_BIYO": "Contract: kill Biorr",
        "KILL_WAIT_ROGARN": "Contract: kill Sage Freke",
        "KILL_WAIT_MAJO": "Contract: kill Yuria",
        "KILL_WAIT_URU": "Contract: kill Saint Urbain",
        "KILL_WAIT_TOMASU": "Contract: kill Stockpile Thomas",
        "KILL_WAIT_BATTI": "Contract: kill Patches",
    }),
    "rogarn": ("Sage Freke", "Latria, then Nexus", "Sorcery teacher; starts imprisoned in the Tower of Latria.", {
        "PRISONER": "Imprisoned in the Tower of Latria (start)",
        "GO_M1": "Freed: on his way to the Nexus",
        "WAIT": "In the Nexus, teaches sorcery",
        "LAST_WARD": "In the Nexus with last words for you (late game)",
        "ANGRY_M4": "Hostile, in Latria",
        "ANGRY_M1": "Hostile, in the Nexus",
        "DEAD": "Dead",
    }),
    "magic_student": ("Freke's Apprentice", "Nexus", "Sells beginner spells; asks you to free Sage Freke.", {
        "ISNOT": "Not in the Nexus yet (arrives after your first demon kill)",
        "ROGARN_HELP": "Asks you to free Sage Freke from Latria",
        "ROGARN_TOGETHER": "With Sage Freke in the Nexus",
        "FALL": "Disheartened",
        "ANGRY": "Hostile",
        "DEAD": "Dead",
    }),
    "yuruto": ("Yurt, the Silent Chief", "Latria, then Nexus", "The assassin; starts locked up in the Tower of Latria.", {
        "LIFT": "Locked up in Latria by the lift (start)",
        "STANDBY_M1": "Freed: will come to the Nexus",
        "WAIT_M1": "In the Nexus",
        "ANGRY_M4": "Hostile, in Latria",
        "ANGRY_M1": "Hostile, in the Nexus",
        "DEAD": "Dead",
    }),
    "majo": ("Yuria the Witch", "Latria, then Nexus", "Dark-magic teacher; starts locked up in the Tower of Latria.", {
        "LIBERATE": "Locked up in Latria, asks to be freed (start)",
        "BREAK": "Freed: resting in the tower",
        "THANKS": "Thankful",
        "WAIT_M1": "In the Nexus, teaches spells",
        "HOSTILE": "Hostile, in Latria",
        "ANGRY_M1": "Hostile, in the Nexus",
        "DEAD": "Dead",
    }),
    "viraidel": ("Rydell", "Latria", "Locked in a Tower of Latria cell; wants his late wife's keepsake from his corpse.", {
        "HELP": "Locked in a cell, asks to be freed (start)",
        "SEARCH": "Freed: looking for his wife's keepsake",
        "ANGRY": "Hostile",
        "DEAD": "Dead",
    }),
    "noble_woman": ("Former Noble's Wife", "Latria", "Merchant in the Tower of Latria.", {
        "BUSINESS": "Selling (normal)",
        "ANGRY": "Hostile",
        "DEAD": "Dead",
    }),
    "urubain": ("Saint Urbain", "Rescued, then Nexus", "Miracle teacher; must be rescued, then comes to the Nexus.", {
        "HELP": "Needs rescuing (start)",
        "THANKS": "Rescued, thankful",
        "STONE_PILLAR": "In the Nexus, teaches miracles",
        "ANGRY": "Hostile",
        "STONE_PILLAR_ANGRY": "Hostile, in the Nexus",
        "DEAD": "Dead",
    }),
    "god_beliver1": ("Acolyte of God", "Nexus", "One of Saint Urbain's three followers (talk rows 43xxx = NPC name 43).", {
        "ISNOT": "Not in the Nexus yet",
        "STONE_PILLAR": "In the Nexus",
        "URU": "With Saint Urbain in the Nexus",
        "FALL": "Disheartened",
        "ANGRY": "Hostile",
        "DEAD": "Dead",
    }),
    "god_beliver2": ("Disciple of God", "Nexus", "The follower of Saint Urbain who leaves to look for him (talk rows 44xxx).", {
        "ISNOT": "Not in the Nexus yet",
        "STONE_PILLAR": "In the Nexus",
        "FALL": "Disheartened",
        "ANGRY": "Hostile",
        "ISNOTALREADY": "Left to find Saint Urbain and never came back",
        "DEAD": "Dead",
    }),
    "god_beliver3": ("Worshiper of God", "Nexus", "One of Saint Urbain's three followers (talk rows 45xxx).", {
        "STONE_PILLAR": "In the Nexus (start)",
        "URU": "With Saint Urbain in the Nexus",
        "FALL": "Disheartened",
        "ANGRY": "Hostile",
        "DEAD": "Dead",
    }),
    "rendol": ("Ostrava of Boletaria", "Boletaria", "The knight you keep rescuing through Boletarian Palace.", {
        "HELP_FOR_DOREI_HEISI": "1-1: surrounded by dreglings, calls for help (start)",
        "THANKS_1": "1-1: rescued, thankful",
        "SEARCH_1": "1-1: exploring",
        "HOSTILE_1": "1-1: hostile",
        "HELP_HIDING_ME": "1-2: hiding, asks for help",
        "THANKS_2": "1-2: rescued, thankful",
        "SEARCH_2": "1-2: exploring",
        "HOSTILE_2": "1-2: hostile",
        "LOCATION_INVISIBLE": "Hidden out of sight",
        "WANT_TO_OPEN_THE_GATE": "1-3: asks you to open the gate",
        "SCARED": "1-3: cowering in a dead end",
        "THANKS_3": "1-3: rescued, thankful",
        "SEARCH_3": "1-3: exploring",
        "HOSTILE_3_FRONT_GATE": "1-3: hostile, in front of the gate",
        "HOSTILE_3_BACK_GATE": "1-3: hostile, behind the gate",
        "LIFT_FRONT": "1-4: by the lift",
        "HOSTILE_4_LIFT_FRONT": "1-4: hostile, by the lift",
        "HOSTILE_STONE_PILLAR": "Hostile, in the Nexus",
        "DEAD": "Dead",
        "ERASE": "Gone",
    }),
    "biyo": ("Biorr of the Twin Fangs", "Boletaria", "Imprisoned in Boletarian Palace; helps against the Penetrator (the scripts' \"King's Sword\") and later fights the dragon.", {
        "CAPTIVE": "Locked in a cell in Boletaria (start)",
        "THANKS": "Freed, thankful",
        "TARGET_ENEMY": "Wants to kill the jailer",
        "END_OF_STRIKES_BACK": "Got his revenge, sleeping it off",
        "SLEEPING_IN_PRISON": "Asleep in the cell",
        "SEARCH_3": "Exploring Boletaria 1-3",
        "KING_OF_SWORD_KILL": "Satisfied after the Penetrator fight",
        "BATTLE_FLY_DRAGON": "Fighting the flying dragon",
        "HOSTILE_IN_PRISON": "Hostile, in the cell",
        "HOSTILE_IN_RAMPART": "Hostile, on the ramparts",
        "HOSTILE_IN_KING_ROOM": "Hostile, in the Penetrator's room",
        "HOSTILE_IN_GATE_FRONT": "Hostile, in front of the gate",
        "HOSTILE_IN_STONE_PILLAR": "Hostile, in the Nexus",
        "DEAD": "Dead",
        "EXIT": "Gone",
    }),
    "doran": ("Old King Doran", "Boletaria", "Guards the Demonbrandt mausoleum in Boletaria.", {
        "GUARD": "Guarding the mausoleum (normal)",
        "ALLOWED": "Has accepted you",
        "NOT_ALLOWED": "Will not forgive you any more",
        "DEAD": "Dead",
    }),
    "syuujin": ("Graverobber Blige", "Shrine of Storms", "Caught in Patches' trap in the Shrine of Storms; a merchant once freed.", {
        "ESCAPE": "Trapped in the water cage, wants out (start)",
        "THANKS": "Freed, thankful",
        "INTERVAL": "Resting by the water cage",
        "STAY": "In Shrine of Storms 4-2, selling",
        "ANGRY_01": "Hostile, at the water cage",
        "ANGRY_02": "Hostile, in 4-2",
        "DEAD": "Dead",
    }),
    "batti": ("Patches the Hyena", "Storms, Stonefang, Latria, Nexus", "Lures you into traps across several worlds, then sells in the Nexus.", {
        "NOT_STAY": "Not met yet",
        "COME": "Shrine of Storms: beckons you to the pit",
        "PUSHING": "Shrine of Storms: about to kick you into the pit",
        "SATISFIED": "Shrine of Storms: pleased (his trap worked)",
        "ANGRY": "Shrine of Storms: angry",
        "TRAP_M6": "Stonefang: luring you into a trap",
        "TREASURE_M6": "Stonefang: took the treasure",
        "VEXING_M6": "Stonefang: annoyed (you got out)",
        "DESTORYKUMA": "Stonefang: you killed the Giant Bearbug",
        "PRESENT": "Stonefang: gave you an item",
        "ANGRY_M6": "Stonefang: hostile",
        "SATISFIED_M4": "Latria: pleased",
        "VEXING_M4": "Latria: annoyed",
        "ANGRY_M4": "Latria: hostile",
        "RESERVE_M1": "In the Nexus, selling",
        "ANGRY_M1": "Hostile, in the Nexus",
        "DEAD": "Dead",
    }),
    "half": ("Scirvir, the Wanderer", "Stonefang, then Nexus", "The treasure hunter; appears in Stonefang Tunnel when its tendency allows.", {
        "WAIT_KOUDOU": "Waiting in Stonefang Tunnel",
        "GO_TO_SEKITYU": "On his way to the Nexus",
        "WAIT_SEKITYU": "In the Nexus",
        "HOSTILE_KOUDOU": "Hostile, in Stonefang",
        "HOSTILE_SEKITYU": "Hostile, in the Nexus",
        "DEAD": "Dead",
    }),
    "doreisol_shop": ("Dregling Merchant", "Boletaria", "A dregling who sells goods in Boletarian Palace, moving from 1-1 to 1-3.", {
        "DOREISOL_SHOP_SELL01": "1-1: selling",
        "DOREISOL_SHOP_HOSTILE01": "1-1: hostile",
        "DOREISOL_SHOP_SELL02": "1-2: selling",
        "DOREISOL_SHOP_HOSTILE02": "1-2: hostile",
        "DOREISOL_SHOP_SELL03": "1-3: selling",
        "DOREISOL_SHOP_HOSTILE03": "1-3: hostile",
        "DOREISOL_SHOP_DEAD": "Dead",
    }),
    "masterparam": ("Master Satsuki", "Shrine of Storms", "Searches for his father's sword, the Makoto.", {
        "MasterSATSUKI_NORMAL": "Looking for the Makoto (normal)",
        "MasterSATSUKI_HOSTILE": "Hostile (you attacked him)",
        "MasterSATSUKI_HOSTILE_Makoto": "Hostile for good (he saw the Makoto)",
        "MasterSATSUKI_DEAD": "Dead",
    }),
    "smith": ("Blacksmith Ed", "Stonefang", "The blacksmith at the entrance to Stonefang Tunnel.", {
        "SMITH_WORKING": "Working (normal)",
        "SMITH_ANGRY": "Hostile (you attacked him)",
        "SMITH_DEAD": "Dead",
    }),
    "shop": ("Filthy Man", "Stonefang", "The merchant in Stonefang Tunnel, moving from 2-1 to 2-2 (talk rows 49xxx).", {
        "SHOP_NORMAL_1": "2-1: selling",
        "SHOP_HOSTILE_1": "Hostile (2-1 or 2-2; one flag for both)",
        "SHOP_NORMAL_2": "2-2: selling",
        "SHOP_DEAD": "Dead",
    }),
    "kojiki_shop": ("Filthy Woman", "Valley of Defilement", "Sells goods in the Valley of Defilement, moving from 5-1 to 5-2.", {
        "KOJIKI_FEMALE_SHOP_SELL01": "5-1: selling",
        "KOJIKI_FEMALE_SHOP_HOSTILE01": "5-1: hostile",
        "KOJIKI_FEMALE_SHOP_SELL02": "5-2: selling",
        "KOJIKI_FEMALE_SHOP_HOSTILE02": "5-2: hostile",
        "KOJIKI_FEMALE_SHOP_DEAD": "Dead",
    }),
    "selen": ("Selen Vinland", "", "Searches for her brother, Garl Vinland.", {
        "SEARCH_BROTHER": "Looking for her brother (normal)",
        "THANKS": "Satisfied",
        "PURIFY": "At peace, gone",
        "ANGRY": "Hostile",
        "DEAD": "Dead",
    }),
    "tyo": ("Flying Dragon (the chief)", "Boletaria", "The great dragon over Boletarian Palace (the game names both dragons \"Flying Dragon\"); its sleep and retreat are in the next list.", {
        "WARNING_AISLE": "On guard over the passage",
        "WARNING_GATE": "On guard over the gate",
        "WARNING_KING_ROOM": "On guard over the king's hall",
        "DEAD": "Dead",
    }),
    "tyo1": ("Flying Dragon (the chief), nest", "Boletaria", "Whether the chief dragon is in its nest.", {
        "SLEEPING": "Asleep in its nest",
        "ESCAPE": "Withdrawn",
    }),
    "kenzoku": ("Flying Dragon kin 1", "Boletaria 1-1", "The dragon of Boletaria 1-1.", {
        "WARNING": "In its nest",
        "ABSENCE": "Away",
        "PROTECT_CASTLE": "Guarding the wall",
        "WARNING_AND_LEVER": "In its nest (no longer stops the lever)",
        "ABSENCE_AND_LEVER": "Away (no longer stops the lever)",
        "ESCAPE": "Withdrawn",
        "DEAD": "Dead",
        "KENZOKU_2_STATE_DEAD": "Kin 2 dead (shared with kin 2's list)",
    }),
    "kenzoku_2": ("Flying Dragon kin 2", "Boletaria 1-2", "The dragon of Boletaria 1-2.", {
        "WARNING": "On guard",
        "HEROHERO": "Worn out",
        "DEAD": "Dead",
        "KENZOKU_STATE_DEAD": "Kin 1 dead (shared with kin 1's list)",
    }),
}
# Display order: the Nexus residents, then each world's NPCs, then the dragons.
NPC_ORDER = ["heroine", "yojin", "baldwin", "tomasu", "heartbreak_fighter", "mefist",
             "magic_student", "rogarn", "yuruto", "majo", "viraidel", "noble_woman",
             "urubain", "god_beliver1", "god_beliver2", "god_beliver3",
             "rendol", "biyo", "doran", "doreisol_shop", "syuujin", "masterparam",
             "batti", "smith", "shop", "half", "kojiki_shop", "selen",
             "tyo", "tyo1", "kenzoku", "kenzoku_2"]
# SHOP_LINEUP_PARAM.equipType -> item category; ITEMLOT category bits >> 28.
SHOP_CATEGORY = {0: "Weapon", 1: "Armor", 2: "Ring", 3: "Goods"}
LOT_CATEGORY = {0x0: "Weapon", 0x1: "Armor", 0x2: "Ring", 0x4: "Goods"}
SHOP_GROUP = 8           # each limited shop row owns 8 consecutive flags

CONST_LINE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\d+)\s*;?'
                        r'\s*(?:--\s*(.*))?$', re.M)
# heroine_flag_list, SMITH_Flag_list, MasterParamFlag_list, ... (any case)
FLAG_LIST = re.compile(r'([A-Za-z_][A-Za-z0-9_]*?[Ff]lag_list)\s*=\s*\{(.*?)\}',
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
    if 'proxy:' in text or re.search(r'\b(then|end|local)\b.*[=(]', text):
        return ''                              # commented-out code, not a description
    # prefer the machine-translated English; keep Japanese-only text as-is
    if text and sum(ord(c) > 0x2FFF for c in text) > len(text) / 2:
        return ''
    # "English (日本語)" and the same with the closing bracket cut off
    text = re.sub(r'\s*[(（][^()（）]*[\u3000-\u9fff][^()（）]*[)）]?\s*$', '', text)
    return text.strip(' ();\t')


def parse_event_define(text: str) -> dict:
    """NPC state constants and state lists from event_define.lua."""
    consts = {}
    for m in CONST_LINE.finditer(text):
        consts[m.group(1)] = (int(m.group(2)), strip_comment(m.group(3)))
    lists = []
    for m in FLAG_LIST.finditer(text):
        members, seen = [], set()
        for name in LIST_MEMBER.findall(m.group(2)):
            # a list may repeat a flag under two names (SHOP_HOSTILE_1/_2 are
            # both 16411); the flag is one state, so keep its first name
            if name in consts and consts[name][0] not in seen:
                seen.add(consts[name][0])
                members.append((name, consts[name][0], consts[name][1]))
        lists.append({"list": m.group(1), "states": members})
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
        descs[int(m.group(1))].append(tidy(strip_comment(m.group(2))))
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


def npc_key(list_name: str) -> str:
    """heroine_flag_list -> heroine; MasterParamFlag_list -> masterparam."""
    return re.sub(r'_?flag_list$', '', list_name.lower())


def npc_entry(lst: dict) -> dict:
    """One state machine with its in-game name and plain-English states."""
    key = npc_key(lst['list'])
    name, where, about, labels = NPC_INFO.get(
        key, (key.replace('_', ' ').capitalize(), '', '', {}))
    states = []
    for const, fid, desc in lst['states']:
        short = const.split('_STATE_')[-1] if '_STATE_' in const else const.split('_', 1)[-1]
        label = labels.get(const, labels.get(short))   # exact constant first
        if label is None:                      # the batti list has no _STATE_
            label = labels.get(const.removeprefix('BATTI_'))
        marker = isinstance(label, tuple) and label[1]
        if isinstance(label, tuple):
            label = label[0]
        state = {"name": const, "id": fid, "desc": desc,
                 "label": label or short.replace('_', ' ').capitalize()}
        if marker:
            state["marker"] = True
        states.append(state)
    return {"list": lst['list'], "name": name, "where": where, "about": about,
            "states": states}


def item_names() -> dict[tuple[str, int], str]:
    try:
        doc = json.loads((HERE / 'itemdb.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {(i['category'], i['id']): i['name'] for i in doc.get('items', [])}


def param_flags(game: Path) -> tuple[list[dict], list[dict]]:
    """Shop-stock flag groups and one-time drop flags from the game's params."""
    tables = des_gamedata.load_params(game)
    names = item_names()
    shops = []
    for row_id, row in sorted(tables.get('SHOP_LINEUP_PARAM', {}).items()):
        if row['eventFlag'] < 0:
            continue
        category = SHOP_CATEGORY.get(row['equipType'])
        shops.append({"flag": row['eventFlag'], "count": SHOP_GROUP, "row": row_id,
                      "category": category, "item": row['equipId'],
                      "name": names.get((category, row['equipId'])),
                      "stock": row['sellQuantity'], "price": row['value']})
    lots = []
    for row_id, row in sorted(tables.get('ITEMLOT_PARAM_ST', {}).items()):
        if row['eventId'] in (0, -1):
            continue
        item = None
        # the flagged lots hand out their item through the host-only slot
        candidates = [(row['hostOnlyItemCate'], row['hostOnlyItemId'])]
        candidates += [(row[f'lotItemCategory{slot:02d}'], row[f'lotItemId{slot:02d}'])
                       for slot in range(1, 9)]
        for code, item_id in candidates:
            category = LOT_CATEGORY.get((code & 0xFFFFFFFF) >> 28) if code != -1 else None
            if category and item_id:
                item = {"category": category, "item": item_id,
                        "name": names.get((category, item_id))}
                break
        lots.append({"flag": row['eventId'], "lot": row_id, **(item or {})})
    return shops, lots


# Hand-written labels for flags the sources above describe badly or not at
# all: (area or None for a global flag, flag) -> text. Evidence in
# docs/research-event-flags.md ("Curated labels").
CURATED: dict[tuple[int | None, int], str] = {
    (1, 30): "Nexus intro cutscene played",
    (1, 31): "Revival cutscene played",
    (1, 34): "Keystone seal opened",
    (1, 90): "You knelt before the Maiden in Black",
    (2, 0): "Castle gate lever pulled",
    (2, 200): "Door to the execution ground opened",
    (2, 720): "Ostrava thanked you (one-off conversation)",
    (2, 1040): "Boletaria 1-1: castle gate opened by the lever",
    (2, 1380): "Yuria (the witch) thanked you (one-off conversation)",
    (6, 0): "Door opened by the lever",
    (6, 10): "Gear handle A turned",
    (6, 20): "Gear handle B turned",
    (6, 187): "The collapsing bridge has fallen",
    (6, 1050): "Entered the Dragon God's room",
}
# Recurring machine-translation mistakes in the scripts' comments, fixed in
# every label: (pattern, replacement); an empty replacement drops the label.
GLOSSARY = [
    (r'^for triggering events$', ''),
    (r'^(light fog|fog of light|mist of light)[^|]*?only the host PC can pass[^|]*$', 'Fog wall (host only)'),
    (r'^(light fog|fog of light|mist of light|light wall|wall of light)( ?\d+)?$', r'Fog wall\2'),
    (r'\b(light wall|wall of light)\b', 'fog wall'),
    (r'\bpoli(ce|ty|s)? ?plays?(ing)?\b|\bpoly ?plays?(ing)?\b|\bpolyphon(ic|y)( plays?)?( play)?'
     r'|\bpolitical (plays?|drama)\b|\bpolygram\b|\bpolyplastic\b|\bbospory play play\b',
     'cutscene'),
    (r'\bpolice door\b|\bpenal key\b', 'prison door'),
    (r'\bmedium boss\b|\bmiddle boss\b', 'boss'),
    (r'\bthe heroine\b', 'the Maiden in Black'),
    (r'\b(prince )?(lendor|lendrd|lendlund|lundle|rendezer|rendle)( prince)?\b', 'Ostrava'),
    (r'\b(bjyo|byo|beyonne|bjorn gurum|bjorn)\b', 'Biorr'),
    (r'\b(rogan|logan)\b', 'Freke'),
    (r'\byuruto\b', 'Yurt'),
    (r'\b(satki|sutaki)\b', 'Satsuki'),
    (r'\bur\b', 'Urbain'),
    (r'\bQWC\b', 'Tendency'),
    (r'\bOBJ\b', 'object'),
    (r'\bPC\b', 'player'),
    (r'BGM再生\s*(\d*)', r'Music \1 playing'),
]
_GLOSSARY = [(re.compile(p, re.I), r) for p, r in GLOSSARY]


def tidy(text: str) -> str:
    """Apply the glossary; '' when the label says nothing."""
    for pattern, replacement in _GLOSSARY:
        text = pattern.sub(replacement, text)
        if not text.strip():
            return ''
    text = re.sub(r'\s+', ' ', text).strip(' |')
    return text[:1].upper() + text[1:]


# --------------------------------------------------------------------------- #
#  More label sources: map layouts, talk tables, talk scripts, script usage
# --------------------------------------------------------------------------- #
TALK_LINE = re.compile(r'TALK_MSG_(\d+):[0-9A-Fa-f]+=([^\r\n]*)')
ESD_INT = re.compile(rb'\x82(....)', re.S)   # an i32 literal in ESD bytecode
ESD_NAME = re.compile(rb'talk\\(t\d+)\.esd')
# proxy:OnXxx(id, ...) registers script event `id`; with `once` the game keeps
# it as a flag. What triggers it, in plain words:
TRIGGERS = {
    "OnKeyTime": "a timer ran out", "OnKeyTime2": "a timer ran out",
    "OnCharacterDead": "an enemy died", "OnCharacterHP": "an enemy's HP dropped",
    "OnCharacterTotalDamage": "an enemy took damage",
    "OnCharacterTotalRateDamage": "an enemy took damage",
    "OnSimpleDamage": "something took damage",
    "OnRegionIn": "the player reached a spot", "OnRegionJustIn": "the player reached a spot",
    "OnRegionJustInAttribute": "the player reached a spot",
    "OnPlayerActionInRegion": "the player acted at a spot",
    "OnRegionJustOut": "the player left a spot",
    "OnDistanceAction": "the player used something (lever, door, corpse)",
    "OnDistanceActionAttribute": "the player used something (lever, door, corpse)",
    "OnDistanceActionPlus": "the player used something (lever, door, corpse)",
    "OnActionEventRegion": "the player used something (lever, door, corpse)",
    "OnChrAnimEnd": "an animation finished", "OnCharacterAnimEnd": "an animation finished",
    "OnCheckEzStateMessage": "an animation signalled",
    "OnObjectDestroy": "an object was destroyed",
    "CreateEventBody": "a body part was broken off", "CreateEventBodyPlus": "a body part was broken off",
    "AddCorpseEvent": "a corpse was searched",
    "TreasureDispModeChange": "a treasure was shown or hidden",
    "TreasureDispModeChange2": "a treasure was shown or hidden",
    "EnableObjTreasure": "a treasure was enabled",
    "GetRateItem": "the script handed over an item",
    "OnRegistFunc": "a condition the script watches came true",
}
PROXY_CALL = re.compile(r'proxy:(\w+)\(\s*(\d{1,5})\b')
LUA_CALL = re.compile(r'(SingleReset|LuaCall\w*)\(\s*(?:proxy\s*,\s*)?(\d{1,5})\b')
TRAILING = re.compile(r'--\s*(.*)$')
# comments about the code, not about the flag ("16900 seems high enough not
# to be in use", "Condition is met", "Clear flag ON")
DEV_NOTE = re.compile(r'high enough|ceiling|in use|^condition (is|not)|^debug|^for debug'
                      r'|^(clear )?flag (on|off)$|^on$|^off$', re.I)
RANGE_COMMENT = re.compile(r'--[■▼]\s*(\d+)\s*[-～~]\s*(\d+)\s*[■▼]\s*([^■▼\n]*)')
SINGLE_COMMENT = re.compile(r'--▼\s*(\d+)\s*▼\s*([^▼\n]*)')


def english(comment: str) -> str:
    """'Clear flag ON (クリアフラグON)' -> 'Clear flag ON'; '' for Japanese only."""
    text = strip_comment(comment)
    text = re.sub(r'\s*\([^()]*[\u3000-\u9fff][^()]*\)\s*$', '', text)
    if not text or sum(ord(c) > 0x2FFF for c in text) > len(text) / 3:
        return ''
    return text.strip(' -;')


def script_usage(text: str) -> dict[int, dict]:
    """Every number a script hands to a flag/event call: id -> {calls, notes}.

    ``notes`` are the English trailing comments of SetEventFlag lines and the
    ``--▼ id ▼`` / ``--■ a - b ■`` headers the comment parser misses.
    """
    out: dict[int, dict] = collections.defaultdict(lambda: {"calls": set(), "notes": []})
    for line in text.splitlines():
        found = [(m.group(1), int(m.group(2))) for m in PROXY_CALL.finditer(line)]
        found += [(m.group(1), int(m.group(2))) for m in LUA_CALL.finditer(line)]
        for call, flag in found:
            out[flag]["calls"].add(call)
            if call in ('SetEventFlag', 'IsCompleteEvent'):
                note = TRAILING.search(line.split(')', 1)[-1])
                text_ = english(note.group(1)) if note else ''
                if text_ and len(text_) > 3 and not DEV_NOTE.search(text_) \
                        and text_ not in out[flag]["notes"]:
                    out[flag]["notes"].append(text_)
        for m in RANGE_COMMENT.finditer(line):
            lo, hi = int(m.group(1)), int(m.group(2))
            note = english(m.group(3))
            if note and 0 < hi - lo <= 64:
                for flag in range(lo, hi + 1):
                    if note not in out[flag]["notes"]:
                        out[flag]["notes"].append(note)
        for m in SINGLE_COMMENT.finditer(line):
            note = english(m.group(2))
            if note and note not in out[int(m.group(1))]["notes"]:
                out[int(m.group(1))]["notes"].append(note)
    return out


def usage_label(info: dict) -> str | None:
    notes = [tidy(n) for n in info["notes"]]
    notes = [n for n in notes if n]
    if notes:
        return notes[0]
    triggers = sorted({TRIGGERS[c] for c in info["calls"] if c in TRIGGERS})
    if triggers:
        return "Script event: " + "; ".join(triggers[:2])
    flagish = info["calls"] & {"SetEventFlag", "IsCompleteEvent", "SingleReset"}
    if flagish:
        return "Script flag (no description in the scripts)"
    return None


def read_talk_text(game: Path) -> dict[int, str]:
    path = game / 'text' / 'ds' / '_cmn' / 'talk_msg.en.ctxt'
    if not path.exists():
        return {}
    return {int(k): v.replace('\\n', ' ').strip()
            for k, v in TALK_LINE.findall(path.read_text(encoding='utf-8-sig'))}


def first_line(talk_text: dict[int, str], talk_id: int) -> str:
    """First non-empty line of a TALK_PARAM row's text (msg ids talk*1000+n)."""
    for n in range(0, 40):
        text = talk_text.get(talk_id * 1000 + n, '')
        if text:
            return text if len(text) <= 70 else text[:67].rstrip() + '…'
    return ''


def talk_scripts(game: Path) -> list[dict]:
    """Talk state machines (script/talk/mXX.talkesdbnd): per script, its area,
    the TALK_PARAM rows it plays and the flag ids it reads or writes (every
    i32 literal in its bytecode that is not a talk row)."""
    tables = des_gamedata.load_params(game)
    talk_rows = set(tables.get('TALK_PARAM_ST', {}))
    out = []
    folder = game / 'cp11demonssouls' / 'dvdroot' / 'script' / 'talk'
    for path in sorted(folder.glob('m0*.talkesdbnd')):
        area = int(path.name[1:3])
        data = path.read_bytes()
        names = [n.decode() for n in ESD_NAME.findall(data)]
        starts = [m.start() for m in re.finditer(rb'DLSE', data)] + [len(data)]
        if len(starts) - 1 != len(names):
            continue
        for n, name in enumerate(names):
            chunk = data[starts[n]:starts[n + 1]]
            values = {int.from_bytes(m.group(1), 'little', signed=True)
                      for m in ESD_INT.finditer(chunk)}
            out.append({"script": name, "area": area,
                        "talks": sorted(v for v in values if v in talk_rows),
                        "flags": sorted(v for v in values
                                        if 0 <= v < FLAG_CAPACITY and v not in talk_rows)})
    return out


def talk_speakers(scripts: list[dict], npcs: list[dict], talk_text: dict[int, str],
                  npc_names: dict[int, str]) -> dict[str, str]:
    """Talk script -> NPC name. A TALK_PARAM row id divided by 1000 is the
    speaker's npc_name id (43500 -> 43 "Acolyte of God"), so the most common
    one among a script's rows names it. Rows of unnamed speakers fall back to
    the NPC whose state flags the script touches most, then to its first line."""
    owner = {}
    for npc in npcs:
        for state in npc['states']:
            owner.setdefault(state['id'], npc['name'])
    out = {}
    for script in scripts:
        rows = collections.Counter(row // 1000 for row in script['talks'])
        named = [npc_names.get(k) for k, _ in rows.most_common() if npc_names.get(k)]
        votes = collections.Counter(owner[f] for f in script['flags'] if f in owner)
        if named:
            out[script['script']] = named[0]
        elif votes:
            out[script['script']] = votes.most_common(1)[0][0]
        elif script['talks']:
            line = first_line(talk_text, script['talks'][0])
            out[script['script']] = f'someone who says "{line}"' if line else ''
    return out


def read_npc_names(game: Path) -> dict[int, str]:
    path = game / 'text' / 'ds' / '_cmn' / 'npc_name.en.ctxt'
    if not path.exists():
        return {}
    return {int(k): v.strip() for k, v in
            re.findall(r'NPC_NAME_(\d+):[0-9A-Fa-f]+=([^\r\n]*)',
                       path.read_text(encoding='utf-8-sig')) if v.strip()}


def map_entities(game: Path, items: dict, lots_table: dict) -> tuple[dict, dict, dict]:
    """(pickups, placed, pickup_items): area -> {flag: ...} from the map layouts.

    A treasure event names a part; that part's entity id is the flag the game
    sets when the pickup is taken. Other parts whose entity id falls in a local
    range (enemies that stay dead, broken objects) are listed as "placed".
    ``pickup_items`` keeps each pickup's level, map and items
    ([category, id, count, name]) for the page's Pickups view.
    """
    labels = build_entitydb.level_labels(game / 'misc' / 'dspointsofinterest.txt')
    pickups: dict[int, dict[int, str]] = collections.defaultdict(dict)
    placed: dict[int, dict[int, str]] = collections.defaultdict(dict)
    pickup_items: dict[int, dict[int, dict]] = collections.defaultdict(dict)
    for msb in des_msb.load_all(game):
        area = msb.area + 1
        level = labels.get(msb.name[:6], msb.name[:6])
        for flag, info in des_msb.treasure_flags(msb).items():
            if not is_local(flag):
                continue
            entries = []
            for lot in info['lots']:
                entries += lot_entries(lots_table.get(lot), items)
            names = [entry_name(e) for e in entries]
            what = ', '.join(dict.fromkeys(names)) or f"item lot {info['lots'][0]}"
            if flag not in pickups[area]:
                pickups[area][flag] = f"Pickup: {what} ({level})"
                pickup_items[area][flag] = {"level": level, "map": msb.name,
                                            "items": [list(e) for e in entries]}
        for part in msb.parts:
            if part.entity > 0 and is_local(part.entity) and part.type in (1, 2) \
                    and part.entity not in pickups[area]:
                kind = "Enemy" if part.type == 2 else "Object"
                placed[area].setdefault(part.entity, f"{kind} {part.name} ({level})")
    return pickups, placed, pickup_items


def lot_entries(row: dict | None, items: dict) -> list[tuple[str, int, int, str]]:
    """(category, item id, count, name) of each item of one ITEMLOT row."""
    if not row:
        return []
    out = []
    slots = [(row['hostOnlyItemCate'], row['hostOnlyItemId'], row['hostOnlyItemNum'])]
    slots += [(row[f'lotItemCategory{n:02d}'], row[f'lotItemId{n:02d}'],
               row[f'lotItemNum{n:02d}']) for n in range(1, 9)]
    for code, item_id, count in slots:
        category = LOT_CATEGORY.get((code & 0xFFFFFFFF) >> 28) if code != -1 else None
        if not category or item_id <= 0:
            continue
        out.append((category, item_id, count,
                    items.get((category, item_id)) or f"{category} {item_id}"))
    return out


def entry_name(entry: tuple[str, int, int, str]) -> str:
    """"Grass ×2" for a lot entry."""
    _, _, count, name = entry
    return f"{name} ×{count}" if count and count > 1 else name


FORGIVE_CALL = re.compile(r'RestoreBackupNpcStateFlag\s*\(\s*proxy\s*,\s*param\s*,\s*(\w+)\s*,'
                          r'\s*(\w+)\s*,\s*\{(.*?)\}\s*\)\s*;')
FORGIVE_AREA = re.compile(r'\{\s*(\d+)\s*,\s*\{([\d,\s]*)\}\s*\}')


def parse_forgiveness(global_text: str, consts: dict) -> list[dict]:
    """SeekForgiveness's table (global_event.lua): which hostile state of
    which list the game can forgive, and the area-local flags it clears."""
    start = global_text.index('function SeekForgiveness')
    body = global_text[start:global_text.index('\nend', start)]
    out = []
    for m in FORGIVE_CALL.finditer(body):
        const = m.group(2)
        if const not in consts:
            continue
        resets = {}
        for area, flags in FORGIVE_AREA.findall(m.group(3)):
            resets[int(area)] = [int(f) for f in re.findall(r'\d+', flags)]
        out.append({"list": m.group(1), "state": const, "id": consts[const][0],
                    "reset": {str(a): f for a, f in resets.items()}})
    return out


SET_TRUE = re.compile(r'SetEventFlag\s*\(\s*(\d+)\s*,\s*(?:true|1)\s*\)')


def boss_resets(script_dir: Path, local: dict) -> dict[int, dict]:
    """What a full respawn clears besides the death and soul flags, per boss.

    From the boss's own map script (the one whose handler sets the death flag):
    ``block`` = global flags it sets within 20 above the death flag (fog,
    cutscene and soul-pickup flags; other bosses' flags excluded) plus the
    non-counter flags the death handler itself sets; ``room`` = local flags it
    sets whose description mentions the boss (room entered, boss door, fight
    started). World counters (8000-8099) are left alone.
    """
    ids = {b[0] for b in BOSSES} | {b[4] for b in BOSSES}
    out = {}
    for death, area, _name, _world, soul in BOSSES:
        block, room = set(), set()
        for path in sorted(script_dir.glob(f'm{area:02d}_*.lua')):
            if 'eventboss' in path.name:
                continue
            text = _read(path)
            sets = {int(m.group(1)) for m in SET_TRUE.finditer(text)}
            if death not in sets:
                continue
            block |= {f for f in sets if death < f < death + 20 and (f not in ids or f == soul)}
            for chunk in re.split(r'\n(?=function\s)', text):
                chunk_sets = {int(m.group(1)) for m in SET_TRUE.finditer(chunk)}
                if death in chunk_sets:
                    block |= {f for f in chunk_sets
                              if f != death and not 8000 <= f < 8100 and not is_local(f)}
                    room |= {f for f in chunk_sets if is_local(f)}
            companion = path.with_name(path.stem + '_eventboss.lua')
            if companion.exists():
                sets |= {int(m.group(1)) for m in SET_TRUE.finditer(_read(companion))}
            for flag in sets:
                entry = local.get(area, {}).get(flag)
                if is_local(flag) and entry and any('boss' in d.lower() for d in entry['descs']):
                    room.add(flag)
        block.discard(soul)
        out[death] = {"block": sorted(block), "room": sorted(room)}
    return out


RATE_ITEM = re.compile(r'GetRateItem\s*\(\s*(\d+)\s*\)')
ONCE_BLOCK = re.compile(r'if\s+proxy:IsCompleteEvent\s*\(\s*(\d+)\s*\)\s*==\s*false\s+then(.*?)\n\s*end', re.S)


def rate_item(lot: int, lots_table: dict, items: dict) -> list[tuple[str, int, int, str]]:
    """What ``GetRateItem(lot)`` hands over: an ITEMLOT row, or (the remake's
    additions) an item encoded as category << 28 | id (0x40002709 = Goods 9993)."""
    if lot in lots_table:
        return lot_entries(lots_table[lot], items)
    category = LOT_CATEGORY.get(lot >> 28) if lot >= 1 << 28 else None
    if category is None:
        return []
    item_id = lot & 0x0FFFFFFF
    return [(category, item_id, 1, items.get((category, item_id)) or f"{category} {item_id}")]


def soul_handlers(script_dir: Path, lots_table: dict, items: dict) -> dict[int, dict]:
    """Per boss (death flag): what its "Get Soul" handler hands over.

    The handler is the map-script function that sets the soul flag
    (``OnEvent_4103_1``: ``GetRateItem(10110) -- Soul``, four empty lots, then
    ``SetEventFlag(4103, 1)``). ``soul_items`` are its unconditional items (the
    demon soul first; Maiden Astrea's also holds the Ring of Sincere Prayer); ``bonus`` are its ``if not IsCompleteEvent(F) then
    GetRateItem(..) SetEventFlag(F)`` blocks (the remake's one-time Nexial
    Agent for the four world-final bosses, flag 17800).
    """
    out = {}
    for death, area, name, _world, soul in BOSSES:
        found = None
        for path in sorted(script_dir.glob(f'm{area:02d}_*.lua')):
            text = re.sub(r'--[^\n]*', '', _read(path))
            for chunk in re.split(r'\n(?=function\s)', text):
                if soul in {int(m.group(1)) for m in SET_TRUE.finditer(chunk)} \
                        and RATE_ITEM.search(chunk):
                    found = chunk
                    break
            if found:
                break
        if found is None:
            raise AssertionError(f"no soul handler found for {name} (flag {soul})")
        bonus = []
        for m in ONCE_BLOCK.finditer(found):
            given = [list(e) for lot in RATE_ITEM.findall(m.group(2))
                     for e in rate_item(int(lot), lots_table, items)]
            if given:
                bonus.append({"flag": int(m.group(1)), "items": given})
        plain = ONCE_BLOCK.sub('', found)
        souls = [list(e) for lot in RATE_ITEM.findall(plain)
                 for e in rate_item(int(lot), lots_table, items)]
        # the demon soul comes first; Maiden Astrea's pickup also holds a ring
        assert souls and souls[0][0] == 'Goods' and 'Demon Soul' in souls[0][3], \
            f"{name}: the soul pickup should start with a demon soul, got {souls}"
        out[death] = {"soul_items": souls, "bonus": bonus}
    return out


def build(game: Path) -> dict:
    script_dir = game / 'cp11demonssouls' / 'dvdroot' / 'script'
    define = parse_event_define(_read(script_dir / 'event_define.lua'))
    global_text = _read(script_dir / 'global_event.lua')
    table_flags = parse_boss_table(global_text)

    # ---- sanity: the hardcoded boss table must match the game's own ----------
    assert sorted(table_flags) == sorted(f for f, *_ in BOSSES), \
        f"boss table mismatch: game={sorted(table_flags)}"

    maps, usage = {}, {}
    for path in sorted(script_dir.glob('*.lua')):
        if 'testroom' in path.name or path.name == 'event_define.lua':
            continue
        maps[path.name] = parse_map(path)
        usage[path.name] = script_usage(_read(path))
    # per-map area assignment from the map id (m02_* -> area 02)
    def area_of(file_name: str) -> int | None:
        m = re.match(r'm(\d\d)_', file_name)
        return int(m.group(1)) if m else None

    # ---- flag events -----------------------------------------------------------
    # Local flags (see LOCAL_RANGES) are documented per map; global ones keep
    # every map's description. Call sites ("uses") are kept per file.
    local: dict[int, dict[int, dict]] = collections.defaultdict(dict)
    global_: dict[int, dict] = {}
    scripts: dict[int, dict] = {}
    local_any: dict[int, dict] = {}

    def entry_for(flag: int, area: int | None, file_name: str) -> dict:
        if not is_local(flag):
            return global_.setdefault(flag, {"id": flag, "areas": {}})
        if area is None or area not in AREAS:
            entry = scripts.setdefault(flag, {"id": flag, "descs": [], "files": []})
            if file_name not in entry['files']:
                entry['files'].append(file_name)
            return entry
        return local[area].setdefault(flag, {"id": flag, "descs": []})

    # (area or None for global, flag) -> [(kind, text)]
    extra: dict[tuple[int | None, int], list[tuple[str, str]]] = collections.defaultdict(list)

    def add(area: int | None, flag: int, kind: str, text: str) -> None:
        if text and (kind, text) not in extra[(area, flag)]:
            extra[(area, flag)].append((kind, text))

    for file_name, data in maps.items():
        area = area_of(file_name)
        for flag, descs in data['descs'].items():
            if not 0 <= flag < FLAG_CAPACITY:
                continue
            entry = entry_for(flag, area, file_name)
            seen = (entry['areas'].setdefault(str(area or 0), [])
                    if 'areas' in entry else entry['descs'])
            for d in descs:
                if d and d not in seen:
                    seen.append(d)
        for arg, funcs in data['uses'].items():
            if not arg.isdigit() or not 0 <= int(arg) < FLAG_CAPACITY:
                continue
            entry = entry_for(int(arg), area, file_name)
            entry.setdefault('uses', []).extend(
                f"{file_name}:{fn}" for fn in sorted(set(funcs)))
        if area in AREAS:
            for flag, info in usage[file_name].items():
                if 0 <= flag < FLAG_CAPACITY:
                    label = usage_label(info)
                    if label:
                        add(area if is_local(flag) else None, flag, "usage", label)
    for entry in global_.values():                  # drop empty description lists
        entry['areas'] = {k: v for k, v in entry['areas'].items() if v}

    # ---- map layouts, talk tables and talk scripts ---------------------------
    tables = des_gamedata.load_params(game)
    items = item_names()
    pickups, placed, pickup_items = map_entities(game, items,
                                                 tables.get('ITEMLOT_PARAM_ST', {}))
    souls = soul_handlers(script_dir, tables.get('ITEMLOT_PARAM_ST', {}), items)
    for area, rows in pickups.items():
        for flag, label in rows.items():
            add(area, flag, "pickup", label)
    for area, rows in placed.items():
        for flag, label in rows.items():
            add(area, flag, "placed", label)
    order = {key: n for n, key in enumerate(NPC_ORDER)}
    npcs = sorted((npc_entry(lst) for lst in define['lists']),
                  key=lambda n: order.get(npc_key(n['list']), len(order)))
    talk_text = read_talk_text(game)
    talks = talk_scripts(game)
    speakers = talk_speakers(talks, npcs, talk_text, read_npc_names(game))
    talk_area: dict[int, set] = collections.defaultdict(set)
    flag_scripts: dict[tuple[int | None, int], set] = collections.defaultdict(set)
    for script in talks:
        for row in script['talks']:
            talk_area[row].add(script['area'])
        for flag in script['flags']:
            flag_scripts[(script['area'] if is_local(flag) else None, flag)].add(script['script'])
    for (area, flag), names in flag_scripts.items():
        who = sorted({speakers.get(n, '') for n in names} - {''})
        if len(who) == 1:
            add(area, flag, "conversation", f"Conversation with {who[0]} (dialogue progress)")
    for row_id, row in sorted(tables.get('TALK_PARAM_ST', {}).items()):
        flag = row['eventId']
        if flag <= 0 or flag >= FLAG_CAPACITY:
            continue
        line = first_line(talk_text, row_id)
        label = f'Heard: "{line}"' if line else f"Heard talk {row_id}"
        if not is_local(flag):
            add(None, flag, "talk", label)
        elif len(talk_area[row_id]) == 1:
            add(next(iter(talk_area[row_id])), flag, "talk", label)
        else:
            local_any.setdefault(flag, {"id": flag, "descs": [], "kind": "talk"})
            if label not in local_any[flag]['descs']:
                local_any[flag]['descs'].append(label)
    for (area, flag), texts in CURATED.items():
        add(area, flag, "curated", texts)

    shops, lots = param_flags(game)
    backup = define['backup_offset']
    named_elsewhere = {f for f, *_ in BOSSES} | {b[4] for b in BOSSES}
    named_elsewhere |= {lot['flag'] for lot in lots}
    named_elsewhere |= {s['flag'] + n for s in shops for n in range(s['count'])}
    for npc in npcs:
        named_elsewhere |= {s['id'] for s in npc['states']}
        named_elsewhere |= {s['id'] + backup for s in npc['states']}

    def is_named_elsewhere(flag: int) -> bool:
        return flag in named_elsewhere

    # ---- merge: descs best first (KINDS order), "kind" = the first one's source
    rank = {kind: n for n, kind in enumerate(KINDS)}
    for (area, flag), found in extra.items():
        found = sorted(found, key=lambda kt: rank[kt[0]])
        if area is None:
            entry = global_.setdefault(flag, {"id": flag, "areas": {}})
            comments = bool(entry.get('areas'))
            keep = [(k, x) for k, x in found if k != "usage"]
            if not keep and not comments and not is_named_elsewhere(flag):
                keep = [(k, x) for k, x in found if k == "usage"][:1]
            # curated first, then param/talk labels; script comments stay in "areas"
            entry['descs'] = list(dict.fromkeys(x for _, x in keep))
            if keep:
                entry['kind'] = keep[0][0]
            elif comments:
                entry['kind'] = "comment"
            continue
        entry = local[area].setdefault(flag, {"id": flag, "descs": []})
        comments = list(entry['descs'])
        merged = [(k, x) for k, x in found if rank[k] < rank["comment"]]
        merged += [("comment", x) for x in comments]
        merged += [(k, x) for k, x in found if rank[k] > rank["comment"]
                   and k not in ("usage", "placed")]
        # placed parts name the flag only in the high range (entity ids below
        # 3200 often double as unrelated event numbers)
        if flag >= LOCAL_SIZE or not merged:
            merged += [(k, x) for k, x in found if k == "placed"]
        if not merged:
            merged = [(k, x) for k, x in found if k == "usage"][:1]
        texts, seen = [], set()
        for _, x in merged:
            if x and x.lower() not in seen:
                seen.add(x.lower())
                texts.append(x)
        entry['descs'] = texts
        entry['kind'] = merged[0][0] if merged else "comment"
    for area_rows in local.values():
        for entry in area_rows.values():
            entry.setdefault('kind', "comment")
    for entry in global_.values():
        entry.setdefault('kind', "comment")

    resets = boss_resets(script_dir, local)
    forgiveness = parse_forgiveness(global_text, define['consts'])

    # ---- NPC state machines --------------------------------------------------
    state_ids = {fid for lst in define['lists'] for _, fid, _ in lst['states']}

    # ---- tendency pairs (dedup) ---------------------------------------------
    pairs, seen_pairs = [], set()
    for file_name, data in maps.items():
        for pair in data['qwc_pairs']:
            key = (pair['judge'], pair['flag'])
            if key not in seen_pairs:
                seen_pairs.add(key)
                area = area_of(file_name)
                if is_local(pair['flag']) and area in AREAS:
                    pair = {**pair, "area": area}
                pairs.append(pair)

    return {
        "areas": {str(k): {"name": v[0], "map": v[1]} for k, v in AREAS.items()},
        "backup_offset": define['backup_offset'],
        "bosses": [{"id": fid, "area": area, "name": name, "world": world,
                    "soul": soul, **resets[fid], **souls[fid]}
                   for fid, area, name, world, soul in BOSSES],
        "npcs": npcs,
        "forgiveness": forgiveness,
        "npc_state_ids": sorted(state_ids),
        "local_size": LOCAL_SIZE,
        "local_ranges": [list(r) for r in LOCAL_RANGES],
        "local": {str(area): [flags[k] for k in sorted(flags)]
                  for area, flags in sorted(local.items())},
        "global": [global_[k] for k in sorted(global_)],
        "scripts": [scripts[k] for k in sorted(scripts)],
        "local_any": [local_any[k] for k in sorted(local_any)],
        "talk_scripts": [{**s, "npc": speakers.get(s['script'], '')} for s in talks],
        "pickups": {str(area): {str(flag): rows[flag] for flag in sorted(rows)}
                    for area, rows in sorted(pickup_items.items())},
        "shops": shops,
        "itemlots": lots,
        "tendency_pairs": sorted(pairs, key=lambda p: (p['judge'], p['flag'])),
    }


def _count(db: dict) -> int:
    return (sum(len(v) for v in db['local'].values()) + len(db['global'])
            + len(db['scripts']))


def coverage(doc: dict, saves: list[Path], show: int = 25) -> None:
    """How many set flags of each save have a label, per range and source."""
    import des_flags
    import des_save
    db = des_flags.FlagDB(doc)
    kinds = {}
    for area, rows in doc['local'].items():
        for entry in rows:
            kinds[(int(area) - 1, entry['id'])] = entry.get('kind', 'comment')
    for path in saves:
        sf = des_save.load(str(path))
        rows = [(None, f) for f in des_flags.global_flags(sf)]
        for area in range(des_flags.AREAS):
            rows += [(area, f) for f in des_flags.local_flags(sf, area)]
        named = collections.Counter()
        total = collections.Counter()
        by_kind = collections.Counter()
        missing = []
        for area, flag in rows:
            group = 'global' if area is None else ('local low' if flag < LOCAL_SIZE
                                                   else 'local high')
            total[group] += 1
            if db.event_label(flag, area):
                named[group] += 1
                if area is not None:
                    by_kind[kinds.get((area, flag), 'other')] += 1
            else:
                missing.append(f"{'m%02d:' % (area + 1) if area is not None else ''}{flag}")
        print(f"{path}")
        for group in ('global', 'local low', 'local high'):
            if total[group]:
                print(f"  {group:<10} {named[group]:>4} / {total[group]:<4} labelled "
                      f"({100 * named[group] // total[group]}%)")
        all_named, all_total = sum(named.values()), sum(total.values())
        print(f"  {'all':<10} {all_named:>4} / {all_total:<4} labelled "
              f"({100 * all_named // max(all_total, 1)}%)")
        print("  local labels by source: " + ", ".join(f"{k} {n}" for k, n in by_kind.most_common()))
        if missing:
            print(f"  unlabelled ({len(missing)}): " + " ".join(missing[:show])
                  + (" …" if len(missing) > show else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game', type=Path, help='PPSA01341-app0 game folder')
    ap.add_argument('-o', '--out', type=Path, default=HERE / 'flagdb.json')
    ap.add_argument('--check', action='store_true',
                    help='verify the committed flagdb.json matches a rebuild')
    ap.add_argument('--coverage', type=Path, nargs='+', metavar='SAVE',
                    help='report how many set flags of these USR-DATA files have a label '
                         '(uses the rebuilt database; writes nothing)')
    args = ap.parse_args(argv)

    db = build(args.game)
    if args.coverage:
        coverage(db, args.coverage)
        return 0
    text = json.dumps(db, indent=1, ensure_ascii=False, sort_keys=False) + '\n'

    if args.check:
        current = args.out.read_text(encoding='utf-8') if args.out.exists() else ''
        if current == text:
            print(f"{args.out} matches the game files "
                  f"({_count(db)} flags, {len(db['npcs'])} NPCs, "
                  f"{len(db['bosses'])} bosses)")
            return 0
        print(f"{args.out} is stale; rebuild with "
              f"python3 tools/build_flagdb.py {args.game}", file=sys.stderr)
        return 1

    args.out.write_text(text, encoding='utf-8')
    print(f"{args.out}: {_count(db)} documented flags, "
          f"{len(db['npcs'])} NPC state machines, "
          f"{len(db['bosses'])} boss flags, "
          f"{len(db['tendency_pairs'])} tendency pairings")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
