# Demon's Souls PS5 save editor

Open **`des_editor.html`** in a modern browser. It is a self-contained offline
editor for the **version-7 decrypted `USR-DATA` files** of `PPSA01341`. No
server, installation, game assets, or network access is needed to use the page.
Its content-security policy blocks network requests.

**Important:** the container can be parsed and rebuilt, and most of a played
profile can now be named and read: character, options, inventory, storage box,
equipment, spells, tendency and per-entity world state. A name recovered from a
hash is still not proof of gameplay meaning, and a checksum-valid file is not
necessarily a game-safe edit. Edits beyond the character form are experimental
and opt-in: quantity/durability and storage-quantity edits keep every record
size, and item creation inserts records that follow the layout measured from
real saves but has not been verified in game. Earlier versions offered the
dead-enemy list as an "experimental inventory"; that was wrong (see
*Dead enemies, not inventory* below).

## Quick start

1. Close the game/emulator and back up your entire `_SaveData` folder.
2. Open `des_editor.html`. Prefer **Choose folder… → `_SaveData`** so the
   original profile-folder names are retained. File selection and folder drops
   also work; nothing is written merely by loading a file.
3. Click **Original backup** for an exact download of the loaded bytes.
4. Edit fields and review **Checks & coverage** and **Changes**.
5. **Save file** writes through a browser save dialog when supported, otherwise
   requests a download. Restore the filename to **`USR-DATA`** in the correct
   `SAVEDATA0PlayerProfileN` or `SAVEDATA0OptionsProfile0` folder.
6. Alternatively, **Save all (ZIP)** downloads one bundle containing every
   loaded profile's edited copy, immutable original, and a mapping manifest.
   Confirm the download completed before replacing files.

The ZIP's `edited/` and `originals/` trees contain **only USR-DATA files**.
Keep your emulator `.blocks` capacity files and the rest of the original folder.
When bare files were loaded without their folders, the bundle uses descriptive
placeholder folders; match them to the real profile folders yourself. Loading
the full save folder avoids that ambiguity.

The loaded original is never replaced by an export. **Revert all** always
restores the original payload, even after several exports. Undo history survives
exports. The page warns before closing with unexported edits or unapplied drafts.
A browser download request cannot prove that the download actually completed.

## Desktop app

The same editor is also packaged as a desktop app (Electron hosting the
unmodified `des_editor.html`, with the network blocked) for Windows, Linux and
macOS. Download it from the repository's **Releases** page:

| Platform | File | Notes |
|---|---|---|
| Windows | `…-win-x64-portable.exe` or the `…-win-x64.exe` installer | Unsigned: SmartScreen may ask you to choose *More info → Run anyway* |
| Linux | `…-linux-x86_64.AppImage` | `chmod +x` it; needs `libfuse2` on newer distributions |
| macOS | `…-mac-x64.dmg` / `…-mac-arm64.dmg` | Unsigned: right-click → **Open** the first time |

The desktop app behaves exactly like the page: all the workflows below apply,
and closing it with unexported edits asks for confirmation. To run it from a
checkout: `cd desktop && npm ci && npm start`. Maintainers: pushing a `v*` tag
makes `.github/workflows/desktop.yml` test, build and publish the release; other
pushes upload the builds as workflow artifacts.

## Views and workflows

| View | What it provides |
|---|---|
| **Editor** | Character and class, souls, base/current attributes, vitals, resistance, spells and tendency, records, options, coverage warnings; inventory, storage box and equipment slots with experimental **Add item…**; recovered arrays |
| **All fields** | Named and unknown records, strict scalar/text/hex editing, filtering, 100 records per page |
| **Tree** | Container hierarchy and absolute file offsets, 200 records per page |
| **World state** | Every world-state entity with its level and defining game file, named records, filtering, 200 per page; opt-in same-size edits |
| **Field reference** | The 78 named fields with editor metadata, hashes, descriptions and values in the active file. A further 12,600 indexed family names and 19 world-state names label records in the other views |
| **Item catalog** | All 2,291 category-scoped entries, including wide weapon/armor IDs, spells, and skills |
| **Changes** | Before/after comparison with the immutable original; export conflict-checked scalar patches |
| **JSON / patches** | Full dump, file import/export, plain field maps, and path-based patches |

