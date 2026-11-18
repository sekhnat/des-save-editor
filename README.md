<div align="center">

<a href="https://github.com/sekhnat/des-save-editor/releases/latest"><img src="docs/assets/banner.svg" alt="Demon's Souls Save Editor" width="100%"></a>

<br>

**An offline save editor for *Demon's Souls* (2020) on PS5 — decrypted `USR-DATA`, title `PPSA01341`.**

[![Release](https://img.shields.io/github/v/release/sekhnat/des-save-editor?style=flat-square&label=release&color=c9a86a)](https://github.com/sekhnat/des-save-editor/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/sekhnat/des-save-editor/total?style=flat-square&color=8a8274)](https://github.com/sekhnat/des-save-editor/releases)
[![Build](https://img.shields.io/github/actions/workflow/status/sekhnat/des-save-editor/desktop.yml?style=flat-square&label=build)](https://github.com/sekhnat/des-save-editor/actions/workflows/desktop.yml)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20browser-555?style=flat-square)](#download)
[![Python](https://img.shields.io/badge/CLI-Python%203%20·%20stdlib%20only-3776ab?style=flat-square)](#command-line)
[![License](https://img.shields.io/github/license/sekhnat/des-save-editor?style=flat-square&color=555)](LICENSE)

[**Download**](#download) · [Quick start](#quick-start) · [Features](#features) · [Command line](#command-line) · [Documentation](#documentation)

</div>

---

## Overview

Demon's Souls Save Editor is a single self-contained page, `des_editor.html`, that
reads, edits and rebuilds **version-7 decrypted `USR-DATA`** files. The same page
ships as a desktop app for Windows, macOS and Linux, and a Python command-line
tool covers scripting and batch work.

| At a glance | |
|---|---|
| **Runs** | In any modern browser, as a desktop app, or from the command line |
| **Needs** | Nothing: no server, installation, game files or network access |
| **Network** | None. The page's content-security policy blocks every request |
| **Safety** | Loading never writes. Originals are kept, every edit can be undone, and exports are validated |
| **CLI** | Python 3 standard library only |

## Highlights

- **Easy and Advanced modes.** Easy covers what most people want: souls, name, class,
  attributes, world tendency and adding items. It shows a paper doll of the equipped
  gear and the game's own icon for every item. Advanced is the full editor. The page
  remembers your choice.
- **Character.** Name, class, souls, all eight attributes, vitals, resistances,
  spells and counters.
- **World tendency.** Set each world and the character anywhere from Pure Black to
  Pure White. See which of the 32 tendency events (black phantoms, NPCs, doors,
  treasure) are active, and trigger one by moving tendency into the range the game's
  own table requires.
- **Items.** Browse the inventory, storage box and equipment slots. Edit quantities
  and durability, change a weapon's upgrade level or path, and add items from a
  2,291-entry catalog.
- **Attributes.** Move points between attributes at the same soul level, or change
  the soul level.
- **Events.** See which bosses are dead and every NPC's quest state, respawn a
  boss or mark it defeated (its demon soul goes into your inventory), forgive a hostile NPC or put an NPC back into a quest state, see each
  map's pickups with their item icons, re-arm them or take the ones you missed
  (their items go into your inventory), one at a time or all at once, and browse or search every map's event flags (doors, levers,
  pickups, conversations) by name: about 94% of the flags an end-game save has
  set carry a description. Every recipe (respawn, mark defeated, NPC state,
  forgive, take, re-arm, reset a map) is confirmed in game; raw flag edits and
  re-arming a tendency event stay experimental.
- **World state.** Inspect per-entity records (archstones, boss loot, chains,
  statues), each labelled with its level and the game file that defines it.
- **Fully inspectable.** Tree view, raw field editing, JSON dumps, conflict-checked
  patches and a before/after diff.

## Verification status

Every edit below writes a checksum-valid file. Edits marked *verified* were also
loaded in the game (on the Kyty emulator): the menus showed them and the game's own
save kept them.

| Edit | Status |
|---|---|
| Inventory quantity and durability | ✅ Verified in game |
| Adding items to the inventory | ✅ Verified in game |
| Weapon upgrade level and path | ✅ Verified in game |
| Attribute redistribution at the same soul level | ✅ Verified in game |
| Event flags: respawn a boss, mark it defeated, NPC state, forgive, take, re-arm or reset a map's pickups | ✅ Verified in game: each was seen on screen against an unedited control (boss back or gone, Boldwin hostile then back at work, a pickup's glow gone and back) |
| Raw single-flag edits, re-arming a tendency event | ⚠️ Experimental, opt-in: the game keeps the bit, but what it does depends on the flag, and a tendency event repeating was not seen |
| Storage-box edits (quantity, adding items, weapon upgrades) | ✅ Verified in game, on Stockpile Thomas's storage screen |
| World-state edits (other than `BROKEN`) | ⚠️ Experimental, opt-in: no observed effect |
| Soul-level change, class change | ⏳ Not yet checked in game |

> [!WARNING]
> A checksum-valid file is not necessarily a game-safe edit. **Back up your entire
> `_SaveData` folder before you start.**

## Download

Get the latest build from the [**Releases**](https://github.com/sekhnat/des-save-editor/releases/latest)
page, or open `des_editor.html` from a checkout in any modern browser.

| Platform | File | Notes |
|---|---|---|
| Windows | `…-win-x64-portable.exe` or the `…-win-x64.exe` installer | Unsigned: SmartScreen may ask you to choose *More info → Run anyway* |
| macOS | `…-mac-arm64.dmg` (Apple silicon) or `…-mac-x64.dmg` (Intel) | Unsigned: right-click → **Open** the first time |
| Linux | `…-linux-x86_64.AppImage` | `chmod +x` it; needs `libfuse2` on newer distributions |

The desktop app is Electron hosting the unmodified `des_editor.html` with the
network blocked, so it behaves exactly like the page. Closing it with unexported
edits asks for confirmation.

## Quick start

1. **Back up** your entire `_SaveData` folder, with the game or emulator closed.
2. Open `des_editor.html` (or the desktop app) and choose **Choose folder… → `_SaveData`**.
   This keeps the original profile-folder names. Selecting files and dropping
   folders also work, and loading never writes anything.
3. Click **Original backup** for an exact download of the loaded bytes.
4. Make your edits. **Easy** mode (the default) covers souls, attributes, tendency
   and adding items. Switch to **Advanced** for every field, then review
   **Checks & coverage** and **Changes** there.
5. **Save file** writes through a browser save dialog where one is supported, and
   otherwise requests a download. Put the file back as **`USR-DATA`** in the correct
   `SAVEDATA0PlayerProfileN` or `SAVEDATA0OptionsProfile0` folder.
6. Or use **Save all (ZIP)** for one bundle holding every loaded profile's edited
   copy, its unmodified original and a mapping manifest. Confirm that the download
   completed before replacing files.

<details>
<summary>Exports and the ZIP bundle</summary>

The ZIP's `edited/` and `originals/` trees contain **only `USR-DATA` files**. Keep
your emulator `.blocks` capacity files and the rest of the original folder. When
bare files were loaded without their folders, the bundle uses descriptive
placeholder folders that you must match to the real profile folders yourself;
loading the full save folder avoids that ambiguity.

The loaded original is never replaced by an export. **Revert all** always restores
the original payload, even after several exports, and undo history survives
exports. The page warns before closing with unexported edits or unapplied drafts.
A browser download request cannot prove that the download actually completed.

</details>

## Features

### Easy mode

| View | What it provides |
|---|---|
| **Character** | A paper doll of the game icons for the worn head, body, arms and legs pieces and the L1/R1 hand items; name, class, souls with **Max souls**, and the eight attributes (keeping the total redistributes at the same soul level, changing it levels up or down). Equipped, inventory and storage-box tables sit side by side, each scrolling and filtering on its own, with an icon per item, editable stackable quantities and **+ Add** to the inventory or storage box |
| **Tendency** | Character and world sliders, presets and all-world buttons, without the event tables; which tendency-gated one-time events already happened, with **Re-arm** |
| **Events** | Bosses (alive or defeated, which demon soul and whether it was taken, **Respawn** and **Mark defeated**, which puts the soul in your inventory), each NPC's quest state as a picker with **Forgive** for hostile NPCs, and every map's **Pickups** with item icons, **Re-arm** and **Take** (a missed pickup's items go into your inventory); buttons marked ✓ work as is (seen in game), those marked EXP are behind an experimental toggle |

### Advanced mode

| View | What it provides |
|---|---|
| **Editor** | Character and class, souls, base and current attributes, vitals, resistances, spells, records, options and coverage warnings; attribute redistribution at the same soul level; inventory, storage box and equipment slots with **Add item…** and weapon upgrade levels and paths; recovered arrays |
| **Tendency** | Character and the five worlds on a −200 to 200 slider with band, presets and all-world buttons; every tendency event with its required range, live on/off status, **Trigger** (one or several at once) and the events a change turns on or off; the tendency-gated one-time events, whether each already happened, and **Re-arm** |
| **Events** | Bosses with their death and soul flags and the soul each gives, **Respawn**, **Full respawn** and **Mark defeated** (the demon soul and anything else the soul pickup gives go to the inventory); NPC quest states with **Forgive**; a **Pickups** list per map or across all maps (item icons, taken or not, **Re-arm** or **Take** one or all; Take puts the items in the inventory, and what goes past a stack's limit in the storage box, as in game); every map's flags (0–3199 and 8192–12287) and the save-wide flags with descriptions from the map layouts (pickups), talk tables and script comments, searchable per map or across all maps, with **Reset this map**; **Fix the copy** when the current map's flag copy disagrees with its slots; shop stock counters; set any flag by map and number. Buttons marked ✓ (every recipe, and fix) are confirmed in game; EXP edits are experimental |
| **All fields** | Named and unknown records with strict scalar, text and hex editing, filtering, 100 records per page |
| **Tree** | Container hierarchy and absolute file offsets, 200 records per page |
| **World state** | Every world-state entity with its level and defining game file, named records, filtering, 200 per page; opt-in same-size edits |
| **Field reference** | The 92 named fields with editor metadata, hashes, descriptions and values in the active file. A further 12,600 indexed family names and 19 world-state names label records in the other views |
| **Item catalog** | All 2,291 category-scoped entries, including wide weapon and armour IDs, spells and skills |
| **Changes** | Before/after comparison with the unmodified original; export conflict-checked scalar patches |
| **JSON / patches** | Full dump, file import and export, plain field maps and path-based patches |

### Item icons and the paper doll

Item icons are the game's own inventory icons, extracted from the remake's UI atlas
by `tools/build_icons.py` and embedded in the page: 475 icons covering 2,183 goods,
weapon, armour, ring and spell rows. Armour has male and female versions and follows
the save's gender. Rows without a game icon (unused data) fall back to an original
line drawing chosen by the item's type in the equip PARAMs (`weaponCategory`,
`protectorCategory`, `goodsType`, `accessoryCategory`). The character card shows the
worn armour's icons as a paper doll, and falls back to a drawn figure when there is
no icon to show.

The game fills an empty slot with a placeholder it names "No Equipment": bare hands,
and a bare head, body, arms and legs. The editor and the CLI label these by slot
("Bare head (No Equipment)") and give them a dashed empty-slot symbol instead of a
game icon, and the paper doll shows the slot as empty.

### Editing tools

- **Binary fields.** Large binary fields open in a separate inspector with strict hex
  edits and exact binary download and import. It does **not** interpret unknown blob
  formats; the world-state container has its own view.
- **Quick actions.** Max souls, refill effective HP/MP/stamina, copy current
  attributes to base attributes, and set attributes to 99 (with confirmation).
  Effective HP/MP maxima are *not* overwritten from base values automatically,
  because form, equipment and game rules can make them differ.
- **Shortcuts.** `Ctrl/Cmd+S` exports the active save. Outside text inputs,
  `Ctrl/Cmd+Z` undoes and `Ctrl/Cmd+Shift+Z` or `Ctrl+Y` redoes. `Esc` closes
  dialogs, `Tab` stays inside an open dialog, and arrow keys, `Home` and `End`
  move between the view tabs.

<details>
<summary>Undo, redo and drafts</summary>

Undo/redo groups typing within a focused field, creates no history entry merely for
focusing, and keeps redo until an actual edit. History is limited to 60 snapshots
and about 20 MiB per profile (at least one snapshot). JSON drafts survive tab and
profile changes; stale drafts are rejected rather than overwriting newer edits. Text
inputs and textareas keep native text undo.

</details>

### JSON and patches

Plain field maps are accepted by both the browser and the CLI:

```json
{"PLAYER_SOULS": 250000, "PLAYER_NAME": "Slayer"}
```

Raw four-byte and blob values use strict hex strings or `{"hex":"00112233"}`.
Unknown or ambiguous keys reject the **entire** patch. Repeated keys must be
addressed by path using a patch exported from **Changes**; those patches check key,
type, path and expected original bytes before anything is applied.

Structural changes, such as adding or removing array records, need a full
`USR-DATA` export rather than a scalar patch. Use **Add item…** (or the CLI `add`)
to create items instead of hand-crafting records.

Full browser dumps keep keys, types, structure and complete scalar precision;
non-finite floats and negative zero use hex to preserve their exact bits. Applying
an invalid dump never discards existing edits or changes undo history.

## Command line

The CLI needs only Python 3's standard library.

```bash
python3 src/des_editor.py selftest /path/to/_SaveData/PPSA01341   # check every file in a save folder
python3 src/des_editor.py info FILE                               # header, checksum, record counts
python3 src/des_editor.py items FILE [--json]                     # inventory, storage, equipment
python3 src/des_editor.py get FILE PLAYER_SOULS
python3 src/des_editor.py set FILE PLAYER_SOULS=250000 --out /tmp/USR-DATA
python3 src/des_editor.py add FILE weapon 20700                   # Dragon Bone Smasher
python3 src/des_editor.py add FILE ring 123                       # records trophy history
python3 src/des_editor.py upgrade FILE 12                         # levels and paths of inventory weapon 12
python3 src/des_editor.py upgrade FILE 12 20110                   # make it Broadsword+10
python3 src/des_editor.py respec FILE VIT=40 STR=30               # same soul level
python3 src/des_editor.py respec FILE VIT=45 --level              # soul level follows (not checked in game)
python3 src/des_editor.py world FILE --filter TEXT                # world-state entities
python3 src/des_editor.py tendency FILE                           # world/character tendency and events
python3 src/des_editor.py tendency FILE --trigger 20300           # tendency for one event
python3 src/des_editor.py events FILE                             # event flags: bosses, NPC quests
python3 src/des_editor.py events FILE --respawn phalanx           # make a boss alive again (seen working in game)
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
python3 src/des_editor.py inv FILE --qty 9=40 --durability 0=200 --out /tmp/USR-DATA
python3 src/des_editor.py inv FILE --box-qty 4=30 --out /tmp/USR-DATA
python3 src/des_editor.py add FILE weapon 20700                                      # Dragon Bone Smasher
python3 src/des_editor.py add FILE goods 1001 --to storage --quantity 30
python3 src/des_editor.py add FILE ring 123                                          # records trophy history
python3 src/des_editor.py upgrade FILE INDEX [NEW_ID] [--storage]
python3 src/des_editor.py respec FILE [VIT=40 STR=30 ...] [--out /tmp/USR-DATA]
python3 src/des_editor.py arrays FILE
python3 src/des_editor.py aslot FILE 7516f500 --set 0=113 --clear 7 --out /tmp/USR-DATA
python3 src/des_editor.py blobs FILE
python3 src/des_editor.py world FILE [--json] [--group N] [--filter TEXT]
python3 src/des_editor.py wset FILE b13668dff82e7044840eea38f10b0286 BOSS_LOOT_VISIBLE=1 --experimental --out /tmp/USR-DATA
python3 src/des_editor.py tendency FILE [--json]
python3 src/des_editor.py tendency --events
python3 src/des_editor.py tendency FILE --set boletaria=-200 --set character=180 --out /tmp/USR-DATA
python3 src/des_editor.py tendency FILE --trigger 20300 --trigger 30140 --out /tmp/USR-DATA
python3 src/des_editor.py events FILE [--json] [--filter TEXT]
python3 src/des_editor.py events --list
python3 src/des_editor.py events FILE --respawn BOSS [--full] --npc NPC=STATE --out /tmp/USR-DATA
python3 src/des_editor.py events FILE --set 4103=0 --set m02:200=0 --experimental --out /tmp/USR-DATA   # raw flags
python3 src/des_editor.py events FILE --defeat BOSS [--no-soul] --out /tmp/USR-DATA   # dead, soul into the inventory
python3 src/des_editor.py events FILE --forgive NPC --rearm-pickups m02 --reset-map m06 --out /tmp/USR-DATA
python3 src/des_editor.py events FILE --take-pickup m02:10240 [--take-pickups m02] --out /tmp/USR-DATA   # as if picked up
python3 src/des_editor.py events FILE --sync-copy --out /tmp/USR-DATA
python3 src/des_editor.py diff BEFORE/USR-DATA AFTER/USR-DATA [--json]
```

- `items` lists the inventory, storage box, equipment slots and the number of dead-enemy indices.
- `upgrade` without a new id lists the weapon's upgrade levels and paths; with one, it changes only the item id (and an equipped slot's id), as the game does. `respec` without assignments shows the attributes and the starting class's minimums; with them, it moves points while keeping the soul level, or with `--level` lets the soul level change.
- `arrays` lists the recovered fixed-slot arrays with family names, slot letters, real field names and values; `aslot` writes one slot by array state and suffix character (the letter the listing shows).
- `blobs` sizes every blob and summarises world-state containers; `world` lists their entities with level, file and named records; `wset` makes an experimental same-size edit of one record addressed by entity GUID and key.
- `tendency` shows the character and each world with its band and the events it enables; `--set` takes `character`, `character_lr` or a world (`boletaria`, `stonefang`, `latria`, `storms`, `valley`), `--trigger` an event number from `--events`, and a combination no value can satisfy is refused with the conflict.
- `events` reads the event flags the game's scripts set and test: which bosses are dead (with their soul-taken flags), every NPC's quest state, and a searchable list of what each flag means (`--filter`, `--list`). Flags 0–3199 and 8192–12287 belong to one map each, so `--set` names the map for them (`m02:200=0`). `--full` also clears a boss fight's own flags, `--defeat` marks a boss dead and adds its demon soul (and anything else its soul pickup gives) to the inventory, `--no-soul` sets only the death flag, `--forgive` replays the game's own forgiveness, `--rearm-pickups` and `--reset-map` work on one map, `--take-pickup AREA:ID` (or `--take-pickups AREA` for a whole map) does what picking a pickup up does (its items into the inventory, the overflow past a stack's limit into the storage box, its flag set), and `--sync-copy` rebuilds the current map's flag copy from its slots (what the game does on load). These options flip bits. The game keeps them (Kyty); every recipe (`--respawn`, `--defeat`, `--npc`, `--forgive`, `--take-pickup(s)`, `--rearm-pickups`, `--reset-map`) was seen working in game and `--sync-copy` matches what the game does, so they need no flag; raw `--set` stays behind `--experimental`, since what a flag does depends on the flag; the how and why is in [Event flags](docs/research-event-flags.md).
- `diff` prints the record-level and world-state delta, so two saves of the same character can be compared directly:

  ```text
  before    320 records     13709 bytes
  after    1026 records    258582 bytes
  added     706   removed     0   changed    64
  ```

</details>

`wset` and raw event flags (`events --set`) require `--experimental`. `add` creates a full `USR-DATA` through the same
validated path as the page. For in-place writes, `set`, `patch`, `inv`, `wset` and
`aslot` first create a collision-resistant timestamped backup (`set --no-backup` is
an explicit opt-out). Edited bytes are validated, written to a temporary file,
flushed and fsynced, then atomically replace the destination; failed edits leave the
destination untouched. Blob assignments are hex, not UTF-8 text.

## Documentation

| Document | Contents |
|---|---|
| [Coverage and limits](docs/coverage.md) | What is decoded and how far each part can be trusted: character, classes, options, inventory, adding items, arrays, tendency, world state, bounds |
| [Save format](docs/format.md) | Container layout, record types, world-state framing |
| [Research notes](docs/research.md) | How names and structures were recovered, how to identify a field, rebuilding the embedded tables and icons |
| [Event flags](docs/research-event-flags.md) | The decoded event-flag system: where the flags live, what they mean, respawning bosses and fixing NPC quests |
| [Development](docs/development.md) | Running the tests, benchmarks and the desktop app, and cutting a release |

## Scope

Only the sampled **decrypted** format is supported. This project does not decrypt,
re-sign or import encrypted retail-console saves. Apart from the embedded item icons
and the logo in the banner, it ships no game files.

## Credits and legal

This is an unofficial fan project. It is not affiliated with or endorsed by Sony
Interactive Entertainment, Bluepoint Games or FromSoftware. *Demon's Souls* is a
trademark of Sony Interactive Entertainment.

- Item icons are extracted from *Demon's Souls* (2020), © Sony Interactive
  Entertainment; they are shown for identification only.
- The banner's *Demon's Souls* logo is traced from a screenshot of the game's logo, © Sony Interactive
  Entertainment. Its subtitle is set in [Cinzel](https://fonts.google.com/specimen/Cinzel) by
  Natanael Gama under the SIL Open Font License 1.1.

## License

The code is released under the [MIT License](LICENSE).
