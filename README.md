# Demon's Souls PS5 save editor

Open **`des_editor.html`** in a modern browser. It is a self-contained offline
editor for the **version-7 decrypted `USR-DATA` files** of `PPSA01341`. No
server, installation, game assets, or network access is needed to use the page.
Its content-security policy blocks network requests.

**Important:** the container can be parsed and rebuilt, but the game's entire
save schema has **not** been decoded. A checksum-valid file is not necessarily
a game-safe edit. Earlier claims that the full inventory was solved, that
unmapped IDs were invalid, or that storage contents were absent were too strong.
The editor now distinguishes observed structure from unverified interpretation.

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

## Views and workflows

| View | What it provides |
|---|---|
| **Editor** | Character, souls, base/current attributes, vitals, resistance, records, options, and coverage warnings |
| **All fields** | Named and unknown records, strict scalar/text/hex editing, filtering, 100 records per page |
| **Tree** | Container hierarchy and absolute file offsets, 200 records per page |
| **Field reference** | All 62 recovered names, hashes, descriptions, and values in the active file |
| **Item catalog** | All 2,291 category-scoped entries, including wide weapon/armor IDs, spells, and skills |
| **Changes** | Before/after comparison with the immutable original; export conflict-checked scalar patches |
| **JSON / patches** | Full dump, file import/export, plain field maps, and path-based patches |

Large binary fields open in a separate inspector instead of being converted to
huge hidden text inputs. The inspector supports strict hex edits and exact
binary download/import. It does **not** interpret unknown blob formats.

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
`USR-DATA` export rather than a scalar patch.

Full browser dumps retain keys, types, structure and complete scalar precision.
Non-finite float values and negative zero use hex to preserve their exact bits.
Applying an invalid dump never discards existing edits or modifies undo history.

## Coverage and important limits

- **Known character fields:** name, archetype ID, gender flag, character slot,
  souls/lifetime souls, all eight base/current attributes, HP/MP/stamina,
  recovery values, resistances, playtime, death/kill/clear counters and several
  flags. Hash matches establish candidate names, not every gameplay meaning.
- **Estimated soul level:** `sum(eight current attributes) - 80` (99 in every
  attribute gives 712). No independently identified soul-level field is edited.
  The previous `sum - 79` formula was off by one.
- **Playtime:** milliseconds; `3,600,000` is one hour.
- **Archetypes:** numeric IDs are editable, but class-name ordering is not
  verified. The page no longer presents an inferred mapping as fact.
- **Options:** recognized settings have forms; every other record remains
  available in All fields and JSON. Two further settings were recovered by
  hashing bare names against the executable's string table: `AUTOLOCK`
  (boolean, true here) and `CAMERASHAKE` (float, 1.0 here).
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
  same-size edits. Adding or removing items and changing item IDs are not
  offered: the roles of `_DISPLAYID` and `_VARIATIONID` are not verified. The
  `_COUNT` fields are read-only in the form.
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
- **What "append-only" means here.** A longer-played character held all 320
  records of a fresh one plus 706 more, and no record was missing. The save
  therefore accumulates records, which is why a before/after pair of the *same*
  character is the only reliable identification method.
- Only the sampled decrypted format is supported. This page does not decrypt,
  re-sign or import encrypted retail-console saves.
- Browser safety bounds: 16 MiB per save, 100,000 records, 64 container levels,
  32 loaded profiles, 64 MiB loaded originals/bundle. These are editor bounds.

## Recovered structures

Two independent techniques recover structure without knowing a single field
name, and both are implemented in `des_arrays.py` and in the page.

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

**Slot ordering matters.** The four u16 dead-enemy chunks do not label their slots with
plain digits: chunks 0 and 2 sit one below the plain prefix, so their characters
run `1,0,3,2,5,4,7,6,9,8`. The 40-key *set* is unchanged, but the index-to-key
map was wrong before this was measured, which meant "slot 0" addressed slot 1.
`slot_key(0)` is now `0x582724E7`, the first record in file order.

