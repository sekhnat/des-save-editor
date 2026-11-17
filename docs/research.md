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

## Tendency (QWC)

**Names.** The executable's printf templates `Tendency_World%02d_BlackWhite` /
`_LeftRight` name the save records. Its UI strings (`WorldStatus_BoletariaTendency`,
`cp11_tendency_world_current_0..5`) give six worlds. The Lua scripts call the
system *QWC* (`IsSuccessQWC`, `AddQWC`, `RecvGlobalQwc`).

**Conditions.** `gameparam.parambnd` carries `QwcJudge.param` (ranges) and
`QwcChange.param` (deltas). `des_gamedata.load_params` decodes both through
their PARAMDEFs. Judge IDs are grouped by map (ID / 10000: 1 Nexus, 2 Boletaria,
3 Shrine, 4 Latria, 5 Valley, 6 Stonefang). The scripts in
`cp11demonssouls/dvdroot/script/*.lua` are plain text (CP932, with machine
translated English comments) and say what each judge gates. Map-to-area labels
(m03_01 = 4-1, …) come from `misc/dspointsofinterest.txt`.
`tools/build_tendencydb.py GAME` prints the judge table and every uncommented
call site, and `--check` holds `src/des_tendency.py` to them.

**Kyty measurements (2026-11-15, Xvfb, a copy of the saves, restored and
verified afterwards).**

1. *Field roles.* A character was loaded with all seven `_BLACKWHITE` values
   set to one pattern and `_LEFTRIGHT` to another, then saved. The game rewrote
   every `_BLACKWHITE` with its `_LEFTRIGHT` value and left `_LEFTRIGHT`
   unchanged. The Tendency menu matched `_LEFTRIGHT`. The character's
   `TENDENCY_PLAYER_BLACKWHITE` = 200 showed as a Pure White character and was
   kept.
2. *Slot mapping.* Three boots, each writing ±200 to both fields of slot *i*
   by bit *k* of *i* + 1. The Tendency menu shows each world as a glowing
   white or a dark icon, and the three bits decode as Boletaria 1, Shrine 2,
   Latria 3, Valley 4, Stonefang 5, which is the remake's map number − 1.
3. *Persistence.* Boletaria at −200 and at +200, loaded in 1-1 and saved by
   the game: both values came back unchanged. No event-flag bits differed
   between the two runs, which fits the scripts re-evaluating these flags
   (`SingleReset`) on every load.

The game's Lua `print` output does not reach Kyty's log. Points of interest
from `dspointsofinterest.txt` are not in the save's coordinate space (a
character placed at one spawned out of bounds). So no individual event was
observed in game.

## In-game checks

