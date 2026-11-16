# Event flags

How the save's event-flag system was decoded: where the flags live, how a flag
number maps to a bit, what the flags mean, and what that makes possible. The
runtime side is `src/des_flags.py`; the meanings are compiled into
`flagdb.json` by `tools/build_flagdb.py`.

[← Back to the README](../README.md) · [Research notes](research.md) · [Coverage and limits](coverage.md)

## What was found

The game's Lua scripts (`cp11demonssouls/dvdroot/script/*.lua`) drive every
story event through numbered flags: `proxy:SetEventFlag(id, value)` sets one,
`proxy:IsCompleteEvent(id)` tests it. Boss deaths, NPC quest states, opened
doors and one-shot pickups are all flags in one numbering.

The save stores those flags as **plain bit fields in three fixed-size blobs**,
with

```
bit position = flag id          (LSB first: flag 4096 = byte 512, bit 0)
```

| Blob (key)  | Bytes  | Capacity        | Role |
|-------------|--------|-----------------|------|
| `522ad995`  | 2256   | flags 0–18047   | **The event flags.** Every boss, NPC quest, door and pickup flag the scripts use. Proven (below). |
| `0af4946a`  | 3200   | flags 0–25599   | Same bit-per-flag layout; what selects it is not identified yet. |
| `78a5c2d7`  | 4096   | flags 0–32767   | Same layout; empty for a fresh character, wiped by New Game+. |

No header, no count: unused bytes are zero. The blobs sit together near the
end of the save's top-level records (between the option floats and the
world-state blob). The options profile has none.

## How it was identified

The eboot's save reader gave the first anchor: it reads exactly these three
blobs into buffers of exactly their sizes (`0x8d0`, `0xc80`, `0x1000` bytes —
visible as `mov $0x8d0/%ecx...` allocation pairs around the `522ad995`,
`0af4946a`, `78a5c2d7` immediates at `eboot+0x3c74f` ff.), so they are
fixed-layout engine state, not per-record data.

The bit mapping was then proven against saves with known game state, with
three independent anchors:

1. **Boss flags match the demon souls each save holds.** The scripts'
   `GetBossFlagCount` (in `global_event.lua`) lists all sixteen boss-death
   flags in world groups. A mid-game save (`DPG`, `DEMONSKILLED=3`, holding
   the Phalanx, Tower Knight and Armour Spider souls) has exactly the flag
   pairs 4096+4103, 4224+4252, 6174+6193 set — death flag and soul flag,
   nothing else. An end-game save (`LOL`, `DEMONSKILLED=15`) has fifteen of
   sixteen boss flags — every one except 4480, the False King, which that
   character never fought.
2. **NPC quest states match each save's story.** `event_define.lua` defines
   each NPC's quest states as flag constants (the Maiden in Black
   `HEROINE_STATE_*` = 16140–16146, Biorr `BIYO_STATE_*` = 16060+, ... twenty
   seven lists in all) and the scripts keep **exactly one state flag set per
   NPC** (`SetNpcStateFlag` lowers the old state and raises the new). Every
   save in the collection obeys this: fresh characters show
   `HEROINE_STATE_ISNOT` (16146) with Biorr `CAPTIVE` (16060); the mid-game
   save shows `WAIT_FOR_PLAYER` (16140); the end-game save shows Scirvir
   `DEAD` (16314), Biorr mid-flight with the dragon, Selen searching for her
   brother — all matching what those playthroughs did.
3. **New Game+ wipes world flags and keeps Nexus ones.** The same character
   before and after finishing the game: every world flag (bosses, doors,
   pickups — everything below ~15000 that belongs to the five worlds) is
   cleared; the Nexus NPC states, the tutorial flags (14050–14312) and the
   "has been to" flags (8084–8090) survive. That is exactly how a New Game+
   behaves in game.

The mapping also explains the two "mystery" 16-byte and 12-byte blobs nearby
(`fb0faeb2`, `739273b8`, `2b87b29a`, `94a8d348`): they churn between saves
seconds apart, so they are session state, not story flags. They are left
untouched.

## Where each flag's meaning comes from

`tools/build_flagdb.py GAME` parses the game's own scripts (CP932 text, no
game files are shipped) and writes `flagdb.json`:

- **Bosses.** `GetBossFlagCount`'s table gives the sixteen death flags; each
  map script's "Get Soul" handler (`OnEvent_4103_1` → `GetRateItem(10110)`,
  `SetEventFlag(5121, 1)` in 3-1, ...) names the paired one-shot soul flag.