**Versioned blob containers.** The large opaque containers start with a 16-byte
header: `u32` version (3), `u32` count, then an 8-byte signature
`b13668df f82e7044`. The 239 KB container in the larger sample reports
`count 188`; the 296-byte one in the fresh character reports `count 2`. The
bodies also carry embedded `tag 7 / type 9 / key / int32` records that use the
same FNV key space, and those are listed in the `blobs` command. The rest of the
payload is dense (about 7.3 bits/byte, all 256 byte values present) with **no
compression and no encryption** — zlib/deflate fails at every offset and the
byte distribution is far from what either would produce. It is not a
fixed-stride table either: no periodicity from 16 to 256 bytes.

**Differential harness.** `des_diff.py` compares two saves record by record,
using `(key, occurrence)` identity so an insertion elsewhere never renumbers
anything, and reports added/removed/changed records plus any new digit-suffixed
array that appears among the added keys. This is the tool that turns a save pair
into evidence; tendency, equipment and spells will be identified with it, not
with more dictionaries.

## Command line

Python's standard library is sufficient:

```bash
python3 des_editor.py selftest ../_SaveData/PPSA01341
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
python3 des_editor.py arrays FILE
python3 des_editor.py aslot FILE 7516f500 --set 0=113 --clear 7 --out /tmp/USR-DATA
python3 des_editor.py blobs FILE
python3 des_editor.py diff BEFORE/USR-DATA AFTER/USR-DATA
```

`arrays` lists the recovered fixed-slot arrays with slot letters, values and
candidate names; `aslot` writes one slot by array state and suffix character
(the same letter the listing shows). `blobs` decodes the 16-byte container
header and lists the embedded typed records. `diff` prints the record-level
delta, so two saves of the same character can be compared directly:

```text
before    320 records     13709 bytes
after    1026 records    258582 bytes
added     706   removed     0   changed    64
```

`items` lists the inventory, storage box, equipment slots and the number of
dead-enemy indices. `inv` requires `--experimental` and only makes same-size
quantity and durability edits. `set`/`patch`/`inv` create a
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

The browser's binary model indexes fields by hash and path, caches serialized
snapshots by revision, and serializes into a preallocated typed buffer. Hidden
views are not rendered. Binary previews read only the first few bytes rather
than hex-encoding whole blobs on every refresh.

## Rebuild the catalog (optional)

The editor already embeds the catalog. Regeneration requires the game files:

```bash
python3 tools/build_itemdb.py /path/to/PPSA01342-app -o itemdb.json
python3 tools/embed_itemdb.py
```

Sources: `cp11demonssouls/dvdroot/param/gameparam/gameparam.parambnd` and
`text/ds/_cmn/*_name.en-gb.ctxt`. The builder retains `(category, id)` namespaces,
uses exact PARAM row IDs, and ignores unverified internal-name offsets.
Counts: Armor 147, Goods 157, Ring 35, Skill 28, Spell 40, Weapon 1884.
Catalog `hasParam` distinguishes rows backed by a parameter table from text-only
entries. Both tools offer stdout modes for reproducible build integration.

## Verification and performance

From the repository root. Tests that need real saves read `DES_SAVE_DIR`
(your `_SaveData/PPSA01341` copy) and are skipped, with the reason printed,
when it is not set:

```bash
# Standard-library tests only
python3 -m unittest discover -s tests -p test_save.py -v
# Full suite; requires Playwright and its Chromium browser in the test environment
python3 -m unittest discover -s tests -v
python3 tests/benchmark_editor.py
python3 tools/embed_fields.py --check   # page field table matches des_fields.py
python3 des_editor.py selftest ../_SaveData/PPSA01341
```

56 tests run in about 15 s (25 format/structure, 31 browser). Regression
coverage includes all three original files, malformed records, strict
numeric/hex bounds, atomic imports/writes, undo/redo, async-save races, JSON
drafts, category collisions, exact binary exports, ZIP contents/CRC, float bit
preservation, 100 seeded Python/JavaScript differential fixtures, and a check
that Python and the browser recover identical arrays on every sample. Tests
never edit the original saves.

On the 258,582-byte / 1,026-record sample, observed JavaScript refresh time went
from about **70.5 ms to 0.9 ms** (not a page-load/paint or game benchmark).
Inactive raw inputs dropped from **1,023 to zero**, and eagerly generated hidden
JSON from **609,779 characters to zero**. After cache warm-up, 100 unchanged
dirty checks perform **zero serializations**. Timings vary by machine; structural
performance assertions are tested instead of fragile wall-clock thresholds.