`tools/ingame_check.py` applies edits with the CLI to a copy of the saves, boots
Demon's Souls on the Kyty emulator inside its own Xvfb server, drives the menus
with xdotool, takes screenshots, saves and exits, and judges each edit against
the file the game wrote. The original `_SaveData` is renamed aside with a
SHA-256 manifest and put back afterwards (see
[Development](development.md#in-game-checks)).

**Results (2026-11-15, character `DPG`, Royalty, SL 320, at the Gates of
Boletaria).** *Shown* means the edit was visible in a menu or the world; *kept*
means the game's own save still held it.

| Edit | Shown | Kept |
|---|---|---|
| Inventory quantity (Crescent Moon Grass 45 → 37) | quick-item count 37 | yes |
| Inventory durability (Kris Blade+5 120 → 61) | weapon list 61/120 | yes |
| Add a weapon (Broadsword) | weapon list 150/150 | yes |
| Add armor (Leather Cap) | armour list 400/400 | yes |
| Add a ring (Ring of Great Strength) and its trophy entry | ring list | yes |
| Add a new goods stack (Half Moon Grass ×3) | item list, in sort order | yes |
| Add to a goods stack (Throwing Knife 13 + 5) | item list 18 | yes |
| Upgrade an equipped weapon (Large Sword of Moonlight+5 → +2) | right hand 1 | yes |
| Attributes VIT 50 → 60, STR 50 → 40 | Status screen, SL 320 | yes |
| World state `BROKEN` 1 → 0 on seven 1-1 start objects | intact barricade | yes |
| Storage quantity, storage addition, storage upgrade | not opened | yes |
| `CLEARCOUNT` 1 → 2, `CLEARSTATE` 1 → 2 | *Games completed* stayed 1 | yes |

**Results (2026-11-17, character `LOL`, end-game, in Boletaria 1-3).** Event
flags ([Event flags](research-event-flags.md#in-game-check)):

| Edit | Shown | Kept |
|---|---|---|
| Respawn Phalanx (clear flags 4096 and 4103) | not visited | yes |
| Boletaria local flag 720 cleared in its slot and the current-map copy | not visited | yes |
| Boletaria local flag 1380 cleared in its slot only | not visited | yes; the game rebuilt the copy from the slot |

**Results (2026-11-17/18, `LOL` again, started at chosen spots with
`ingame_check.py`'s new `start`/`--start`, which moves the character with
Kyty's `set-map` and refills the flag copy from the new map's slots).**

| Edit | Shown | Kept |
|---|---|---|
| Respawn Phalanx (death + soul flags), start 14 m from its core | **yes**: fog gate up and Phalanx's health bar, where a no-edit control from the same spot shows an open archway | yes |
| Full respawn of Phalanx (also its fight and boss-room flags) | **yes**, the same | yes |
| m02 flag 10770 (high range, bank `78a5c2d7`) cleared in slot and copy | not visited | yes |
| m02 flag 10766 cleared in the `78a5c2d7` slot only | not visited | yes; the copy was rebuilt from the slot, as for the low range |
| Re-arm the Late Moon Grass pickup (m02 10242), 28 m ahead of the 1-1 start | no difference visible from the start, compared with a control | yes |
| Crestfallen Warrior (dead) set to "In the Nexus" | his spot was out of view | **advanced by the game**: it saved "Starting to fade away (late game)" with "In the Nexus" as the previous state, so it read the edited state and ran its own state change from there |

Further observations:

- **Equipment slots.** Slot 0 is left hand 1, slot 1 right hand 1, slot 2 left
  hand 2, slot 3 right hand 2.
- **Upgrades keep `DISPLAYID`.** Across the Kyty saves, 4 upgraded weapons carry
  a `DISPLAYID` sort component that matches an ancestor in their upgrade chain,
  never a different weapon, so the game changes only the item id when it
  upgrades.
- **Derived stats.** After the attribute edit, max HP stayed 1,123 in the menu
  and in the game's save; item burden changed (255 → 285). The game does not
  recompute stored maxima on load.
- **Autosave.** The game rewrites the profile while menus are open, so the
  harness judges the first write after its save-and-exit keys.
- **Title menu.** The smoke script's OCR can read the title menu mid-fade and
  miss *Continue*; a retry a few seconds later finds it.

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
python3 tools/build_tendencydb.py /path/to/PPSA01342-app --check      # tendency catalog vs game
python3 tools/build_flagdb.py /path/to/PPSA01341-app0                # event-flag database (see research-event-flags.md)
python3 tools/parse_loadouts.py /path/to/PPSA01342-app                # loadout checks
```

Catalog sources: `gameparam.parambnd` with `paramdef.paramdefbnd`, and
`text/ds/_cmn/*_name.en-gb.ctxt`. The builder keeps `(category, id)` namespaces
and uses exact PARAM row IDs. Counts: Armor 147, Goods 157, Ring 35, Skill 28,
Spell 40, Weapon 1884. `hasParam` distinguishes rows backed by a parameter table
from text-only entries, and schema-4 rows additionally carry `sortId`, initial
`durability` and an `ammo` flag (weaponCategory 13/14) as the creation metadata
for add-item. Schema 5 adds `kind`, the item type that picks the editor's glyph.
It comes from `weaponCategory` 0–14 (dagger, sword, thrust, curved, axe, hammer,
spear, polearm, catalyst, fist, bow, crossbow, shield, arrow, bolt),
`protectorCategory` 0–4 (head, body, arms, legs, hair), `goodsType` 0–3
(consumable, key, material, demonsoul) and `accessoryCategory` 0 (ring). These
meanings were matched against item names in the PS5 dump. Schema 6 adds
`placeholder` to the five empty-slot rows the game names "No Equipment"
(`des_gamedata.placeholder_items`): armour rows with sortId -1 and
equipModelId 0 (101700 head, 201700 body, 301500 arms, 401500 legs), and the
sortId -1 fist-category weapon that CharaInitParam puts in empty hands
(100300). Starting loadouts use 101700 as an empty helm and 100300 as an empty
hand. The page embeds the flag as row column 10.

The embed tools offer `--stdout` or `--check` modes for reproducible builds
(`tools/embed_itemdb.py --check` covers the page block).

```bash
python3 tools/build_icons.py --game /path/to/PPSA01341-app0 --report   # coverage only
python3 tools/build_icons.py --game /path/to/PPSA01341-app0            # writes iconpack.json (~45 s)
python3 tools/embed_icons.py                                           # ICONS block; --check to verify
```

## UI atlas and item icons

The remake ships no per-item icon files: its inventory icons live in the global
UI atlas (`src/des_uiatlas.py` reads it).

- `ui/textures/_ps5/global.ctal` is the sprite table: a length-prefixed atlas
  path (`$/ui/textures/_ps5/****/global_pages.ctxr`), a u32 count (1,229), then
  40-byte records `u32 name hash, 4 × (u, v) f32 corners, u32 page`.
- Sprite names are hashed with **FNV-1a 32 over the uppercased name** (the same
  hash as save keys): `TEX_INVICON_PLACEHOLDER`, `Tex_StatIcon_Weight` and the
  `Tex_InvIcon_*` names in eboot all match.
- `ui/textures/_ps5/_ps5/global_pages.ctxr` is a 0x4D-byte header followed by
  five 4096² RGBA8 pages (64 MiB each), in the GPU's standard 64 KiB tiling:
  128 × 128 texel blocks in row-major order, and within a block the byte address
  bits 2–15 come from x0 x1 y0 y1 y2 x2 y3 x3 y4 x4 y5 x5 y6 x6 (AMD's
  SW_64KB_S pattern for 4-byte texels). The decoder was checked by eye and by
  transparent sprite gutters.
- The inventory icons are named `Tex_InvIcon_<key>`. Most are 260 × 300
  tiles (483 of them); a few large weapons use bigger ones (Dragon Bone
  Smasher, Large Sword of Moonlight, the axes and Meat Cleaver 300 × 420,
  Shotel 300 × 400, the light crossbow 322 × 372, the heavy and gargoyle
  crossbows 500 × 500). Two unused ring rows name 2048 × 2048 placeholder
  sheets, which the builder skips (sprites over 512 px are not icons). The key comes from string fields the remake added to the
  equip PARAMs (8-byte pointers into each PARAM's string block, read by
  `des_gamedata.param_strings`):

  | Table | Key | Rows with an icon |
  |---|---|---|
  | Goods | `bpPreviewKey` | 146 / 149 |
  | Ring | `bpPreviewKey` | 31 / 33 |
  | Spell | pointer at row offset 48, past the 48-byte PARAMDEF (rows are 56 bytes) | 34 / 34 |
  | Weapon | `wp_a_<equipModelId:04d>_<bpPreviewSuffix>` | 1,866 / 1,882 |
  | Armour | `<hd\|bd\|am\|lg>_<m\|f>_<equipModelId:04d>_<bpPreviewSuffix[_Female]>`, or `_a_` (gender-neutral) for the enemy sets | 110 / 126 |

  The legacy `iconId` is not the key: Elixir and Bearbug Grains share iconId
  1036 but have different icons. The unmatched rows are unused or unlabelled
  data. The empty-slot placeholders are skipped on purpose: the bare head's
  sprite is blank and the others show the base underclothes, which would read
  as real gear. The nine standard tiles left over are other art.
- There is no 2D player or class portrait: the menus render the character in
  3D, and `charcreator.ctal` holds only face-feature thumbnails.