Large binary fields open in a separate inspector instead of being converted to
huge hidden text inputs. The inspector supports strict hex edits and exact
binary download/import. It does **not** interpret unknown blob formats; the
world-state container has its own view.

Undo/redo groups typing within a focused field, creates no history entry merely
for focusing, and preserves redo until an actual edit. History is limited to
60 snapshots and approximately 20 MiB per profile (at least one snapshot).
JSON drafts survive tab/profile changes; stale drafts are rejected rather than
overwriting newer edits. Text inputs and textareas retain native text undo.

**Shortcuts:** Ctrl/Cmd+S exports the active save. Outside text inputs,
Ctrl/Cmd+Z undoes and Ctrl/Cmd+Shift+Z or Ctrl+Y redoes. Escape closes dialogs;
Tab stays inside an open dialog. Arrow keys, Home and End navigate the view tabs.

Quick actions: max souls, refill effective HP/MP/stamina, copy current attributes
to base attributes, and set attributes to 99 with confirmation. Effective
HP/MP maxima are **not** automatically overwritten from base values: form,
equipment and game rules can make those values differ.

### JSON and patches

Plain field maps are accepted by both browser and CLI:

```json
{"PLAYER_SOULS": 250000, "PLAYER_NAME": "Slayer"}
```

Raw four-byte/blob values use strict hex strings or `{"hex":"00112233"}`.
Unknown or ambiguous keys reject the **entire** patch. Repeated keys must be
addressed by path using a patch exported from **Changes**; those patches check
key, type, path and expected original bytes before applying anything.
Structural changes, such as adding/removing array records, require a full
`USR-DATA` export rather than a scalar patch. Use the editor's **Add item…**
action (or the CLI `add`) for item creation instead of hand-crafting records.

Full browser dumps retain keys, types, structure and complete scalar precision.
Non-finite float values and negative zero use hex to preserve their exact bits.
Applying an invalid dump never discards existing edits or modifies undo history.

## Coverage and important limits

- **Known character fields:** name, class, gender flag, character slot,
  souls/lifetime souls, all eight base/current attributes, HP/MP/stamina,
  recovery values, resistances, playtime, death/kill/clear counters and several
  flags. Hash matches establish names, not every gameplay meaning.
- **Estimated soul level:** `sum(eight current attributes) - 80` (99 in every
  attribute gives 712). No independently identified soul-level field is edited.
  The developers' loadout scripts confirm the formula: all 77 premade files
  named `_slNNN` have base stats summing to NNN + 80.
- **Playtime:** milliseconds; `3,600,000` is one hour.
- **Classes:** archetype N is `CharaInitParam` row 1000+N. The rows carry no
  name, so each is identified by its starting weapon (Broadsword → Soldier,
  Long Sword → Knight, Battle Axe → Hunter, Mace → Priest, Short Sword →
  Magician, Falchion → Wanderer, Club → Barbarian, Dagger → Thief, Halberd →
  Temple Knight, Rapier → Royalty). Both samples are archetype 9: the fresh
  character carries row 1009's exact base stats, and every attribute the others
  never levelled still matches it. One class has been observed in saves.
- **Options:** recognized settings have forms; every other record remains
  available in All fields and JSON. Settings recovered from the game's strings
  include `AUTOLOCK`, `CAMERASHAKE`, `ADAPTIVETRIGGERS`, `AUTOEQUIPNEWITEMS`,
  `HUDBACKING`, `SUBTITLEBACKING`, `MIDNIGHTMODE`, `RENDERCONFIG` and `MAPUID`;
  the type and value of each fit a setting, but their effects are not verified.
- **Inventory, storage box and equipment:** decoded from named records
  (`EQUIPMENT_INVENTORY##_*`, `EQUIPMENT_STORAGEBOX##_*`, `EQUIPMENT_SLOT##_*`),
  whose names come from printf templates in the game executable. The top four
  bits of `_TYPE` / `_EQUIPTYPEID` give the category (0 weapon, 1 armor,
  2 ring, 4 goods), and with it every item in both samples resolves to a
  catalog name. `_QUANTITY` holds a little-endian count. Equipment slots
  reference inventory entries through their `_INDEX` value; slot meanings
  (which hand, which quick slot) are not verified.