- **NPC quest states.** `event_define.lua`'s `*_flag_list` tables with their
  per-state comments ("Working", "Hostility", "Death", "Not yet"). The file
  also defines `NPC_STATE_BACKUP_OFFSET = 1000`: when a script turns an NPC
  hostile it parks the old state in flag+1000 so `SeekForgiveness` can restore
  it. Real saves carry those backup bits (the end-game save has 17353 and
  17443 set — Tomasu's and Baldwin's hostility backups).
- **Everything else.** Each map script documents its own events as
  `--■ 4096 ■ Opening the door to the inside of the castle ■` next to the
  `SetEventFlag`/`IsCompleteEvent` calls that use them — 1,200 flags have at
  least one such description (machine-translated English, occasionally
  ambiguous; several maps reuse small numbers, so the database keeps every
  description it saw).
- **Tendency pairings.** The `IsSuccessQWC(judge)` call sites sit next to the
  flags they gate: judge 20300/20600 with the execution-ground door flag 200,
  20500 with Miralda's removal flag 61, and so on (41 pairings). This is what
  the Tendency view needs to say which flags a tendency change will drive.

## What this makes possible

All three are same-size bit edits in one blob, so they go through the normal
validated write path:

- **Respawn a boss.** Clear its death flag; clear its soul flag to make the
  demon soul pickable again. `events FILE --respawn phalanx`. The scripts
  re-evaluate everything on area load — the boss, its fog gate, the boss-room
  collision and the archstone state all key off the one flag.
- **Fix a bugged NPC questline.** Put an NPC into exactly one quest state
  (`events FILE --npc baldwin=work`); the recipe enforces the one-state
  invariant and clears the +1000 backup twins.
- **Re-collect a one-shot item.** Clear its flag (`events FILE --set 4103=0`
  for the Phalanx's soul, or any flag from `--filter`).
- **Finish tendency.** With the pairings, the Tendency view can show which
  event flags each judge drives — and which of those flags are already set,
  which is why a tendency change sometimes appears to "do nothing": the
  one-shot event already happened.

Edits are opt-in (`--experimental`) until they are verified in game.

## Verification status and next steps

Verified against saves (no game run yet):

- bit mapping, boss/soul flags, NPC states, NG+ semantics (above)
- round-trip: flag edits rebuild byte-identically apart from the flipped bits,
  checksum valid, 21 tests in `tests/test_flags.py`

Not yet done:

1. **In-game check.** The Kyty harness (`tools/ingame_check.py`) needs a case
   that flips one flag and observes it. Cheapest first case: respawn Phalanx
   (clear 4096+4103) on the SL-320 character, warp to 1-1, and check the fog
   gate is back; the reverse case (set 4096 on a fresh character) should make
   the Phalanx archstone show as cleared. A NPC case: set Biorr `CAPTIVE`
   (16060) and check he is back in the 1-2 cell.
2. **The other two banks.** `0af4946a` and `78a5c2d7` use the same layout but
   their selector is unknown. Candidates: the area argument of
   `SetAreaEventFlag(area, flag, value)` (the scripts pass areas 01–08), a
   second flag space for NG+ cycles, or per-entity state (the third bank is
   empty for a fresh character and wiped by NG+, and its set bits sit at
   indices no script uses — 23000+, where only entity/lot ids reach). The
   experiment: in Kyty, kill one specific enemy and diff — the bit that flips
   names the bank and its index base.
3. **Flag-number reuse across maps.** Small flag numbers appear in several
   map scripts (200 is "Half hand enemy" in the Nexus script and "Door to the
   execution place" in 1-1's). Either the scripts share those flags or the
   engine namespaces them per area and the blobs hold per-area banks — the
   same question as (2), answerable with the same experiment: open the
   execution-ground door and see whether the Nexus's flag 200 moves too.
4. **The 20xxx outliers.** `m03_01_00_99.lua` uses flags 20080/20090 (above
   the primary bank's 18048); if they persist, the second bank continues the
   numbering (`20080 - 18048 = bit 2032`). No sampled save has them set.

## Using it

```bash
python3 tools/build_flagdb.py /path/to/PPSA01341-app0      # rebuild flagdb.json
python3 src/des_editor.py events --list                    # every known flag
python3 src/des_editor.py events FILE                      # bosses, NPC states
python3 src/des_editor.py events FILE --filter miralda     # search by text
python3 src/des_editor.py events FILE --json
python3 src/des_editor.py events FILE --respawn phalanx --experimental
python3 src/des_editor.py events FILE --npc baldwin=work --experimental
python3 src/des_editor.py events FILE --set 4103=0 --experimental
```

`--respawn`, `--npc` and `--set` write through the normal validated path
`--respawn`, `--npc` and `--set` write through the normal validated path
(timestamped backup, atomic replace) and change nothing else; reads never need
`--experimental`.
