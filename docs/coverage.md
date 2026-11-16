# Coverage and limits

The container can be parsed and rebuilt, and most of a played profile can be
named and read: character, options, inventory, storage box, equipment, spells,
tendency (with the game's event conditions), event flags and per-entity world state. A name recovered from a hash is still not
proof of gameplay meaning, and a checksum-valid file is not necessarily a
game-safe edit.

Inventory quantity and durability edits, adding items to the inventory, weapon
upgrades and attribute redistribution were checked in the game on 2026-11-15
(Kyty, `tools/ingame_check.py`): the menus showed each edit and the game's own
save kept it (see [Research notes](research.md#in-game-checks)). Storage-box
edits were kept by the game's save but could not be seen on screen, and world
state is confirmed only for `BROKEN`; both stay experimental and opt-in.

[← Back to the README](../README.md)

## Contents

- [Character](#character)
- [Options](#options)
- [Inventory, storage box and equipment](#inventory-storage-box-and-equipment)
- [Adding items](#adding-items)
- [Weapon upgrades](#weapon-upgrades)
- [Attribute redistribution](#attribute-redistribution)
- [New Game+](#new-game)
- [Dead enemies, not inventory](#dead-enemies-not-inventory)
- [Catalog IDs](#catalog-ids)
- [Fixed-slot arrays](#fixed-slot-arrays)
- [Tendency and character-creator presets](#tendency-and-character-creator-presets)
- [World state](#world-state)
- [Event flags](#event-flags)
- [Append-only saves](#append-only-saves)
- [Supported formats and bounds](#supported-formats-and-bounds)

## Character

- **Known fields:** name, class, gender flag, character slot, souls and lifetime
  souls, all eight base/current attributes, HP/MP/stamina, recovery values,
  resistances, playtime, death/kill/clear counters and several flags. Hash
  matches establish names, not every gameplay meaning.
- **Estimated soul level:** `sum(eight current attributes) - 80` (99 in every
  attribute gives 712). No independently identified soul-level field is edited.
  The developers' loadout scripts confirm the formula: all 77 premade files named
  `_slNNN` have base stats summing to NNN + 80.
- **Playtime:** milliseconds; `3,600,000` is one hour.
- **Classes:** archetype N is `CharaInitParam` row 1000+N. The rows carry no
  name, so each is identified by its starting weapon:

  | Weapon | Class |
  |---|---|
  | Broadsword | Soldier |
  | Long Sword | Knight |
  | Battle Axe | Hunter |
  | Mace | Priest |
  | Short Sword | Magician |
  | Falchion | Wanderer |
  | Club | Barbarian |
  | Dagger | Thief |
  | Halberd | Temple Knight |
  | Rapier | Royalty |

  Both samples are archetype 9: the fresh character carries row 1009's exact base
  stats, and every attribute the others never levelled still matches it. One
  class has been observed in saves.

## Options

Recognized settings have forms; every other record remains available in **All
fields** and JSON. Settings recovered from the game's strings include `AUTOLOCK`,
`CAMERASHAKE`, `ADAPTIVETRIGGERS`, `AUTOEQUIPNEWITEMS`, `HUDBACKING`,
`SUBTITLEBACKING`, `MIDNIGHTMODE`, `RENDERCONFIG` and `MAPUID`. The type and value
of each fit a setting, but their effects are not verified.

## Inventory, storage box and equipment

Decoded from named records (`EQUIPMENT_INVENTORY##_*`, `EQUIPMENT_STORAGEBOX##_*`,
`EQUIPMENT_SLOT##_*`), whose names come from printf templates in the game
executable.

- The top four bits of `_TYPE` / `_EQUIPTYPEID` give the category (0 weapon,
  1 armor, 2 ring, 4 goods). With it, every item in both samples resolves to a
  catalog name.
- `_QUANTITY` holds a little-endian count.
- Equipment slots reference inventory entries through their `_INDEX` value. Seen
  in game: slot 0 is left hand 1, slot 1 right hand 1, slot 2 left hand 2 and
  slot 3 right hand 2. Other slot meanings are not verified.
- `EQUIPMENT_INVENTORY_COUNT` is normally a top-level record, but the game also
  writes it as the last child of a top-level container that precedes the entries
  (container `0x4081F683` declaring 8 children instead of 5). Both layouts are
  accepted.

**Editing:** inventory quantity (1–999) and durability are same-size edits,
confirmed in game. The storage low-quantity byte (1–255) is experimental and
opt-in: the game kept it, but the storage box was not opened in game. The
`_COUNT` fields are read-only in the form. Stack and durability maxima from the
equip PARAMs (`maxQuantity`, `maxStorageQuantity`, `durabilityMax`) are shown as
hints and enforced only by item creation; the samples' durabilities sit at or
below them.

## Adding items

Use **Add item…** (or the CLI `add`). Additions to the inventory were confirmed
in game: a weapon, an armor piece, a ring, a new goods stack and units added to
an existing stack all appeared in the menus, sorted where the game sorts them,
and survived the game's own save. Additions to the storage box were kept by the
game's save but not seen, so they need the *Enable experimental storage-box
edits* toggle (CLI: `--experimental`). Easy mode shows a warning when the storage
box is chosen instead, and turns the flag on for that file when the item is added.

- **What is offered.** Supported rows carry PARAM creation data, and the others
  are listed with the reason: weapons, armor, rings and goods with a usable sort
  ID, initial durability and quantity data.
- **Nothing is mutated.** Creation never changes the loaded save; it returns a
  candidate that you export explicitly.
- **Record layout.** Inventory entries use `INDEX == VARIATIONID ==` the lowest
  free 16-bit instance reference, checked against the inventory references,
  equipment slots and quick items (storage display words still carry freed
  references and reserve nothing). `DISPLAYID = (PARAM sortId << 16) | ref`.
- **Ordering.** Like the game, the entry is placed in ascending-reference order,
  so later entries move up one index (slots and quick items hold references and
  are unaffected). An inventory that is not already sorted is refused. The sort
  component comes from the same game PARAMs and is never recalculated on
  existing items.
- **Storage.** Directly created storage entries carry the observed `-1` display
  sentinel and only the low quantity byte.
- **Stacks.** Goods and ammunition add units to the destination's single matching
  stack, refusing ambiguous or over-cap stacks and storage stacks with a
  non-zero `HIGHQUANTITY`. Weapons, armor and rings are added one copy at a time.
- **Rings.** A newly recorded ring also appends its ID to the `TROPHIES_RING##`
  history and its count in the same atomic operation.
- **Refusals.** Layouts that do not match the measured framing are refused, never
  repaired: missing or duplicate counts, incomplete or ambiguous entries, nested
  family records, wrong ordering, and exhausted entry or reference bounds.

## Weapon upgrades

A weapon's upgrade levels and paths are separate catalog rows linked by the
EquipParamWeapon `originEquipWep` chain (Broadsword → Broadsword+1 … +10, and
Broadsword → Sharp Broadsword+1 …). The editor offers every row that shares the
weapon's unupgraded root and changes only the item id: `EQUIPID` in the
inventory, the low 28 bits of `EQUIPTYPEID` in storage, and an equipped weapon's
`EQUIPMENT_SLOT##_EQUIPMENTID`. `DISPLAYID` is left alone because the game does
the same: in real saves an upgraded weapon keeps the sort id from when it was
acquired (a Compound Short Bow+6 still carries the +0 bow's, a Crescent
Falchion+4 the Crescent Falchion+1's). Durability above the new maximum is
lowered to it.

Confirmed in game for the inventory: an equipped Large Sword of Moonlight+5
changed to +2 showed as +2 in right hand 1 and was kept. A storage-box upgrade
(Bastard Sword → +10) was kept but not seen, so it is experimental.

## Attribute redistribution

**Redistribute attributes** (CLI `respec`) moves points between the eight
`PLAYER_CURRENT*` attributes while their sum, and so the soul level, stays the
same. Each attribute stays between the starting class's value and 99. In game,
VIT 50 → 60 and STR 50 → 40 showed on the Status screen at the same soul level
and were kept. The game did **not** recompute the stored max HP, MP or stamina
on load or save (HP stayed 1,123), although item burden changed at once. The
`PLAYER_BASE*` records are left alone; their meaning is not established (one
sample holds base 30 with current 50).

A **level change** (Easy mode's attribute card when the total changes, CLI
`respec --level`) uses the same fields and bounds but lets the sum, and so the
soul level, change. It has **not** been checked in game yet.

## New Game+

Not editable. The exit screen shows *Games completed*, but neither `CLEARCOUNT`
(1 → 2) nor `CLEARSTATE` (1 → 2) changed it, although the game kept both values
in its save. The counter it displays is stored elsewhere.

## Dead enemies, not inventory

The u16 records once offered as an "experimental inventory" are
`DEADENEMIES_INDICES####` followed by `DEADENEMIES_COUNT` (key `CC62FF39`). The
measured key of the first record hashes to `DEADENEMIES_INDICES0000`. Their
values (including the former "unmapped" `127 128 129 …`) are enemy indices, not
item IDs. Item insertion into this list has been removed; it is shown read-only.

## Catalog IDs

IDs are category-specific. For example, Goods 1000 is Crescent Moon Grass while
Spell 1000 is Soul Arrow. They are separate records, never merged. Some rows are
unused, test or unlabelled data.

## Fixed-slot arrays

Arrays recovered by hash inversion now have names:

- `SPELLS_EQUIPPED##` and `MIRACLES_EQUIPPED##`: seven slots, `-1` empty.
- `TROPHIES_RING##` with `TROPHIES_RING_COUNT`: rings recorded for the trophy.
- `EQUIPMENT_EQUIPITEM##`: inventory refs of the quick items.

One four-slot array of small integers is still unnamed. Spell and miracle slot
counts are `SPELLS_SLOTSUNLOCKED` / `MIRACLES_SLOTSUNLOCKED`.

## Tendency and character-creator presets

The game calls tendency *QWC*. The character and each world have a white/black
axis and a left/right axis, each clamped to −200 (black / left) … 200 (white /
right).

| Record | Meaning |
|---|---|
| `TENDENCY_PLAYER_BLACKWHITE` | Character tendency; the in-game Tendency menu shows it |
| `TENDENCY_PLAYER_LEFTRIGHT` | Hidden character axis. Buying certain spells moves it left (−30 or −40 each, `ShopLineupParam.qwcId` → `QwcChange` 80000/80010); God's Wrath moves it right (+40). Only the Nexus dialogue flags read it |
| `TENDENCY_WORLD##_LEFTRIGHT` | **The world tendency the game uses and displays** |
| `TENDENCY_WORLD##_BLACKWHITE` | A copy: the game overwrites it with `_LEFTRIGHT` when it saves |

World slots are the remake's map number − 1: 1 Boletarian Palace (m02),
2 Shrine of Storms (m03), 3 Tower of Latria (m04), 4 Valley of Defilement (m05),
5 Stonefang Tunnel (m06). Slot 0 (the Nexus) and slot 6 carry no world events.
The editor reads `_LEFTRIGHT` and writes the same value to both fields. Both
the mapping and the field roles were measured in Kyty (see
[Research notes](research.md#tendency-qwc)).

- **Bands.** They follow the thresholds the game's judges use: Pure Black ≤ −180,
  Black ≤ −100, Neutral −49…49, White ≥ 100, Pure White ≥ 180, with "leaning"
  bands in between.
- **Events.** A script asks `IsSuccessQWC(id)`. Row `id` of `QwcJudge.param`
  gives an inclusive range for character WB/LR and area WB/LR, and the area is
  the world being played. `src/des_tendency.py` lists all 32 live call sites:
  - 4 character events, checked in the Nexus
  - 28 world events: soul monsters, ore spirits, black phantoms (Miralda,
    Satsuki, Vileidel, Selen, Garl Vinland, Scirvir), NPCs (Miralda, Selen,
    Scirvir), the execution-ground door, the 1-1 dragon, the Makoto and other
    treasure

  `tools/build_tendencydb.py GAME --check` verifies every range and call site
  against the game files. One commented-out call (the 3-1 key, judge 40140) is
  excluded.
- **Triggering an event** sets the tendency to the nearest value inside its
  range, 1 past a threshold (e.g. −181 for "−180 or lower"). The editor reports
  the other events this turns on or off, and refuses combinations that no value
  can satisfy. Events that remove an enemy "until killed" also depend on event
  flags, and a one-shot event that has already happened stays done: see
  [Event flags](research-event-flags.md), which decodes them and maps each
  tendency judge to the flags it drives.
- **When it takes effect.** The game applies world tendency when an area loads
  (`BP_ApplyPendingQwc` after an archstone warp; the Nexus on entry).
- **Verification status.** Verified in Kyty:
  - the game shows edited character and world values in the Tendency menu
  - it keeps an edited value through its own save
  - it rewrites `_BLACKWHITE` from `_LEFTRIGHT`

  The effect of each individual event comes from the scripts and was not
  observed in game.
- **Character-creator presets:** `CCSLOT_{GENDER,ANIMTYPE,VOICETYPE,FACEDATA}_##`
  in five slots; face data is an opaque blob.

## World state

The largest blob (key `6d87f588`) holds per-entity records keyed by entity GUIDs
from the game's prefab files: archstones, boss loot, broken objects, chains,
statues, moved objects' transforms. 431 of 437 entities in the larger sample are
labelled with their level and file. Names such as `BOSS_LOOT_VISIBLE` or
`O2110_0000_CHAINS_BOL_SAVE` come from the game's own strings. One record type
was seen working in game: setting `BROKEN` from 1 to 0 on the seven broken
objects at the 1-1 start put an intact wooden barricade back where the debris
lay, and the game kept the change. What changing the other records does is not
verified, so world edits stay opt-in, same-size and experimental. The blob framing is in [Save format](format.md#world-state-blobs).

## Event flags

The flags the game's scripts set and test (`SetEventFlag` / `IsCompleteEvent`):
boss deaths, NPC quest states, opened doors, one-shot pickups. They live as
plain bit fields (bit position = flag id) in three fixed-size blobs; the
primary one (`522ad995`, flags 0–18047) is proven against saves — boss flags
match the demon souls each save holds, every NPC shows exactly one quest state
matching its story progress, and a New Game+ wipes world flags but keeps the
Nexus's. Meanings come from the game's own scripts, compiled into
`flagdb.json` by `tools/build_flagdb.py`; the full story, the recipes
(respawn a boss, fix an NPC questline, re-collect a one-shot item) and the
open questions are in [Event flags](research-event-flags.md).

The `events` command reads them; `--respawn`, `--npc` and `--set` edit them
and are experimental (not yet checked in game). The two further flag banks
(`0af4946a`, `78a5c2d7`) are shown but not yet attributed.

## Append-only saves

A longer-played character held all 320 records of a fresh one plus 706 more, and
no record was missing. The save therefore accumulates records, which is why a
before/after pair of the *same* character is the only reliable identification
method (see [Research notes](research.md#identifying-a-field)).

## Supported formats and bounds

- Only the sampled decrypted format is supported. This project does not decrypt,
  re-sign or import encrypted retail-console saves.
- Browser safety bounds: 16 MiB per save, 100,000 records, 64 container levels,
  32 loaded profiles, 64 MiB loaded originals/bundle. These are editor bounds.