- **Inventory editing is experimental and opt-in:** inventory quantity
  (1–999) and durability, and the storage low-quantity byte (1–255), as
  same-size edits. The `_COUNT` fields are read-only in the form. Stack and
  durability maxima from the equip PARAMs (`maxQuantity`, `maxStorageQuantity`,
  `durabilityMax`) are shown as hints and enforced only by item creation; the
  samples' durabilities sit at or below them.
- **Adding items is experimental and opt-in** (the card's *Enable experimental
  …* toggle, then **Add item…**, or the CLI `add`). Supported rows carry PARAM
  creation data and are offered with a reason otherwise: weapons, armor, rings
  and goods with a usable sort ID, initial durability and quantity data.
  Creation never mutates the loaded save; it returns a candidate that you
  export explicitly. It preserves the measured record layout: inventory entries
  use `INDEX == VARIATIONID ==` the lowest free 16-bit instance reference
  (checked against the inventory references, equipment slots and quick items;
  storage display words still carry freed references and reserve nothing) and
  `DISPLAYID = (PARAM sortId << 16) | ref`. Like the game, the entry is placed
  in ascending-reference order, so later entries move up one index (slots and
  quick items hold references and are unaffected); an inventory that is not
  already sorted is refused. The sort component comes from the same game PARAMs and is never
  recalculated on existing items. Directly created storage entries carry the
  observed `-1` display sentinel and only the low quantity byte. Goods and
  ammunition add units to the destination's single matching stack (refusing
  ambiguous or over-cap stacks, and storage stacks with a non-zero
  `HIGHQUANTITY`); weapons, armor and rings are added one copy at a time. A
  newly recorded ring also appends its ID to the `TROPHIES_RING##` history and
  its count in the same atomic operation. Layouts that do not match the
  measured framing (missing/duplicate counts, incomplete or ambiguous entries,
  nested family records, wrong ordering, exhausted entry or reference bounds)
  are refused, never repaired.
- **Dead enemies, not inventory.** The u16 records once offered as an
  "experimental inventory" are `DEADENEMIES_INDICES####` followed by
  `DEADENEMIES_COUNT` (key `CC62FF39`). The measured key of the first record
  hashes to `DEADENEMIES_INDICES0000`. Their values (including the former
  "unmapped" `127 128 129 …`) are enemy indices, not item IDs. Item insertion
  into this list has been removed; it is shown read-only.
- **Catalog IDs are category-specific.** For example, Goods 1000 is Crescent
  Moon Grass while Spell 1000 is Soul Arrow. They are separate records, never
  merged. Some rows are unused/test/unlabelled data.
- **Fixed-slot arrays** recovered by hash inversion now have names:
  `SPELLS_EQUIPPED##` and `MIRACLES_EQUIPPED##` (seven slots, `-1` empty),
  `TROPHIES_RING##` with `TROPHIES_RING_COUNT` (rings recorded for the
  trophy), and `EQUIPMENT_EQUIPITEM##` (inventory refs of the quick items).
  One four-slot array of small integers is still unnamed. Spell and miracle
  slot counts are `SPELLS_SLOTSUNLOCKED` / `MIRACLES_SLOTSUNLOCKED`.
- **Tendency:** `TENDENCY_PLAYER_BLACKWHITE/LEFTRIGHT` and seven
  `TENDENCY_WORLD##_BLACKWHITE/LEFTRIGHT` floats (observed −180 to 180).
- **Character-creator presets:** `CCSLOT_{GENDER,ANIMTYPE,VOICETYPE,FACEDATA}_##`
  in five slots; face data is an opaque blob.
- **World state:** the largest blob (key `6d87f588`) holds per-entity
  records keyed by entity GUIDs from the game's prefab files: archstones, boss
  loot, broken objects, chains, statues, moved objects' transforms. 431 of 437
  entities in the larger sample are labelled with their level and file. Names
  such as `BOSS_LOOT_VISIBLE` or `O2110_0000_CHAINS_BOL_SAVE` come from the
  game's own strings; what changing them does in game is not verified, so
  world edits are opt-in, same-size and experimental.
- **What "append-only" means here.** A longer-played character held all 320
  records of a fresh one plus 706 more, and no record was missing. The save
  therefore accumulates records, which is why a before/after pair of the *same*
  character is the only reliable identification method.
- Only the sampled decrypted format is supported. This page does not decrypt,
  re-sign or import encrypted retail-console saves.
