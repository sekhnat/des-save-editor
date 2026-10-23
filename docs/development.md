# Development

[← Back to the README](../README.md)

## Tests

Run from the repository root. Tests that need real saves read `DES_SAVE_DIR`
(your `_SaveData/PPSA01341` copy), and tests that need the game files read
`DES_GAME_DIR` (the `PPSA01342-app` folder). They are skipped, with the reason
printed, when those are not set.

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

The full suite is 166 tests and runs in about 30 s without the optional fixture
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
