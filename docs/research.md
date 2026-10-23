# Research notes

How the field names and structures in this editor were recovered, so that the
work can be repeated and extended.

[← Back to the README](../README.md)

## Names from the game files

Every key is FNV-1a 32 of an uppercase name, so any string the game ships is a
candidate. `tools/build_keydb.py` hashes the printable strings of the executable,
the prefab files (`scripts/**/*.cgpr`, `ui/scripts`), `misc/` and the param
definitions, and expands the executable's printf templates
(`Equipment_Inventory%02d_EquipId` → `…00_…` to `…99_…`; inventory and storage
names continue to `…2047_…`, the original game's 0x800-entry capacity). It prints
every match with the types and values seen in your saves. A match is a candidate
until its type and values fit; nothing is accepted automatically.

The accepted names live in `src/des_fields.py`, which also generates the page's table
(`tools/embed_fields.py`).

## Fixed-slot arrays by hash inversion

A member key is `(state ^ ord(suffix_character)) * 0x01000193`, so multiplying
the observed key by the modular inverse of the FNV prime (`0x359C449B`) and
XOR-ing a candidate character recovers the state that all members of one array
share. Grouping keys that resolve to the same state under a digit, then requiring
contiguous records with a constant stride, yields whole arrays even though the
base name is unknown. Six 32-bit arrays and the four u16 dead-enemy chunks came
out this way before their names were recovered from the executable.

The suffix character is only defined up to an XOR of the whole alphabet, so the
labelling is canonicalised to `0,1,2,...` and then to the smallest matching
state; Python and the browser return identical results on every sample. Canonical
letters do not follow the game's index order (slot `'0'` of `TROPHIES_RING##` is
`TROPHIES_RING06`), so listings also show each member's real field name.

### Slot ordering matters

The four u16 dead-enemy chunks do not label their slots with plain digits: chunks
0 and 2 sit one below the plain prefix, so their characters run
`1,0,3,2,5,4,7,6,9,8`. The 40-key *set* is unchanged, but the index-to-key map
was wrong before this was measured, which meant "slot 0" addressed slot 1.
`slot_key(0)` is now `0x582724E7`, the first record in file order; it hashes to
`DEADENEMIES_INDICES0000`.

## World state

Blob `6d87f588` is a sequence of groups (see [Save format](format.md#world-state-blobs)).

**Entity index.** `tools/build_entitydb.py` finds 499,123 GUIDs in the prefab
files, from index tables (`u32 n, GUID` runs) and reference structs
(`GUID, 8 bytes, 01, u32, FF FF FF FF, 00`, version and variant checked), plus the
baseline files. It maps each GUID to its defining file and each world folder to a
level label voted from `misc/dspointsofinterest.txt`. The result, `entitydb.bin`
(2.6 MiB), is embedded in the page as a non-executing data block (about 3.4 MB
encoded) and decoded only when the World state view first opens.

## Param definitions

`src/des_gamedata.py` reads the PARAMDEFs (0xB0-byte field records with byte sizes
and bit fields) and decodes PARAM rows through them, but only when a definition
accounts for exactly the PARAM row stride: 29 of 32 tables qualify, and NpcParam,
AtkParam and Magic, whose rows the remaster extended, are refused. Catalog schema
3 takes the classes and the item limits from them.

## Loadouts

`tools/parse_loadouts.py` reads the developers' 235 automation scripts in
`misc/loadouts/`. 6,424 of the IDs they add or equip resolve in the catalog under
the matching category (two do not: Official Cap and Moon Mace). The packaged game
does not appear to apply loadouts, so they are reference data, not a way to
create test saves.

## Differential harness

`src/des_diff.py` compares two saves record by record, using `(key, occurrence)`
identity so an insertion elsewhere never renumbers anything. It reports
added/removed/changed records plus any new digit-suffixed array that appears among
the added keys. Inside world-state containers it compares by
`(GUID, key, occurrence)`, so a changed flag is reported against its entity
instead of as "blob changed".

## Identifying a field

1. Back up the save. Load it in Kyty, change **one** thing in game (pick up an
   item, touch an archstone, open a door), and save.
2. `python3 src/des_editor.py diff BEFORE/USR-DATA AFTER/USR-DATA`
3. Read the changed records and world entities. Run
   `python3 tools/build_keydb.py GAME --save AFTER/USR-DATA` to try names for any
   key that is still unnamed, and look the entity GUID up with
   `python3 src/des_editor.py world AFTER/USR-DATA --filter GUID`.
4. Record the name in `src/des_fields.py` (or `WORLD_NAMES`), run
   `tools/embed_fields.py`, and add a test.

## Rebuilding the embedded tables

The editor already embeds everything it needs. Regeneration is optional and
requires the game files (`PPSA01342-app`):

```bash
python3 tools/build_itemdb.py /path/to/PPSA01342-app -o itemdb.json   # catalog, classes, limits
python3 tools/embed_itemdb.py
python3 tools/build_entitydb.py /path/to/PPSA01342-app -o entitydb.bin
python3 tools/embed_entitydb.py
python3 tools/embed_fields.py                                         # after editing src/des_fields.py
python3 tools/build_keydb.py /path/to/PPSA01342-app --save USR-DATA   # name candidates
python3 tools/parse_loadouts.py /path/to/PPSA01342-app                # loadout checks
```

Catalog sources: `gameparam.parambnd` with `paramdef.paramdefbnd`, and
`text/ds/_cmn/*_name.en-gb.ctxt`. The builder keeps `(category, id)` namespaces
and uses exact PARAM row IDs. Counts: Armor 147, Goods 157, Ring 35, Skill 28,
Spell 40, Weapon 1884. `hasParam` distinguishes rows backed by a parameter table
from text-only entries, and schema-4 rows additionally carry `sortId`, initial
`durability` and an `ammo` flag (weaponCategory 13/14) as the creation metadata
for add-item.

The embed tools offer `--stdout` or `--check` modes for reproducible builds
(`tools/embed_itemdb.py --check` covers the page block).
