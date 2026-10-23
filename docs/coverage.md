# Coverage and limits

The container can be parsed and rebuilt, and most of a played profile can be
named and read: character, options, inventory, storage box, equipment, spells,
tendency and per-entity world state. A name recovered from a hash is still not
proof of gameplay meaning, and a checksum-valid file is not necessarily a
game-safe edit.

Edits beyond the character form are experimental and opt-in. Quantity,
durability and storage-quantity edits keep every record size. Item creation
inserts records that follow the layout measured from real saves but has not been
verified in game.

[← Back to the README](../README.md)

## Contents

- [Character](#character)
- [Options](#options)
- [Inventory, storage box and equipment](#inventory-storage-box-and-equipment)
- [Adding items](#adding-items)
- [Dead enemies, not inventory](#dead-enemies-not-inventory)
- [Catalog IDs](#catalog-ids)
- [Fixed-slot arrays](#fixed-slot-arrays)
- [Tendency and character-creator presets](#tendency-and-character-creator-presets)
- [World state](#world-state)
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
- Equipment slots reference inventory entries through their `_INDEX` value. Slot
  meanings (which hand, which quick slot) are not verified.
- `EQUIPMENT_INVENTORY_COUNT` is normally a top-level record, but the game also
  writes it as the last child of a top-level container that precedes the entries
  (container `0x4081F683` declaring 8 children instead of 5). Both layouts are
  accepted.

**Editing is experimental and opt-in:** inventory quantity (1–999) and
durability, and the storage low-quantity byte (1–255), as same-size edits. The
`_COUNT` fields are read-only in the form. Stack and durability maxima from the
equip PARAMs (`maxQuantity`, `maxStorageQuantity`, `durabilityMax`) are shown as
hints and enforced only by item creation; the samples' durabilities sit at or
below them.

## Adding items

Experimental and opt-in: enable the card's *Enable experimental …* toggle, then
use **Add item…** (or the CLI `add`).

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

- **Tendency:** `TENDENCY_PLAYER_BLACKWHITE/LEFTRIGHT` and seven
  `TENDENCY_WORLD##_BLACKWHITE/LEFTRIGHT` floats (observed −180 to 180).
- **Character-creator presets:** `CCSLOT_{GENDER,ANIMTYPE,VOICETYPE,FACEDATA}_##`
  in five slots; face data is an opaque blob.

## World state

The largest blob (key `6d87f588`) holds per-entity records keyed by entity GUIDs
from the game's prefab files: archstones, boss loot, broken objects, chains,
statues, moved objects' transforms. 431 of 437 entities in the larger sample are
labelled with their level and file. Names such as `BOSS_LOOT_VISIBLE` or
`O2110_0000_CHAINS_BOL_SAVE` come from the game's own strings; what changing them
does in game is not verified, so world edits are opt-in, same-size and
experimental. The blob framing is in [Save format](format.md#world-state-blobs).

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