- Browser safety bounds: 16 MiB per save, 100,000 records, 64 container levels,
  32 loaded profiles, 64 MiB loaded originals/bundle. These are editor bounds.

## How names and structures were recovered

**Names from the game files.** Every key is FNV-1a 32 of an uppercase name, so
any string the game ships is a candidate. `tools/build_keydb.py` hashes the
printable strings of the executable, the prefab files (`scripts/**/*.cgpr`,
`ui/scripts`), `misc/` and the param definitions, and expands the executable's
printf templates (`Equipment_Inventory%02d_EquipId` → `…00_…` to `…99_…`; inventory and
storage names continue to `…2047_…`, the original game's 0x800-entry capacity). It
prints every match with the types and values seen in your saves. A match is a
candidate until its type and values fit; nothing is accepted automatically.
The accepted names live in `des_fields.py`, which also generates the page's
table (`tools/embed_fields.py`).

**Fixed-slot arrays by hash inversion.** A member key is
`(state ^ ord(suffix_character)) * 0x01000193`, so multiplying the observed key
by the modular inverse of the FNV prime (`0x359C449B`) and XOR-ing a candidate
character recovers the state that all members of one array share. Grouping
keys that resolve to the same state under a digit, then requiring contiguous
records with a constant stride, yields whole arrays even though the base name
is unknown. Six 32-bit arrays and the four u16 dead-enemy chunks came out this
way before their names were recovered from the executable.

The suffix character is only defined up to an XOR of the whole alphabet, so the
labelling is canonicalised to `0,1,2,...` and then to the smallest matching
state; Python and the browser return identical results on every sample.
Canonical letters do not follow the game's index order (slot `'0'` of
`TROPHIES_RING##` is `TROPHIES_RING06`), so listings also show each member's
real field name.

**Slot ordering matters.** The four u16 dead-enemy chunks do not label their slots with
plain digits: chunks 0 and 2 sit one below the plain prefix, so their characters
run `1,0,3,2,5,4,7,6,9,8`. The 40-key *set* is unchanged, but the index-to-key
map was wrong before this was measured, which meant "slot 0" addressed slot 1.
`slot_key(0)` is now `0x582724E7`, the first record in file order; it hashes to
`DEADENEMIES_INDICES0000`.

**World state.** Blob `6d87f588` is a sequence of groups,
`u32 version (3) | u32 count | count × entry`, and each entry is
`16-byte entity GUID | u32 kind | u32 length | typed record stream`. The record
streams use the same format and key space as the outer save. The 8 bytes once
reported as a container "signature" (`b13668df f82e7044`) are the first half of
the archstone entity's GUID. Every sample blob and all 166 baseline files the
game ships in `misc/cachedsavedata/` decode and rebuild byte-identically.
Entries that are not a record stream (an unknown type `0x10`, header-only
containers) keep their raw bytes. Kinds 7, 8 and 13 are preserved without
interpretation.

**Entity index.** `tools/build_entitydb.py` finds 499,123 GUIDs in the
prefab files, from index tables (`u32 n, GUID` runs) and reference structs
(`GUID, 8 bytes, 01, u32, FF FF FF FF, 00`, version and variant checked), plus
the baseline files. It maps each GUID to its defining file and each world
folder to a level label voted from `misc/dspointsofinterest.txt`. The result,
`entitydb.bin` (2.6 MiB), is embedded in the page and decoded only when the
World state view first opens.

**Param definitions.** `des_gamedata.py` reads the PARAMDEFs (0xB0-byte field
records with byte sizes and bit fields) and decodes PARAM rows through them,
but only when a definition accounts for exactly the PARAM row stride: 29 of 32
tables qualify, and NpcParam, AtkParam and Magic, whose rows the remaster
extended, are refused. Catalog schema 3 takes the classes and the item limits
from them.

**Loadouts.** `tools/parse_loadouts.py` reads the developers' 235 automation
scripts in `misc/loadouts/`. 6,424 of the IDs they add or equip resolve in the
catalog under the matching category (two do not: Official Cap and Moon Mace).
The packaged game does not appear to apply loadouts, so they are reference data,
not a way to create test saves.

