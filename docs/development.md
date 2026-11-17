# Development

[← Back to the README](../README.md)

## Tests

Run from the repository root. The atlas tests need numpy (`tools/build_icons.py` also needs Pillow).
Tests that need real saves read `DES_SAVE_DIR`
(your `_SaveData/PPSA01341` copy), and tests that need the game files read
`DES_GAME_DIR` (the `PPSA01342-app` folder). They are skipped, with the reason
printed, when those are not set.

```bash
# Standard-library tests only
python3 -m unittest discover -s tests -p test_save.py -v

# Full suite; requires Playwright and its Chromium browser in the test environment
python3 -m unittest discover -s tests -v

python3 tests/benchmark_editor.py
python3 tools/embed_fields.py --check     # page field and tendency tables match src/
python3 tools/build_tendencydb.py GAME --check   # tendency catalog matches the game files
python3 tools/build_flagdb.py GAME --check       # event-flag database matches the game files
python3 tools/build_flagdb.py GAME --coverage SAVE  # share of a save's set flags that have a label
python3 tools/embed_flagdb.py --check     # page carries the current event-flag table
python3 tools/embed_entitydb.py --check   # page carries the current entity index
python3 tools/embed_icons.py --check      # page carries iconpack.json
python3 src/des_editor.py selftest /path/to/_SaveData/PPSA01341
```

The full suite is 290 tests and runs in about 45 s without the optional fixture
environment (most of them format, structure, tools and browser flows). Regression
coverage includes all three original files, malformed records, strict numeric and
hex bounds, atomic imports and writes, undo/redo, async-save races, JSON drafts,
category collisions, exact binary exports, ZIP contents and CRC, float bit
preservation, 100 seeded Python/JavaScript differential fixtures, world-state
framing on every sample and all 166 game baselines, PARAMDEF layouts, loadout
checks, and Python/browser agreement on arrays, inventory, world state and entity
labels. Tests never edit the original saves.

## Performance

On the 258,582-byte / 1,026-record sample, observed JavaScript refresh time went
from about **70.5 ms to 0.9 ms** (not a page-load/paint or game benchmark).
Inactive raw inputs dropped from **1,023 to zero**, and eagerly generated hidden
JSON from **609,779 characters to zero**. After cache warm-up, 100 unchanged dirty
checks perform **zero serializations**. With the inventory card, the editor view
renders in about 6.6 ms on the machine used for that change (4.1 ms there before
the card).

Timings vary by machine; structural performance assertions are tested instead of
fragile wall-clock thresholds.

## In-game checks

`tools/ingame_check.py` checks edits in the real game: Demon's Souls on the
Kyty emulator. It is opt-in and needs `KYTY_DIR` (the KytyPS5 checkout, with
`run-linux.sh`, `tools/local/demons-souls-smoke.py` and `_SaveData`), plus Xvfb,
xdotool, ImageMagick's `import`, tesseract and `pactl`. The game always runs
inside the script's own Xvfb server (`:97`); there is no visible-window mode.

```bash
export KYTY_DIR=/path/to/KytyPS5
python3 tools/ingame_check.py cases                      # what can be checked
python3 tools/ingame_check.py run qty dur --dry-run      # edits on a scratch copy only
python3 tools/ingame_check.py run qty dur add-weapon     # boot, look, save, judge, restore
python3 tools/ingame_check.py boot qty                   # leave the game running to explore
python3 tools/ingame_check.py keys Return wait:2 'e*2' shot:status
python3 tools/ingame_check.py finish                     # save and exit, judge, restore
python3 tools/ingame_check.py restore                    # after a crash
```

Before booting, `_SaveData` is renamed aside with a SHA-256 manifest and copied
back as the working copy. Afterwards the working copy moves into the run folder
and the original is renamed back and checked against the manifest. Nothing is
deleted. Each run folder under `ingame-runs/` (ignored by git) holds the
original, edited and game-written files, both diffs, the screenshots and
`verdict.json`. A case passes as `kept` when its check fails on the original,
passes on the edited file and still passes on the game's save; the screenshots
show whether the game displays it. The cases are written for one character, so
each checks its precondition first. Results so far are in
[Research notes](research.md#in-game-checks).

While a run is in progress the game rewrites the working copy, so point
`DES_SAVE_DIR` for the test suite at another copy of the saves.

## Desktop app

The desktop app is Electron hosting the unmodified `des_editor.html` with the
network blocked.

```bash
cd desktop
npm ci
npm start      # run from a checkout
npm test       # smoke test (needs a display, e.g. xvfb-run -a npm test)
```

## Releases

Pushing a `v*` tag makes `.github/workflows/desktop.yml` test, build and publish
the release for Windows, Linux and macOS. Other pushes upload the builds as
workflow artifacts.

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```
