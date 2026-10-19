# Demon's Souls PS5 save editor

Open **`des_editor.html`** in a modern browser. It is a self-contained offline
editor for **version-7 decrypted `USR-DATA` files** from the PS5 release of
Demon's Souls (title id `PPSA01341`). No server, installation, game assets, or
network access is needed to use the page; its content-security policy blocks
network requests.

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
Keep any emulator sidecar/capacity files and the rest of the original folder.
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
  available in All fields and JSON.
- **Observed u16 array:** 31 records followed by count key `CC62FF39` in the
  larger sample, zero records/count zero in the smaller sample. Candidate keys
  come from four observed hash groups. Add/replace/remove is **experimental and
  opt-in**, validates the entire operation before mutation, and inserts new
  records before the count even for an empty array. The editor supports 40
  candidate keys; **40 is not a verified game inventory limit**. The array's
  relationship to the general inventory is unresolved.
- **Catalog IDs are category-specific.** For example, Goods 1000 is Crescent
  Moon Grass while Spell 1000 is Soul Arrow. They are separate records, never
  merged. IDs above 65535 remain searchable; they cannot be put into u16 slots.
  Some rows are unused/test/unlabelled data. A catalog match is not proof that
  a save field encodes that item.
- **Unmapped values:** `127 128 129 130 140 146 152 153 159 171` in the observed
  array remain unresolved. Preserve them; absence from item tables does not
  prove they should be deleted.
- **Storage:** `EQUIPMENT_STORAGEBOX_COUNT` is read-only in the form. Storage
  contents may be in opaque or unidentified records. Changing a count alone
  does not add storage items. Equipment, stack quantities, learned spells,
  tendency, appearance and general progression are not fully mapped.
- Only the sampled decrypted format is supported. This page does not decrypt,
  re-sign or import encrypted retail-console saves.
- Browser safety bounds: 16 MiB per save, 100,000 records, 64 container levels,
  32 loaded profiles, 64 MiB loaded originals/bundle. These are editor bounds.

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
python3 des_editor.py items FILE
python3 des_editor.py inv FILE --experimental --add 113 --out /tmp/USR-DATA
```

`items` lists observed values and candidate names, not a proven full inventory.
The `inv` command requires `--experimental`. `set`/`patch`/`inv` create a
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

## Repository contents and provenance

```
des_editor.html      the editor (self-contained, offline)
des_editor.py        command line interface
des_save.py          parser / serializer / checksum library
des_fields.py        recovered field-name table
des_items.py         catalog access + experimental array helpers
des_crack.py         field-name brute-forcer used to recover the table
itemdb.json          category-scoped catalog (see below)
tools/               catalog build/embed scripts
tests/               test suites and a benchmark
```

**No save files, account data, or personal paths are included.** The repository
ships no `USR-DATA`, no `_SaveData` folder, and no extracted game assets.

`itemdb.json` contains 2,291 item identifiers and display names extracted from
the game's own parameter and localisation tables. It is included solely so the
editor can label values; it is factual catalogue metadata derived for
interoperability, not a redistribution of game assets. Demon's Souls and all
related names are trademarks of their respective owners. This project is
unaffiliated with and not endorsed by the rights holders. Remove `itemdb.json`
if you prefer to generate it yourself with `tools/build_itemdb.py`.

## License

MIT — see [LICENSE](LICENSE).

## Verification and performance

From `des-editor/`:

```bash
# Standard-library tests only (no fixture files needed)
python3 -m unittest discover -s tests -p test_save.py -v

# Browser tests: synthetic fixtures run out of the box, real-save tests skip
python3 -m unittest discover -s tests -v

# Point the integration tests and benchmark at your own backup
DES_SAVE_DIR=/path/to/_SaveData/PPSA01341 python3 -m unittest discover -s tests -v
DES_SAVE_DIR=/path/to/_SaveData/PPSA01341 python3 tests/benchmark_editor.py

python3 des_editor.py selftest /path/to/_SaveData/PPSA01341
```

`tests/test_editor.py` generates its saves in memory, so it needs no fixture
data. `tests/test_editor_samples.py` exercises the full editor against real
profiles and is skipped unless `DES_SAVE_DIR` points at a compatible save set;
it asserts the SHA-256 of every source file is unchanged after the run.

Regression coverage includes all three original files, malformed records,
strict numeric/hex bounds, atomic imports/writes, undo/redo, async-save races,
JSON drafts, category collisions, exact binary exports, ZIP contents/CRC,
float bit preservation, and 100 seeded Python/JavaScript differential fixtures.
Tests never edit the original saves.

On the 258,582-byte / 1,026-record sample, observed JavaScript refresh time went
from about **70.5 ms to 0.9 ms** (not a page-load/paint or game benchmark).
Inactive raw inputs dropped from **1,023 to zero**, and eagerly generated hidden
JSON from **609,779 characters to zero**. After cache warm-up, 100 unchanged
dirty checks perform **zero serializations**. Timings vary by machine; structural
performance assertions are tested instead of fragile wall-clock thresholds.