**Differential harness.** `des_diff.py` compares two saves record by record,
using `(key, occurrence)` identity so an insertion elsewhere never renumbers
anything, and reports added/removed/changed records plus any new digit-suffixed
array that appears among the added keys. Inside world-state containers it
compares by `(GUID, key, occurrence)`, so a changed flag is reported against its
entity instead of as "blob changed".

### Identifying a field

1. Back up the save. Load it in Kyty, change **one** thing in game (pick up an
   item, touch an archstone, open a door), and save.
2. `python3 des_editor.py diff BEFORE/USR-DATA AFTER/USR-DATA`
3. Read the changed records and world entities. Run
   `python3 tools/build_keydb.py GAME --save AFTER/USR-DATA` to try names for
   any key that is still unnamed, and look the entity GUID up with
   `python3 des_editor.py world AFTER/USR-DATA --filter GUID`.
4. Record the name in `des_fields.py` (or `WORLD_NAMES`), run
   `tools/embed_fields.py`, and add a test.

## Command line

Python's standard library is sufficient:

```bash
python3 des_editor.py selftest /path/to/_SaveData/PPSA01341
python3 des_editor.py info FILE
python3 des_editor.py list FILE
python3 des_editor.py tree FILE
python3 des_editor.py fields
python3 des_editor.py get FILE PLAYER_SOULS
python3 des_editor.py set FILE PLAYER_SOULS=250000 --out /tmp/USR-DATA
python3 des_editor.py set FILE 0x637eb85e=1
python3 des_editor.py patch FILE edits.patch.json --out /tmp/USR-DATA
python3 des_editor.py dump FILE dump.json
python3 des_editor.py verify FILE
python3 des_editor.py items FILE [--json]
python3 des_editor.py inv FILE --experimental --qty 9=40 --durability 0=200 --box-qty 4=30 --out /tmp/USR-DATA
python3 des_editor.py add FILE weapon 20700 --experimental                       # Dragon Bone Smasher
python3 des_editor.py add FILE goods 1001 --to storage --quantity 30 --experimental
python3 des_editor.py add FILE ring 123 --experimental                           # records trophy history
python3 des_editor.py arrays FILE
python3 des_editor.py aslot FILE 7516f500 --set 0=113 --clear 7 --out /tmp/USR-DATA
python3 des_editor.py blobs FILE
python3 des_editor.py world FILE [--json] [--group N] [--filter TEXT]
python3 des_editor.py wset FILE b13668dff82e7044840eea38f10b0286 BOSS_LOOT_VISIBLE=1 --experimental --out /tmp/USR-DATA
python3 des_editor.py diff BEFORE/USR-DATA AFTER/USR-DATA [--json]
```

`arrays` lists the recovered fixed-slot arrays with family names, slot letters,
real field names and values; `aslot` writes one slot by array state and suffix
character (the same letter the listing shows). `blobs` sizes every blob and
summarises world-state containers; `world` lists their entities with level,
file and named records, and `wset` makes an experimental same-size edit of one
record addressed by entity GUID and key. `diff` prints the record-level and
world-state delta, so two saves of the same character can be compared directly:

```text
before    320 records     13709 bytes
after    1026 records    258582 bytes
added     706   removed     0   changed    64
```

`items` lists the inventory, storage box, equipment slots and the number of
dead-enemy indices. `inv`, `add` and `wset` require `--experimental`; `add`
creates a full USR-DATA via the same validated path as the page (backed up and
atomically replaced when it writes in place). `set`/`patch`/`inv`/`wset`/`aslot` create a
collision-resistant timestamped backup for in-place writes (`set --no-backup`
is an explicit opt-out). Edited bytes are validated, written to a temporary
file, flushed/fsynced, then atomically replace the destination. Failed edits
leave the destination untouched. Blob assignments are hex, not UTF-8 text.

## Format notes

All multibyte numeric fields below are little-endian unless marked opaque.

```
+0x00  u32  version = 7
+0x04  u32  FNV-1a 32 of payload
+0x08  u32  payload byte length
+0x0c  u32  marker = 1 in all samples
+0x10       typed record stream
```

Each record begins with `u32 key | u8 type`. Candidate names hash as
`FNV-1a(UPPERCASE(name))`. Containers contain a LEB128 record count; strings and
blobs contain a LEB128 byte length. Parsers validate every read, length, count,
and depth. Noncanonical encodings that cannot round-trip are flagged.

