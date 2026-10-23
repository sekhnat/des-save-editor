<div align="center">

<img src="desktop/build/icons/128x128.png" alt="" width="96" height="96">

# Demon's Souls Save Editor

**An offline editor for decrypted PS5 `USR-DATA` saves of Demon's Souls (`PPSA01341`).**

[![Release](https://img.shields.io/github/v/release/sekhnat/des-save-editor?label=release)](https://github.com/sekhnat/des-save-editor/releases/latest)
[![Build](https://github.com/sekhnat/des-save-editor/actions/workflows/desktop.yml/badge.svg)](https://github.com/sekhnat/des-save-editor/actions/workflows/desktop.yml)
[![License](https://img.shields.io/github/license/sekhnat/des-save-editor)](LICENSE)

[Download](#download) · [Quick start](#quick-start) · [Features](#features) · [Command line](#command-line) · [Documentation](#documentation)

</div>

---

A single self-contained page (`des_editor.html`) that reads, edits and rebuilds
**version-7 decrypted `USR-DATA`** files. It needs no server, installation, game
assets or network access, and its content-security policy blocks network
requests. The same page is also packaged as a desktop app for Windows, Linux and
macOS, and a standard-library Python CLI covers scripting.

## Highlights

- **Character**: name, class, souls, all eight attributes, vitals, resistances, spells, tendency and counters.
- **Items**: browse the inventory, storage box and equipment slots, edit quantities and durability, and add items from a 2,291-entry catalog.
- **World state**: inspect per-entity records (archstones, boss loot, chains, statues) labelled with their level and defining game file.
- **Safe by default**: nothing is written by loading a file, the original bytes are always kept, every edit has undo/redo, and exports are validated before they are offered.
- **Everything is inspectable**: full tree view, raw field editing, JSON dumps, conflict-checked patches and a before/after diff.

> [!WARNING]
> A checksum-valid file is not necessarily a game-safe edit. Character-form
> edits are the best understood. Everything beyond it, such as quantity and
> durability edits, **item creation** and **world-state edits**, is experimental
> and opt-in: it follows the layout measured from real saves but has not been
> verified in game. Back up your entire `_SaveData` folder first.

## Download

Get the latest build from the [**Releases**](https://github.com/sekhnat/des-save-editor/releases/latest) page,
or just open `des_editor.html` from a checkout in any modern browser.

| Platform | File | Notes |
|---|---|---|
| Windows | `…-win-x64-portable.exe` or the `…-win-x64.exe` installer | Unsigned: SmartScreen may ask you to choose *More info → Run anyway* |
| Linux | `…-linux-x86_64.AppImage` | `chmod +x` it; needs `libfuse2` on newer distributions |
| macOS | `…-mac-x64.dmg` / `…-mac-arm64.dmg` | Unsigned: right-click → **Open** the first time |

The desktop app is Electron hosting the unmodified `des_editor.html` with the
network blocked, so it behaves exactly like the page. Closing it with unexported
edits asks for confirmation.

## Quick start

1. **Back up** your entire `_SaveData` folder, with the game or emulator closed.
2. Open `des_editor.html` (or the desktop app) and choose **Choose folder… → `_SaveData`**.
   This retains the original profile-folder names. File selection and folder drops
   also work, and nothing is written merely by loading a file.
3. Click **Original backup** for an exact download of the loaded bytes.
4. Edit fields, then review **Checks & coverage** and **Changes**.
5. **Save file** writes through a browser save dialog where supported, otherwise
   it requests a download. Put the file back as **`USR-DATA`** in the correct
   `SAVEDATA0PlayerProfileN` or `SAVEDATA0OptionsProfile0` folder.
6. Or use **Save all (ZIP)** for one bundle holding every loaded profile's edited
   copy, its immutable original and a mapping manifest. Confirm the download
   completed before replacing files.

<details>
<summary>Details about exports and the ZIP</summary>

The ZIP's `edited/` and `originals/` trees contain **only `USR-DATA` files**. Keep
your emulator `.blocks` capacity files and the rest of the original folder. When
bare files were loaded without their folders, the bundle uses descriptive
placeholder folders that you must match to the real profile folders yourself;
loading the full save folder avoids that ambiguity.

The loaded original is never replaced by an export. **Revert all** always
restores the original payload, even after several exports, and undo history
survives exports. The page warns before closing with unexported edits or
unapplied drafts. A browser download request cannot prove that the download
actually completed.

</details>

## Features

| View | What it provides |
|---|---|
| **Editor** | Character and class, souls, base/current attributes, vitals, resistance, spells and tendency, records, options and coverage warnings; inventory, storage box and equipment slots with experimental **Add item…**; recovered arrays |
| **All fields** | Named and unknown records with strict scalar, text and hex editing, filtering, 100 records per page |
| **Tree** | Container hierarchy and absolute file offsets, 200 records per page |
| **World state** | Every world-state entity with its level and defining game file, named records, filtering, 200 per page; opt-in same-size edits |
| **Field reference** | The 78 named fields with editor metadata, hashes, descriptions and values in the active file. A further 12,600 indexed family names and 19 world-state names label records in the other views |
| **Item catalog** | All 2,291 category-scoped entries, including wide weapon/armor IDs, spells and skills |
| **Changes** | Before/after comparison with the immutable original; export conflict-checked scalar patches |
| **JSON / patches** | Full dump, file import/export, plain field maps and path-based patches |

Large binary fields open in a separate inspector with strict hex edits and exact
binary download/import. It does **not** interpret unknown blob formats; the
world-state container has its own view.

**Quick actions:** max souls, refill effective HP/MP/stamina, copy current
attributes to base attributes, and set attributes to 99 (with confirmation).
Effective HP/MP maxima are *not* overwritten automatically from base values,
because form, equipment and game rules can make them differ.

**Shortcuts:** `Ctrl/Cmd+S` exports the active save. Outside text inputs,
`Ctrl/Cmd+Z` undoes and `Ctrl/Cmd+Shift+Z` or `Ctrl+Y` redoes. `Esc` closes
dialogs, `Tab` stays inside an open dialog, and arrow keys, `Home` and `End`
navigate the view tabs.

<details>
<summary>Undo, redo and drafts</summary>

Undo/redo groups typing within a focused field, creates no history entry merely
for focusing, and preserves redo until an actual edit. History is limited to 60
snapshots and about 20 MiB per profile (at least one snapshot). JSON drafts
survive tab and profile changes; stale drafts are rejected rather than
overwriting newer edits. Text inputs and textareas keep native text undo.

</details>

### JSON and patches

Plain field maps are accepted by both the browser and the CLI:

```json
{"PLAYER_SOULS": 250000, "PLAYER_NAME": "Slayer"}
```

Raw four-byte and blob values use strict hex strings or `{"hex":"00112233"}`.
Unknown or ambiguous keys reject the **entire** patch. Repeated keys must be
addressed by path using a patch exported from **Changes**; those patches check
key, type, path and expected original bytes before anything is applied.

Structural changes, such as adding or removing array records, need a full
`USR-DATA` export rather than a scalar patch. Use **Add item…** (or the CLI
`add`) for item creation instead of hand-crafting records.

Full browser dumps retain keys, types, structure and complete scalar precision;
non-finite floats and negative zero use hex to preserve their exact bits.
Applying an invalid dump never discards existing edits or modifies undo history.

## Command line

Python's standard library is sufficient.

```bash
python3 src/des_editor.py selftest /path/to/_SaveData/PPSA01341   # check every file in a save folder
python3 src/des_editor.py info FILE                               # header, checksum, record counts
python3 src/des_editor.py items FILE [--json]                     # inventory, storage, equipment
python3 src/des_editor.py get FILE PLAYER_SOULS
python3 src/des_editor.py set FILE PLAYER_SOULS=250000 --out /tmp/USR-DATA
python3 src/des_editor.py add FILE weapon 20700 --experimental    # Dragon Bone Smasher
python3 src/des_editor.py add FILE goods 1001 --to storage --quantity 30 --experimental
python3 src/des_editor.py add FILE ring 123 --experimental        # records trophy history
python3 src/des_editor.py world FILE --filter TEXT                # world-state entities
python3 src/des_editor.py diff BEFORE/USR-DATA AFTER/USR-DATA     # record-level delta
```

<details>
<summary>All commands</summary>

```bash
python3 src/des_editor.py selftest /path/to/_SaveData/PPSA01341
python3 src/des_editor.py info FILE
python3 src/des_editor.py list FILE
python3 src/des_editor.py tree FILE
python3 src/des_editor.py fields
python3 src/des_editor.py get FILE PLAYER_SOULS
python3 src/des_editor.py set FILE PLAYER_SOULS=250000 --out /tmp/USR-DATA
python3 src/des_editor.py set FILE 0x637eb85e=1
python3 src/des_editor.py patch FILE edits.patch.json --out /tmp/USR-DATA
python3 src/des_editor.py dump FILE dump.json
python3 src/des_editor.py verify FILE
python3 src/des_editor.py items FILE [--json]
python3 src/des_editor.py inv FILE --experimental --qty 9=40 --durability 0=200 --box-qty 4=30 --out /tmp/USR-DATA
python3 src/des_editor.py add FILE weapon 20700 --experimental                       # Dragon Bone Smasher
python3 src/des_editor.py add FILE goods 1001 --to storage --quantity 30 --experimental
python3 src/des_editor.py add FILE ring 123 --experimental                           # records trophy history
python3 src/des_editor.py arrays FILE
python3 src/des_editor.py aslot FILE 7516f500 --set 0=113 --clear 7 --out /tmp/USR-DATA
python3 src/des_editor.py blobs FILE
python3 src/des_editor.py world FILE [--json] [--group N] [--filter TEXT]
python3 src/des_editor.py wset FILE b13668dff82e7044840eea38f10b0286 BOSS_LOOT_VISIBLE=1 --experimental --out /tmp/USR-DATA
python3 src/des_editor.py diff BEFORE/USR-DATA AFTER/USR-DATA [--json]
```

- `items` lists the inventory, storage box, equipment slots and the number of dead-enemy indices.
- `arrays` lists the recovered fixed-slot arrays with family names, slot letters, real field names and values; `aslot` writes one slot by array state and suffix character (the letter the listing shows).
- `blobs` sizes every blob and summarises world-state containers; `world` lists their entities with level, file and named records; `wset` makes an experimental same-size edit of one record addressed by entity GUID and key.
- `diff` prints the record-level and world-state delta, so two saves of the same character can be compared directly:

  ```text
  before    320 records     13709 bytes
  after    1026 records    258582 bytes
  added     706   removed     0   changed    64
  ```

</details>

`inv`, `add` and `wset` require `--experimental`. `add` creates a full `USR-DATA`
through the same validated path as the page. For in-place writes, `set`, `patch`,
`inv`, `wset` and `aslot` first create a collision-resistant timestamped backup
(`set --no-backup` is an explicit opt-out). Edited bytes are validated, written to
a temporary file, flushed and fsynced, then atomically replace the destination;
failed edits leave the destination untouched. Blob assignments are hex, not UTF-8
text.

## Documentation

| Document | Contents |
|---|---|
| [Coverage and limits](docs/coverage.md) | What is decoded and how far each part can be trusted: character, classes, options, inventory, adding items, arrays, world state, bounds |
| [Save format](docs/format.md) | Container layout, record types, world-state framing |
| [Research notes](docs/research.md) | How names and structures were recovered, how to identify a field, rebuilding the embedded tables |
| [Development](docs/development.md) | Running the tests, benchmarks and the desktop app, and cutting a release |

## Scope

Only the sampled **decrypted** format is supported. This project does not decrypt,
re-sign or import encrypted retail-console saves, and it ships no game assets.

## License

[MIT](LICENSE)
