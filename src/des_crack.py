#!/usr/bin/env python3
"""
Field-name cracker.

Every key in a Demon's Souls save is FNV-1a 32 of the field name in
UPPERCASE, so keys can be matched against candidate names:

    python3 des_crack.py USR-DATA                     # built-in vocabulary
    python3 des_crack.py USR-DATA --depth 2           # also "WORD_WORD"
    python3 des_crack.py USR-DATA --words words.txt   # your own word list
    python3 des_crack.py USR-DATA --game PPSA01342-app # strings from the game files

Names are tried as-is and with these prefixes, which is the convention the
game uses:  PLAYER_, PLAYER, PLAYER_BASE, PLAYER_CURRENT, PLAYER_MAX,
CHAR_, GAME_, WORLD_, STAT_ ...

Anything printed is a *candidate*: the hash matched, but a 32-bit hash has
collisions, so check that the value/type makes sense before trusting it.
"""

from __future__ import annotations

import argparse
import itertools
import os
from pathlib import Path
import sys

import des_save

PREFIXES = ["", "PLAYER_", "PLAYER", "PLAYER_BASE", "PLAYER_CURRENT",
            "PLAYER_MAX", "CHAR_", "CHARACTER_", "GAME_", "WORLD_", "STAT_",
            "ITEM_", "EQUIP_", "OPTION_", "SOUL_", "SOULS_"]

DEFAULT_WORDS = """
ABILITY ACQUIRED ACTIVE ADD AFTER ALL AMOUNT ARCHSTONE AREA ARMOR ARMOUR ARROW ATTACK
ATTRIBUTE ATTR AUDIO BASE BASIC BGM BLACK BLEED BLOOD BLUE BODY BONUS BOSS BOX BRIGHTNESS
CAMERA CAMERAMODE CAMERASPEED CAPACITY CHAR CHARACTER CLASS CLEAR CLEARBONUS CLEARCOUNT
CLEARITEM CLEARSTATE COLORBLIND COMPLETE CONFIG COUNT CURRENT CURSE DAMAGE DATA DEATH
DEATHS DEFAULT DEFEAT DEFENCE DEFENSE DEMON DEMONSKILLED DEXTERITY DEX DEATHCOUNT DISPLAY
DISPLAYBRIGHTNESS DURABILITY EFFECTS ENDURANCE END EXP EXPERIENCE EXTRA FAITH FIRE FLAG
FLOOR FORM FP FULL GAME GAMMA GOLD HARD HEAL HEALTH HP HUMAN HUMANITY ID INDEX
INTELLIGENCE INT INVENTORY INVERT ITEM ITEMS JOB KILL KILLBLACK KILLS LANG LANGUAGE LAST
LEVEL LUCK LV MAGIC MAX MAXHP MAXMP MAXSP MIN MP NAME NUMBER ORDER PASSWORD PLAY PLAYER
PLAYTIME POINT POINTS POISON PLAGUE POSITION POWER PRICE PROFILE PROGRESS RANK RATE RECORD
REGEN RESIST RESISTANCE REST RING RINGS ROTATION SAVE SCALE SCORE SELL SETTING SFX SHOP
SHOPLEVEL SILVER SIZE SLOT SOUL SOULS SOUND SOUNDTYPE SPEED SPELL SP SPIRIT STAGE STAMINA
STATE STAT STATUS STOCK STONE STORAGE STRENGTH STR SUBTITLES TARGET TENDENCY TEXT TIME
TOTAL TREASURE TRUE TRUEDEATHCOUNT TYPE USED USER VALUE VERSION VISITS VOICE VOLUME
VOLUMEEFFECTS VOLUMEMUSIC VOLUMEVOICE WEAPON WEIGHT WHITE WORLD X Y Z
""".split()


def collect(path: str):
    sf = des_save.load(path)
    keys = {}
    for f, _ in sf.walk():
        keys.setdefault(f.key, f)
    return sf, keys


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="brute force field names against a save file")
    ap.add_argument("file")
    ap.add_argument("--words", help="extra word list (one per line)")
    ap.add_argument("--depth", type=int, default=1, help="1 or 2 words per name")
    ap.add_argument("--all", action="store_true", help="also show keys that stayed unknown")
    ap.add_argument("--game", help="also try every string harvested from this game folder "
                                   "(single names only; see tools/build_keydb.py)")
    a = ap.parse_args(argv)

    sf, keys = collect(a.file)
    words = [w.upper() for w in DEFAULT_WORDS]
    if a.words:
        with open(a.words, encoding="utf-8") as fh:
            words += [ln.strip().upper() for ln in fh if ln.strip()]
    words = sorted(set(words))

    found = {}
    if a.game:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import build_keydb
        for name in build_keydb.harvest(Path(a.game)):
            h = des_save.fnv1a(name.encode("ascii"))
            if h in keys:
                found[h] = name
    states = [(des_save.fnv1a(p.encode()), p) for p in PREFIXES]
    for w in words:                                   # single word
        for h0, pre in states:
            h = des_save.fnv1a(w.encode(), h0)
            if h in keys:
                found[h] = pre + w
    if a.depth >= 2:
        for w1, w2 in itertools.product(words, words):
            for h0, pre in states:
                h = des_save.fnv1a((w1 + "_" + w2).encode(), h0)
                if h in keys and h not in found:
                    found[h] = f"{pre}{w1}_{w2}"
                h = des_save.fnv1a((w1 + w2).encode(), h0)
                if h in keys and h not in found:
                    found[h] = f"{pre}{w1}{w2}"

    print(f"{a.file}: {len(keys)} unique keys, {len(found)} matched")
    for key in sorted(found):
        f = keys[key]
        val = f.text() if f.is_text else (
            f"{f.value:.4f}" if f.is_float else f.value)
        print(f"  {key:08X}  {found[key]:<40} t{f.type:02x}  {val}")
    if a.all:
        rest = [k for k in keys if k not in found]
        print(f"\n{len(rest)} unmatched keys: " + " ".join(f"{k:08X}" for k in sorted(rest)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