| Type | Value |
|---|---|
| `02` | u8 |
| `03` | u16 |
| `04` | Exactly four opaque bytes; never assume they are a little-endian integer |
| `06` | Container with LEB128 child count |
| `08` | **Signed** i32; `ffffffff` reads as -1 |
| `0a` | IEEE-754 float32 |
| `0c` | Byte/boolean |
| `0d` | UTF-8 string bytes |
| `0e` | Opaque binary bytes |

World-state blobs (see *World state* above) nest further record streams:

```
group  := u32 version (3) | u32 count | count × entry
entry  := 16-byte entity GUID | u32 kind | u32 length | <length bytes of records>
```

The browser's binary model indexes fields by hash and path, caches serialized
snapshots by revision, and serializes into a preallocated typed buffer. Hidden
views are not rendered. Binary previews read only the first few bytes rather
than hex-encoding whole blobs on every refresh.

## Rebuild the embedded tables (optional)

The editor already embeds everything it needs. Regeneration requires the game
files (`PPSA01342-app`):

```bash
python3 tools/build_itemdb.py /path/to/PPSA01342-app -o itemdb.json   # catalog, classes, limits
python3 tools/embed_itemdb.py
python3 tools/build_entitydb.py /path/to/PPSA01342-app -o entitydb.bin
python3 tools/embed_entitydb.py
python3 tools/embed_fields.py                                         # after editing des_fields.py
python3 tools/build_keydb.py /path/to/PPSA01342-app --save USR-DATA   # name candidates
python3 tools/parse_loadouts.py /path/to/PPSA01342-app                # loadout checks
```

Catalog sources: `gameparam.parambnd` with `paramdef.paramdefbnd`, and
`text/ds/_cmn/*_name.en-gb.ctxt`. The builder keeps `(category, id)`
namespaces and uses exact PARAM row IDs. Counts: Armor 147, Goods 157, Ring 35,
Skill 28, Spell 40, Weapon 1884. `hasParam` distinguishes rows backed by a
parameter table from text-only entries, and schema-4 rows additionally carry
`sortId`, initial `durability` and an `ammo` flag (weaponCategory 13/14) as the
creation metadata for add-item. The embed tools offer `--stdout` or `--check`
modes for reproducible builds (`tools/embed_itemdb.py --check` covers the page
block).

## Verification and performance

From the repository root. Tests that need real saves read `DES_SAVE_DIR`
(your `_SaveData/PPSA01341` copy), and tests that need the game files read
`DES_GAME_DIR` (the `PPSA01342-app` folder). They are skipped, with the reason
printed, when those are not set:

```bash
# Standard-library tests only
python3 -m unittest discover -s tests -p test_save.py -v
# Full suite; requires Playwright and its Chromium browser in the test environment
python3 -m unittest discover -s tests -v
python3 tests/benchmark_editor.py
python3 tools/embed_fields.py --check     # page field table matches des_fields.py
python3 tools/embed_entitydb.py --check   # page carries the current entity index
python3 des_editor.py selftest /path/to/_SaveData/PPSA01341
```

157 tests run in about 30 s without the optional fixture environment (most of
them format/structure/tools and browser flows). Regression
coverage includes all three original files, malformed records, strict
numeric/hex bounds, atomic imports/writes, undo/redo, async-save races, JSON
drafts, category collisions, exact binary exports, ZIP contents/CRC, float bit
preservation, 100 seeded Python/JavaScript differential fixtures, world-state
framing on every sample and all 166 game baselines, PARAMDEF layouts, loadout
checks, and Python/browser agreement on arrays, inventory, world state and
entity labels. Tests never edit the original saves.

On the 258,582-byte / 1,026-record sample, observed JavaScript refresh time went
from about **70.5 ms to 0.9 ms** (not a page-load/paint or game benchmark).
Inactive raw inputs dropped from **1,023 to zero**, and eagerly generated hidden
JSON from **609,779 characters to zero**. After cache warm-up, 100 unchanged
dirty checks perform **zero serializations**. With the inventory card, the
editor view renders in about 6.6 ms on the machine used for that change
(4.1 ms there before the card). The 3.4 MB embedded entity index is a
non-executing data block, decoded only when the World state view opens.
Timings vary by machine; structural performance assertions are tested instead
of fragile wall-clock thresholds.
