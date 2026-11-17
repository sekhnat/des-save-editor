#!/usr/bin/env python3
"""
Demon's Souls (PS5) save editor - command line interface.

    python3 des_editor.py info   <USR-DATA>          # character overview
    python3 des_editor.py list   <USR-DATA>          # known fields + values
    python3 des_editor.py tree   <USR-DATA>          # every field, named or not
    python3 des_editor.py get    <USR-DATA> PLAYER_SOULS
    python3 des_editor.py set    <USR-DATA> PLAYER_SOULS=12345 PLAYER_CURRENTVITALITY=40
    python3 des_editor.py dump   <USR-DATA> out.json
    python3 des_editor.py patch  <USR-DATA> out.json --out <USR-DATA>
    python3 des_editor.py items  <USR-DATA>          # inventory, storage, equipment
    python3 des_editor.py add    <USR-DATA> weapon 20700      # add an item to the inventory
    python3 des_editor.py upgrade <USR-DATA> 69 10603         # weapon level/path
    python3 des_editor.py respec <USR-DATA> VIT=60 STR=40   # same soul level
    python3 des_editor.py respec <USR-DATA> VIT=70 --level  # soul level follows
    python3 des_editor.py world  <USR-DATA>          # world-state entities
    python3 des_editor.py events <USR-DATA>          # event flags: bosses, NPC quests
    python3 des_editor.py events <USR-DATA> --respawn phalanx    # make a boss alive again
    python3 des_editor.py events <USR-DATA> --set m02:200=0 --experimental  # area-local flag
    python3 des_editor.py events <USR-DATA> --rearm-pickups m02 --experimental  # pickups again
    python3 des_editor.py events <USR-DATA> --sync-copy           # fix a mismatched flag copy
    python3 des_editor.py tendency <USR-DATA> --trigger 20300   # world/character tendency

Writing always leaves a timestamped `.bak` copy next to the file and
recomputes the FNV-1a checksum in the header, so the result is a valid save.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import des_arrays
import des_character
import des_diff
import des_fields
import des_inventory
import des_items
import des_flags
import des_save
import des_tendency
from des_save import SaveFile, name_key


# --------------------------------------------------------------------------- #
def _backup(path: str) -> str:
    """Create a collision-resistant backup without ever overwriting an earlier one."""
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = f"{path}.{stamp}-{time.time_ns() % 1_000_000_000:09d}.bak"
    with open(path, 'rb') as source, open(backup, 'xb') as target:
        shutil.copyfileobj(source, target)
    shutil.copystat(path, backup)
    print(f"  backup written to {backup}")
    return backup


def _write(sf: SaveFile, path: str, out: str | None, *, backup: bool = True,
           message=None) -> int:
    """Save to `out` (or over `path`, after a backup unless `backup` is False)."""
    dest = out or path
    if backup and os.path.abspath(dest) == os.path.abspath(path):
        _backup(path)
    des_save.save(sf, dest)
    print(message(dest) if message else f"  wrote {dest}")
    return 0


def _fmt(field: des_save.Field) -> str:
    if field.is_container:
        return f"container({len(field.children)})"
    if field.is_text:
        if field.type == des_save.T_STR:
            return repr(field.text())
        return f"blob[{len(field.raw)}] {field.raw[:16].hex()}"
    if field.type == des_save.T_RAW4:
        return f"0x{field.raw.hex()} (be {int.from_bytes(field.raw, 'big')})"
    if field.is_float:
        return f"{field.value:.4f}"
    return str(field.value)


def cmd_info(path: str) -> int:
    sf = des_save.load(path)
    print(f"{path}")
    print(f"  format version {sf.version}, {sum(1 for _ in sf.walk())} fields, "
          f"checksum {'valid' if sf.checksum_ok() else 'INVALID'}")
    s = sf.summary()
    if s.get("name") is None:
        print("  (no PLAYER_* fields - this looks like the options profile)")
        return 0
    print(f"  name            : {s['name']!r}")
    archetype = sf.get("PLAYER_ARCHETYPE")
    match = next((c for c in des_items.load_classes() if c['archetype'] == archetype), None)
    if match:
        print(f"  class           : {match['name'] or '?'} (archetype {archetype}, "
              f"CharaInitParam row {match['row']})")
    print(f"  souls           : {s['souls']:,}" if isinstance(s['souls'], int) else s['souls'])
    if "soul_level" in s:
        print(f"  soul level      : {s['soul_level']}  (derived from attributes)")
    hp, hpmax, hpbase = s["hp"]
    mp, mpmax, mpbase = s["mp"]
    sp, spmax, spbase = s["sp"]
    print(f"  HP              : {hp} / {hpmax} (body form max {hpbase})")
    print(f"  MP              : {mp} / {mpmax} (body form max {mpbase})")
    print(f"  SP              : {sp} / {spmax} (max {spbase})")
    print("  attributes      : " + ", ".join(f"{k[:3].upper()} {v}" for k, v in s["attributes"].items()))
    if s.get("playtime_s") is not None:
        print(f"  play time       : {s['playtime_s']:.0f} s "
              f"({s['playtime_s']/3600:.2f} h)   [raw {s['playtime_ms']:.0f}]")
    print(f"  deaths          : {s['deaths']}")
    items = des_inventory.inventory(sf)
    if items:
        known = sum(1 for row in items if row['name'])
        stored = des_inventory.storage(sf)
        print(f"  inventory       : {len(items)} entries, {known} named; "
              f"storage {len(stored)} (see `items` command)")
    return 0


def cmd_list(path: str) -> int:
    sf = des_save.load(path)
    print(f"{path}  ({len(sf.records)} root fields)")
    for category, names in des_fields.LAYOUT.items():
        rows = []
        for n in names:
            f = sf.find(n)
            if f is not None:
                rows.append((n, _fmt(f), f.offset))
        if not rows:
            continue
        print(f"\n  [{category}]")
        for n, v, off in rows:
            print(f"    {n:<28} {v:<22} @{off:#08x}")
    unknown = [f for f, _ in sf.walk()
               if not f.is_container and des_fields.lookup(f.key) is None]
    if unknown:
        print(f"\n  [{len(unknown)} fields without a known name - see `tree`]")
    return 0


def cmd_tree(path: str) -> int:
    sf = des_save.load(path)
    for f, depth in sf.walk():
        name = des_fields.field_name(f.key)
        label = f"{name}" if name else f"0x{f.key:08X}"
        print(f"  {'  ' * depth}{f.offset:#08x}  {label:<28} t{f.type:02x}  {_fmt(f)}")
    return 0


def _find(sf: SaveFile, spec: str):
    """Field by name or by 0xKEY hex."""
    spec = spec.strip()
    if spec.lower().startswith("0x"):
        return sf.find(int(spec, 16))
    return sf.find(spec)


def cmd_get(path: str, field: str) -> int:
    sf = des_save.load(path)
    f = _find(sf, field)
    if f is None:
        print(f"field {field} not present in this file", file=sys.stderr)
        return 1
    print(_fmt(f))
    return 0


def _coerce(field: des_save.Field, text: str):
    if field.type == des_save.T_STR:
        return text
    if field.type == des_save.T_BLOB:
        return bytes.fromhex(text)
    if field.type == des_save.T_F32:
        return float(text)
    if field.is_int:
        return int(text, 0)
    return text


def cmd_set(path: str, assignments: list[str], out: str | None,
            no_backup: bool) -> int:
    sf = des_save.load(path)
    changed = 0
    for item in assignments:
        if "=" not in item:
            print(f"bad assignment {item!r} (expected FIELD=VALUE)", file=sys.stderr)
            return 2
        name, _, text = item.partition("=")
        field = _find(sf, name)
        if field is None:
            print(f"field {name} not present in this file", file=sys.stderr)
            return 2
        meta = des_fields.BY_NAME.get(name.strip().upper()) or des_fields.lookup(field.key)
        value = _coerce(field, text)
        if meta and meta["kind"] == "int":
            value = int(value)
            if not (meta["lo"] <= value <= meta["hi"]):
                print(f"warning: {name}={value} is outside the usual range "
                      f"{meta['lo']}..{meta['hi']}", file=sys.stderr)
        if meta and meta["kind"] == "text" and len(value) > 16:
            print(f"warning: {name} is longer than the in-game 16 character limit",
                  file=sys.stderr)
        field.value = value
        print(f"  {name:<28} -> {_fmt(field)}")
        changed += 1

    if changed:
        _write(sf, path, out, backup=not no_backup,
               message=lambda dest: f"  wrote {dest} ({os.path.getsize(dest)} bytes, "
                                    "checksum recalculated)")
    return 0


def cmd_dump(path: str, out: str | None) -> int:
    sf = des_save.load(path)

    def to_obj(records):
        res = []
        for f in records:
            name = des_fields.field_name(f.key)
            entry = {"key": f"{f.key:08X}", "type": f"0x{f.type:02x}",
                     "offset": f.offset}
            if name:
                entry["name"] = name
            if f.is_container:
                entry["children"] = to_obj(f.children)
            else:
                v = f.value
                entry["value"] = (v.hex() if isinstance(v, (bytes, bytearray)) else v)
            res.append(entry)
        return res

    doc = {"file": path, "version": sf.version, "checksum_ok": sf.checksum_ok(),
           "records": to_obj(sf.records)}
    text = json.dumps(doc, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {out}")
    else:
        print(text)
    return 0


def cmd_patch(path: str, patch_path: str, out: str | None) -> int:
    """Apply a strict field map or a browser-exported path/conflict-checked patch."""
    sf = des_save.load(path)
    with open(patch_path, encoding='utf-8') as source:
        patch = json.load(source)
    if not isinstance(patch, dict):
        raise ValueError('patch must be a JSON object')
    if patch.get('format') == 'des-patch-1':
        if patch.get('version') != sf.version or not isinstance(patch.get('changes'), list):
            raise ValueError('invalid change patch')
        paths = {}
        def index(rows, prefix=''):
            for i, field in enumerate(rows):
                address = f'{prefix}/{i}'
                paths[address] = field
                if field.is_container:
                    index(field.children, address)
        index(sf.records)
        for change in patch['changes']:
            field = paths.get(change.get('path'))
            if (field is None or field.is_container
                    or field.key != int(change.get('key', ''), 16)
                    or field.type != change.get('type')
                    or field.raw.hex() != change.get('before')):
                raise ValueError(f"patch conflict at {change.get('path')}")
            raw = bytes.fromhex(change['hex'])
            if field.type in des_save.SIZES and len(raw) != des_save.SIZES[field.type]:
                raise ValueError('fixed-width field size mismatch')
            field.raw = raw
    else:
        for name, value in patch.items():
            key = int(name, 16) if name.lower().startswith('0x') else name_key(name)
            fields = [f for f in sf.find_all(key) if not f.is_container]
            if len(fields) != 1:
                raise ValueError(f'{name}: expected one field, found {len(fields)}')
            field = fields[0]
            if field.type in (des_save.T_BLOB, des_save.T_RAW4):
                field.value = bytes.fromhex(value['hex'] if isinstance(value, dict) else value)
            elif field.type == des_save.T_STR:
                if not isinstance(value, str):
                    raise ValueError(f'{name}: expected text')
                field.value = value
            else:
                field.value = value
    return _write(sf, path, out)


def cmd_items(path: str, as_json: bool) -> int:
    """List the inventory, the storage box and the equipment slots."""
    sf = des_save.load(path)
    catalog = des_inventory._catalog()
    if not catalog:
        print("itemdb.json not found in the repository root - run tools/build_itemdb.py",
              file=sys.stderr)
    doc = {'inventory': des_inventory.inventory(sf, catalog),
           'storage': des_inventory.storage(sf, catalog),
           'equipment': des_inventory.equipment(sf, catalog),
           'dead_enemies': des_items.dead_enemies(sf)}
    if as_json:
        print(json.dumps(doc, indent=2))
        return 0
    print(f"{path}\n\n  inventory ({len(doc['inventory'])} entries)")
    for row in doc['inventory']:
        mark = '' if row['complete'] else '  [incomplete]'
        limit = f"/{row['max_quantity']}" if row['max_quantity'] else ''
        durability = f"{row['durability']}" + (f"/{row['max_durability']}" if row['max_durability'] else '')
        print(f"    {row['index']:2d}  ref {row['ref']!s:>3}  {row['category'] or '?':<6} {row['id']:>7}  "
              f"{row['name'] or 'unknown id':<34} x{str(row['quantity']) + limit:<7} "
              f"durability {durability}{mark}")
    print(f"\n  storage box ({len(doc['storage'])} entries)")
    for row in doc['storage']:
        mark = '' if row['complete'] else '  [incomplete]'
        print(f"    {row['index']:2d}  {row['category'] or '?':<6} {row['id']:>7}  "
              f"{row['name'] or 'unknown id':<34} x{row['low_quantity']:<4} "
              f"durability {row['durability']}{mark}")
    print(f"\n  equipment slots ({len(doc['equipment'])} occupied; slot meanings not verified)")
    for row in doc['equipment']:
        print(f"    slot {row['slot']:2d}  ref {row['inventory']!s:>3}  {row['id']!s:>7}  "
              f"{row['name'] or ''}")
    print(f"\n  dead enemy indices: {len(doc['dead_enemies'])}")
    return 0


def cmd_inv(path: str, quantities: list[str], durabilities: list[str],
            box_quantities: list[str], out: str | None) -> int:
    """Same-size edits of inventory values; storage-box quantities are experimental."""
    sf = des_save.load(path)
    for specs, setter, label in ((quantities, des_inventory.set_quantity, 'quantity'),
                                 (durabilities, des_inventory.set_durability, 'durability'),
                                 (box_quantities, des_inventory.set_storage_quantity,
                                  'storage quantity')):
        for spec in specs:
            index, sep, value = spec.partition('=')
            if not sep:
                raise ValueError(f'bad assignment {spec!r} (expected INDEX=VALUE)')
            setter(sf, int(index), int(value, 0))
            print(f"  {label} {int(index):02d} -> {int(value, 0)}")
    return _write(sf, path, out)


def cmd_add(path: str, category: str, item_id: str, destination: str, quantity: str,
            out: str | None) -> int:
    """Item creation, written only after the operation succeeds (storage box: experimental)."""
    name = {'weapon': 'Weapon', 'armor': 'Armor', 'ring': 'Ring',
            'goods': 'Goods'}.get(category.strip().lower())
    if name is None:
        raise ValueError('category must be one of: armor, goods, ring, weapon')
    sf = des_save.load(path)
    numeric_id = int(item_id, 0)
    created = des_inventory.with_added_item(sf, name, numeric_id, quantity=int(quantity, 0),
                                            destination=destination)
    entry = des_inventory._catalog().get((name, numeric_id))
    label = entry['name'] if entry else '?'
    print(f"  added {label} ({name} {numeric_id}) to the {destination}")
    return _write(created, path, out)


def cmd_upgrade(path: str, index: str, new_id: str, storage: bool, list_family: bool,
                out: str | None) -> int:
    """Change a weapon to another upgrade level or path of the same weapon."""
    sf = des_save.load(path)
    destination = 'storage' if storage else 'inventory'
    rows = des_inventory.storage(sf) if storage else des_inventory.inventory(sf)
    row = next((r for r in rows if r['index'] == int(index)), None)
    if row is None:
        raise ValueError(f'{destination} entry {index} does not exist')
    if list_family or new_id is None:
        for entry in des_inventory.upgrade_family(row['category'], row['id']):
            mark = '  <- current' if entry['id'] == row['id'] else ''
            print(f"  {entry['id']:>7}  {entry['name']}{mark}")
        return 0
    numeric_id = int(new_id, 0)
    des_inventory.set_weapon_variant(sf, int(index), numeric_id, destination)
    entry = des_inventory._catalog().get(('Weapon', numeric_id))
    print(f"  {destination} {int(index):02d}: {row['name']} -> {entry['name'] if entry else numeric_id}")
    return _write(sf, path, out)


def cmd_respec(path: str, assignments: list[str], out: str | None, no_backup: bool,
               level: bool = False) -> int:
    """Move points between attributes at the same soul level, or change it with level."""
    sf = des_save.load(path)
    if not assignments:
        values, floor = des_character.attributes(sf), des_character.class_floor(sf)
        print(f"  soul level {des_character.soul_level(values)}")
        for name in des_character.ATTRS:
            print(f"  {name.lower():<13} {values[name]!s:>3}   (class minimum {floor[name]})")
        return 0
    changes = {}
    for spec in assignments:
        name, sep, value = spec.partition('=')
        if not sep:
            raise ValueError(f'bad assignment {spec!r} (expected ATTRIBUTE=VALUE, e.g. VIT=40)')
        changes[name] = int(value, 0)
    before = des_character.attributes(sf)
    after = (des_character.set_attributes if level else des_character.redistribute)(sf, changes)
    for name in des_character.ATTRS:
        if after[name] != before[name]:
            print(f"  {name.lower():<13} {before[name]} -> {after[name]}")
    old, new = des_character.soul_level(before), des_character.soul_level(after)
    print(f"  soul level {'stays ' + str(new) if old == new else f'{old} -> {new} (not checked in game)'}; "
          "max HP/MP/stamina keep their stored values (the game did not recompute them)")
    return _write(sf, path, out, backup=not no_backup)


def cmd_arrays(path: str, as_json: bool) -> int:
    """List fixed-slot arrays recovered by FNV-state discovery."""
    sf = des_save.load(path)
    rows = des_arrays.report(sf)
    if as_json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{path}\n  {len(rows)} fixed-slot array(s) recovered structurally; "
          f"slot letters are canonical, the field name shows the real index")
    for row in rows:
        print(f"\n  {row['family'] or 'unnamed array'}")
        print(f"  @0x{row['offset']:04x}  {row['count']} slots of {row['type']:#04x}"
              f"  state {row['state']:08x}  [{row['kind']}]")
        print(f"      {row['description']}")
        for slot in row['slots']:
            print(f"      slot '{slot['char']}'  0x{slot['key']:08x}  "
                  f"{slot['field'] or '':<26} {slot['value']:>10}  {slot['name'] or ''}")
    return 0


def cmd_blobs(path: str) -> int:
    """Describe every blob; world-state containers are summarised."""
    sf = des_save.load(path)
    rows = des_arrays.blobs(sf)
    total = sum(row['size'] for row in rows)
    print(f"{path}\n  {len(rows)} blob(s), {total} bytes "
          f"({total * 100 // max(len(sf.build()), 1)}% of the file)")
    for row in rows:
        name = row['name'] or f"<{row['key']:08x}>"
        print(f"\n  {name:<28} {row['size']:>7} B  @0x{row['offset']:05x}")
        world = row['world']
        if world:
            print(f"      world state: {world['groups']} group(s), {world['entries']} "
                  f"entit{'y' if world['entries'] == 1 else 'ies'}, "
                  f"{world['parsed']} decoded (see the world command)")
    return 0


def _world_value(record: dict) -> str:
    value = record['value']
    if isinstance(value, dict):
        return f"blob[{value['size']}] {value['hex'][:24]}"
    if isinstance(value, list):
        return f"container({len(value)})"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def cmd_world(path: str, as_json: bool, group: int | None, text: str | None) -> int:
    """List world-state entities and their decoded records."""
    import des_world
    sf = des_save.load(path)
    index = des_world.default_index()
    found = des_world.world_blobs(sf)
    if not found:
        print(f"{path}\n  no world-state container in this file")
        return 0
    needle = (text or '').lower()
    out = []
    for blob, groups in found:
        rows = des_world.describe(groups, index)
        if group is not None:
            rows = [row for row in rows if row['group'] == group]
        if needle:
            rows = [row for row in rows if needle in json.dumps(row).lower()]
        out.append({'blob': f"{blob.key:08x}", 'offset': blob.offset,
                    'groups': len(groups), 'entries': rows})
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    print(path)
    if index is None:
        print("  (entitydb.bin not found: entities are shown by GUID only)")
    for blob in out:
        print(f"\n  world-state blob {blob['blob']}: {blob['groups']} group(s), "
              f"{len(blob['entries'])} entr{'y' if len(blob['entries']) == 1 else 'ies'} shown")
        current = None
        for row in blob['entries']:
            if row['group'] != current:
                current = row['group']
                print(f"\n  group {current}")
            entity = row['entity'] or ''
            print(f"    {row['guid']}  kind {row['kind']:<3} {row['size']:>6} B  {entity}")
            if 'raw' in row:
                print(f"        (not a record stream; kept raw) {row['raw'][:48]}")
                continue
            for record in row['records']:
                label = record['name'] or f"<{record['key']}>"
                print(f"        {record['key']}  {label:<34} = {_world_value(record)}")
    return 0


def cmd_wset(path: str, guid: str, assignments: list[str], occurrence: int,
             out: str | None) -> int:
    """Experimental same-size edit of scalar records inside one world entity."""
    import des_world
    sf = des_save.load(path)
    found = des_world.world_blobs(sf)
    if not found:
        raise ValueError('no world-state container in this file')
    blob = found[0][0]
    entity = des_world.parse_guid(guid)
    for item in assignments:
        name, sep, text = item.partition('=')
        if not sep:
            raise ValueError(f'bad assignment {item!r} (expected KEY=VALUE)')
        key = int(name, 16) if name.lower().startswith('0x') else name_key(name.strip())
        value = float(text) if any(c in text for c in '.eE') and not text.lower().startswith('0x') else int(text, 0)
        blob.raw = des_world.set_value(blob.raw, entity, key, value, occurrence)
        print(f"  {entity.hex()} {name} -> {value}")
    return _write(sf, path, out)


def cmd_diff(before: str, after: str, as_json: bool) -> int:
    """Record-level delta between two saves, for differential analysis."""
    left = des_save.load(before)
    right = des_save.load(after)
    delta = des_diff.compare(left, right)
    if as_json:
        print(json.dumps(delta, indent=2))
    else:
        print(f"{before}\n  -> {after}")
        print(des_diff.summarise(delta))
    return 0


def cmd_aslot(path: str, state: str, sets: list[str], clears: list[str],
              out: str | None) -> int:
    """Write single slots of a discovered array, addressed by state and suffix."""
    sf = des_save.load(path)
    digest = int(state, 16)
    for spec in sets:
        char, _, value = spec.partition('=')
        if len(char) != 1:
            raise ValueError('slot suffix must be exactly one character')
        written = des_arrays.set_slot(sf, digest, char, int(value, 0))
        print(f"  slot '{char}' -> {written.value}")
    for char in clears:
        if len(char) != 1:
            raise ValueError('slot suffix must be exactly one character')
        des_arrays.clear_slot(sf, digest, char)
        print(f"  slot '{char}' cleared (-1)")
    return _write(sf, path, out)


def cmd_selftest(paths: list[str]) -> int:
    """Check the library against real files: parse, rebuild, compare."""
    import glob
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            files += glob.glob(os.path.join(p, "**", "USR-DATA"), recursive=True)
        else:
            files += glob.glob(p)
    if not files:
        print("no USR-DATA files found", file=sys.stderr)
        return 2
    ok = True
    print("field table")
    seen = {}
    for key, meta in des_fields.FIELDS.items():
        if name_key(meta["name"]) != key:
            print(f"  FAIL {meta['name']} hashes to {name_key(meta['name']):08X}, table says {key:08X}")
            ok = False
        seen.setdefault(key, []).append(meta["name"])
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    print(f"  {len(des_fields.FIELDS)} names, all hashes consistent"
          + (f", DUPLICATES: {dupes}" if dupes else ""))
    ok = ok and not dupes
    print("files")
    for path in sorted(files):
        raw = des_save.read_bytes(path)
        try:
            sf = SaveFile(raw)
        except Exception as exc:
            print(f"  FAIL {path}: {exc}")
            ok = False
            continue
        rebuilt = sf.build()
        same = rebuilt == raw
        named = sum(1 for f, _ in sf.walk() if des_fields.lookup(f.key))
        print(f"  {'ok  ' if same and sf.checksum_ok() else 'FAIL'} {path}")
        print(f"       {len(raw)} bytes, {sum(1 for _ in sf.walk())} fields "
              f"({named} named), checksum {'valid' if sf.checksum_ok() else 'INVALID'}, "
              f"round-trip {'identical' if same else 'DIFFERS'}")
        ok = ok and same and sf.checksum_ok()
    print("SELFTEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1

def cmd_fields(_: str | None = None) -> int:
    for name in des_fields.known_names():
        meta = des_fields.BY_NAME[name]
        print(f"  {name_key(name):08X}  {name:<30} {meta['kind']:<6} {meta['desc']}")
    return 0


def cmd_verify(path: str) -> int:
    raw = des_save.read_bytes(path)
    sf = SaveFile(raw)
    rebuilt = sf.build()
    print(f"{path}")
    print(f"  size            : {len(raw)} bytes")
    print(f"  fields          : {sum(1 for _ in sf.walk())}")
    print(f"  header checksum : {'valid' if sf.checksum_ok() else 'INVALID'}")
    print(f"  rebuild         : {'byte identical' if rebuilt == raw else 'differs'}")
    return 0 if rebuilt == raw else 1


def _tendency_report(state: dict) -> dict:
    T = des_tendency
    active = set(T.active_events(state))
    def events(world):
        return [{"judge": e["judge"], "title": e["title"], "areas": e["areas"],
                 "requires": [f"{T.target_label(t)} {T.describe_range(lo, hi)}"
                              for t, lo, hi in T.requirement(e)],
                 "active": e["judge"] in active}
                for e in T.EVENTS if e["world"] == world]
    worlds = []
    for world in T.WORLDS:
        entry = state["worlds"].get(world["slot"])
        worlds.append({"key": world["key"], "name": world["name"], "slot": world["slot"],
                       "value": entry and entry["value"], "copy": entry and entry["copy"],
                       "band": entry and T.band(entry["value"]), "events": events(world["key"])})
    return {"character": {"value": state["pc_wb"], "band": None if state["pc_wb"] is None
                          else T.band(state["pc_wb"]), "left_right": state["pc_lr"],
                          "events": events("character")},
            "worlds": worlds}


def cmd_events(path: str | None, as_json: bool, text: str | None, list_known: bool,
               sets: list[str], respawn: str | None, npc: str | None,
               out: str | None, no_backup: bool, bank_only: bool = False,
               full: bool = False, defeat: str | None = None, forgive: str | None = None,
               reset_map: str | None = None, rearm: str | None = None,
               sync_copy: bool = False, no_soul: bool = False) -> int:
    """Event flags: the bits the game's scripts set and test."""
    F = des_flags
    db = F.load_db()
    if list_known:
        rows = {
            "bosses": db.bosses if db else [],
            "npcs": [{"list": n["list"], "name": n.get("name", n["list"]),
                      "states": [f"{s['id']} {s['name']}" for s in n["states"]]}
                     for n in (db.npcs if db else [])],
        }
        if as_json:
            print(json.dumps(rows, indent=1))
            return 0
        print("  bosses (death flag, soul flag)")
        for b in rows["bosses"]:
            print(f"    {b['id']:>5} {b['name']:<20} soul {b['soul']:>5}  {b['world']}")
        print("  NPC quest states (one set at a time; +1000 backup twin)")
        for n in rows["npcs"]:
            print(f"    {n['list']}  ({n['name']})")
            for s in n["states"]:
                print(f"      {s}")
        return 0
    if path is None:
        raise ValueError("events needs a file (or --list)")
    sf = des_save.load(path)
    if db is None:
        print("  (flagdb.json not found: run tools/build_flagdb.py; "
              "showing raw bit counts only)")
        if as_json:
            print(json.dumps(F.summary(sf), indent=1))
        else:
            for key, info in F.summary(sf).items():
                print(f"  {key}  {info['bits']} bits set  ({info['note']})")
        return 0

    changed = False
    try:
        if sync_copy:
            area = F.current_area(sf)
            if area is None:
                raise ValueError("the save has no current area (MAPUID), so there is no copy to fix")
            fixed = F.sync_mirror(sf)
            print(f"  {db.area_name(area)}: flag copy "
                  + ("rebuilt from the map slots" if fixed else "already matches the map slots"))
            changed = changed or fixed
        if respawn:
            result = F.respawn_boss(sf, db, respawn, full=full)
            local = (f"; {db.area_name(result['area'])} flags "
                     f"{', '.join(map(str, result['cleared_local']))}"
                     if result['cleared_local'] else "")
            print(f"  {result['boss']} alive again (cleared flags "
                  f"{', '.join(map(str, result['cleared']))}{local})")
            changed = True
        if defeat:
            sf, result = F.defeat_boss(sf, db, defeat, give_soul=not no_soul)
            print(f"  {result['boss']} marked defeated (set flags "
                  f"{', '.join(map(str, result['set']))})")
            if result['items']:
                print(f"  added to the inventory: {', '.join(result['items'])}")
            changed = True
        if forgive:
            result = F.forgive_npc(sf, db, forgive)
            if result['restored'] is None:
                print(f"  {result['npc']}: nothing to forgive (not hostile, "
                      "or no previous state kept)")
            else:
                print(f"  {result['npc']} forgiven: back to flag {result['restored']}"
                      + (f"; cleared {', '.join(f'm{a + 1:02d}:{f}' for a, f in result['cleared_local'])}"
                         if result['cleared_local'] else ""))
                changed = True
        if reset_map:
            area = F.parse_area(reset_map)
            count = F.reset_map(sf, area)
            print(f"  {db.area_name(area)}: cleared all {count} local flags")
            changed = changed or count > 0
        if rearm:
            area = F.parse_area(rearm)
            cleared = F.rearm_pickups(sf, db, area)
            print(f"  {db.area_name(area)}: {len(cleared)} pickups re-armed")
            for flag in cleared:
                print(f"    {flag}  {db.event_label(flag, area)}")
            changed = changed or bool(cleared)
        if npc:
            npc_name, sep, state = npc.partition("=")
            if not sep:
                raise ValueError(f"bad --npc {npc!r} (expected NPC=STATE, "
                                 "e.g. baldwin=work)")
            result = F.set_npc_state(sf, db, npc_name, state)
            print(f"  {result['npc']} -> {result['state']} (flag {result['id']})")
            changed = True
        current = F.current_area(sf)
        for item in sets:
            name, sep, value = item.partition("=")
            if not sep or value not in ("0", "1"):
                raise ValueError(f"bad assignment {item!r} (expected ID=0 or ID=1, "
                                 "or AREA:ID=0|1 for a local flag)")
            area, flag = F.parse_target(name)
            if area is None and F.is_local(flag):
                here = (f"; this save is on {db.area_name(current)}, e.g. "
                        f"m{current + 1:02d}:{flag}={value}") if current is not None else ""
                raise ValueError(f"flag {flag} is area-local: name its area "
                                 f"(AREA:ID=V){here}")
            if area is None:
                F.set_flag(sf, flag, value == "1")
                where = ""
            else:
                F.set_local(sf, area, flag, value == "1", mirror=not bank_only)
                where = f"{db.area_name(area)} "
                if area == current and not bank_only:
                    where += "(+ current-area copy) "
                elif bank_only:
                    where += "(area slot only) "
            label = db.event_label(flag, area)
            print(f"  {where}flag {flag} -> {value}" + (f" ({label})" if label else ""))
            changed = True
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if changed:
        return _write(sf, path, out, backup=not no_backup)

    # read-only report
    current = F.current_area(sf)
    counts = F.local_counts(sf)
    has_local = counts is not None
    report = {
        "summary": F.summary(sf),
        "current_area": current,
        "mirror_ok": F.mirror_ok(sf),
        "local_counts": ({db.area_name(a): n for a, n in enumerate(counts)}
                         if has_local else {}),
        "bosses": F.bosses(sf, db),
        "npcs": [{k: n[k] for k in ("list", "name", "set", "backup")}
                 for n in F.npc_states(sf, db)],
        "shops": F.shop_counters(sf, db),
    }
    if text:
        needle = text.lower()
        report["bosses"] = [b for b in report["bosses"] if needle in b["name"].lower()]
        report["npcs"] = [n for n in report["npcs"]
                          if needle in n["list"].lower() or needle in n["name"].lower()
                          or any(needle in s.lower() for s in n["set"])]
        flags = []
        for raw in F.global_flags(sf):
            label = db.event_label(raw)
            if label and needle in label.lower():
                flags.append({"id": raw, "label": label})
        for area in range(F.AREAS if has_local else 0):
            for raw in F.local_flags(sf, area):
                label = db.event_label(raw, area)
                if label and needle in label.lower():
                    flags.append({"area": f"m{area + 1:02d}", "id": raw, "label": label})
        report["matching_flags"] = flags
    if as_json:
        print(json.dumps(report, indent=1))
        return 0
    print(f"{path}")
    for key, info in report["summary"].items():
        print(f"  event flags {key}: {info['bits']} set "
              f"({info['bytes']} B, capacity {info['capacity']}) - {info['note']}")
    if current is not None:
        mirror = {True: "match its area slots", False: "DIFFER from its area slots",
                  None: "not checked"}[report["mirror_ok"]]
        print(f"  current area {db.area_name(current)}; primary local copies {mirror}")
    if report["local_counts"]:
        print("  local flags set per area: " + ", ".join(
            f"{name.split()[0]} {n}" for name, n in report["local_counts"].items()))
    print("  bosses")
    for b in report["bosses"]:
        soul = f", soul {'taken' if b['soul_taken'] else 'not taken'}" \
            if b["soul_taken"] is not None else ""
        print(f"    {'DEAD' if b['defeated'] else 'alive'}  {b['name']:<20} "
              f"flag {b['id']}{soul}")
    print("  NPC quest states (current | previous)")
    for n in report["npcs"]:
        if n["set"] or n["backup"]:
            print(f"    {n['name'][:24]:<24} {', '.join(n['set']) or '-'}"
                  f"{'  |  ' + ', '.join(n['backup']) if n['backup'] else ''}")
    touched = [s for s in report["shops"] if s["value"]]
    if touched:
        print("  shop stock counters (8 flags each, read as one byte; meaning unconfirmed)")
        for s in touched:
            print(f"    {s['item']:<28} value {s['value']:>3}  (sold: {s['stock']}, "
                  f"flags {s['flag']}..{s['flag'] + 7})")
    if text:
        print("  matching flags")
        for f in report["matching_flags"]:
            print(f"    {f.get('area', 'global'):>6} {f['id']:>5}  {f['label']}")
    return 0


def cmd_tendency(path: str, sets: list[str], triggers: list[str], list_events: bool,
                 as_json: bool, out: str | None, no_backup: bool) -> int:
    T = des_tendency
    if list_events:
        rows = [{"judge": e["judge"], "world": e["world"], "title": e["title"], "effect": e["effect"],
                 "areas": e["areas"], "requires": [f"{T.target_label(t)} {T.describe_range(lo, hi)}"
                                                    for t, lo, hi in T.requirement(e)],
                 "sources": e["sources"]} for e in T.EVENTS]
        if as_json:
            print(json.dumps(rows, indent=1, ensure_ascii=False))
        else:
            for r in rows:
                print(f"  {r['judge']:>5}  {r['world']:<10} {r['title']}  [{', '.join(r['areas'])}]")
                print(f"         needs {'; '.join(r['requires'])}. {r['effect']}")
        return 0
    sf = des_save.load(path)
    state = T.read(sf)
    targets: dict = {}
    try:
        for item in sets:
            name, sep, text = item.partition("=")
            if not sep:
                raise ValueError(f"bad assignment {item!r} (expected TARGET=VALUE)")
            value = float(text)
            if not -T.LIMIT <= value <= T.LIMIT:
                raise ValueError(f"{name}: tendency is -{T.LIMIT} to {T.LIMIT}")
            targets[T.parse_target(name)] = value
        if triggers:
            judges = []
            for text in triggers:
                judge = int(text)
                if judge not in T.EVENT_BY_JUDGE:
                    raise ValueError(f"unknown event {judge} (see --events)")
                judges.append(judge)
            plan = T.trigger_targets(T.with_targets(state, targets), judges)
            if plan["conflicts"]:
                for line in plan["conflicts"]:
                    print(f"conflict: {line}", file=sys.stderr)
                return 2
            targets.update(plan["targets"])
            for label, key in (("also turns on", "turns_on"), ("turns off", "turns_off")):
                for judge in plan[key]:
                    print(f"  {label}: {judge} {T.EVENT_BY_JUDGE[judge]['title']}")
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if targets:
        changed = T.apply(sf, targets)
        for target, value in targets.items():
            print(f"  {T.target_label(target):<26} -> {value:g} ({T.band(value)})")
        if changed:
            return _write(sf, path, out, backup=not no_backup)
        print("  no change")
        return 0
    report = _tendency_report(state)
    if as_json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 0
    def show(events):
        for e in events:
            print(f"      {'on ' if e['active'] else '-  '} {e['judge']:>5} {e['title']} "
                  f"[{', '.join(e['areas'])}] needs {'; '.join(e['requires'])}")
    c = report["character"]
    if c["value"] is not None:
        print(f"  Character            {c['value']:>7g}  {c['band']}   (left/right axis {c['left_right']:g})")
        show(c["events"])
    for w in report["worlds"]:
        if w["value"] is None:
            print(f"  {w['name']:<20} not in this save")
            continue
        note = "" if w["copy"] == w["value"] else f"   (copy field holds {w['copy']:g}; the game rewrites it)"
        print(f"  {w['name']:<20} {w['value']:>7g}  {w['band']}{note}")
        show(w["events"])
    return 0


# --------------------------------------------------------------------------- #
# Edits not yet confirmed in game need --experimental. Inventory quantity,
# durability, item creation and weapon upgrades were shown and kept by the game
# (Kyty, 2026-11-15; docs/research.md). Storage-box edits were kept by the
# game's own save but not seen on screen; world-state records beyond BROKEN
# have no observed effect.
STORAGE_UNSEEN = "storage-box edits are kept by the game but were not seen in game"
EVENTFLAG_UNSEEN = ("event-flag edits are kept by the game's own save but their "
                    "effect was not yet seen in game")
# Event-flag recipes whose effect was seen in game (docs/research.md#in-game-checks);
# the page's EV_CONFIRMED holds the same names.
EVENT_CONFIRMED: set[str] = {"respawn", "respawn-full",   # Phalanx back on screen, 2026-11-18
                              "defeat",   # Allant gone from 1-4, soul kept, 2026-11-18
                              "sync"}   # the game rebuilds the copy from the slots on load


def _events_reason(a) -> str | None:
    used = {name for name, on in (
        ("set", a.sets), ("respawn", a.respawn and not a.full), ("respawn-full", a.respawn and a.full),
        ("npc", a.npc), ("defeat", a.defeat), ("forgive", a.forgive),
        ("reset-map", a.reset_map), ("rearm", a.rearm), ("sync", a.sync_copy)) if on}
    return EVENTFLAG_UNSEEN if used - EVENT_CONFIRMED else None


EXPERIMENTAL = {
    "inv": lambda a: STORAGE_UNSEEN if a.box_qty else None,
    "wset": lambda a: "world-state record meanings are unverified",
    "add": lambda a: STORAGE_UNSEEN if a.destination == "storage" else None,
    "upgrade": lambda a: STORAGE_UNSEEN if a.storage and a.id is not None and not a.list_family else None,
    "events": lambda a: _events_reason(a),
}

COMMANDS = {
    "info": lambda a: cmd_info(a.file),
    "list": lambda a: cmd_list(a.file),
    "tree": lambda a: cmd_tree(a.file),
    "verify": lambda a: cmd_verify(a.file),
    "get": lambda a: cmd_get(a.file, a.field),
    "set": lambda a: cmd_set(a.file, a.assignments, a.out, a.no_backup),
    "dump": lambda a: cmd_dump(a.file, a.out),
    "patch": lambda a: cmd_patch(a.file, a.patch, a.out),
    "items": lambda a: cmd_items(a.file, a.as_json),
    "add": lambda a: cmd_add(a.file, a.category, a.id, a.destination, a.quantity, a.out),
    "inv": lambda a: cmd_inv(a.file, a.qty, a.durability, a.box_qty, a.out),
    "respec": lambda a: cmd_respec(a.file, a.assignments, a.out, a.no_backup, a.level),
    "upgrade": lambda a: cmd_upgrade(a.file, a.index, a.id, a.storage, a.list_family, a.out),
    "arrays": lambda a: cmd_arrays(a.file, a.as_json),
    "aslot": lambda a: cmd_aslot(a.file, a.state, a.sets, a.clear, a.out),
    "blobs": lambda a: cmd_blobs(a.file),
    "world": lambda a: cmd_world(a.file, a.as_json, a.group, a.text),
    "world": lambda a: cmd_world(a.file, a.as_json, a.group, a.text),
    "wset": lambda a: cmd_wset(a.file, a.guid, a.assignments, a.occurrence, a.out),
    "events": lambda a: cmd_events(a.file, a.as_json, a.text, a.list_known, a.sets,
                                   a.respawn, a.npc, a.out, a.no_backup, a.bank_only,
                                   a.full, a.defeat, a.forgive, a.reset_map, a.rearm,
                                   a.sync_copy, a.no_soul),
    "diff": lambda a: cmd_diff(a.before, a.after, a.as_json),
    "selftest": lambda a: cmd_selftest(a.paths),
    "fields": lambda a: cmd_fields(),
    "tendency": lambda a: cmd_tendency(a.file, a.sets, a.triggers, a.list_events, a.as_json,
                                       a.out, a.no_backup),
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Demon's Souls (PS5) save editor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("info", "list", "tree", "verify"):
        p = sub.add_parser(name)
        p.add_argument("file")

    p = sub.add_parser("get")
    p.add_argument("file"); p.add_argument("field")

    p = sub.add_parser("set")
    p.add_argument("file")
    p.add_argument("assignments", nargs="+", metavar="FIELD=VALUE")
    p.add_argument("--out", help="write to this path instead of in place")
    p.add_argument("--no-backup", action="store_true")

    p = sub.add_parser("dump")
    p.add_argument("file"); p.add_argument("out", nargs="?")

    p = sub.add_parser("items", help="list the inventory, storage box and equipment slots")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", dest="as_json")

    p = sub.add_parser("add", help="add an item to the inventory (storage box: experimental)")
    p.add_argument("file")
    p.add_argument("category", help="weapon, armor, ring or goods")
    p.add_argument("id", help="catalog item id (category-specific)")
    p.add_argument("--to", choices=("inventory", "storage"), default="inventory",
                   dest="destination", help="where to add the item (default inventory)")
    p.add_argument("--quantity", default="1",
                   help="stack units for goods and ammunition (default 1)")
    p.add_argument('--experimental', action='store_true',
                   help='acknowledge that storage-box additions were not seen in game')
    p.add_argument("--out", help="write to this path instead of in place")
    p = sub.add_parser("respec", help="move points between attributes at the same soul level, or level up/down with --level")
    p.add_argument("file")
    p.add_argument("assignments", nargs="*", metavar="ATTRIBUTE=VALUE",
                   help="e.g. VIT=40 STR=30; omit to show attributes and class minimums")
    p.add_argument("--out", help="write to this path instead of in place")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--level", action="store_true",
                   help="let the soul level change with the attributes (not checked in game)")
    p = sub.add_parser("upgrade", help="change a weapon's upgrade level or path (storage box: experimental)")
    p.add_argument("file")
    p.add_argument("index", help="inventory (or with --storage, storage box) entry index")
    p.add_argument("id", nargs="?", help="the new weapon id; omit to list the weapon's levels and paths")
    p.add_argument("--storage", action="store_true", help="the index is a storage box entry")
    p.add_argument("--list", action="store_true", dest="list_family",
                   help="list the weapon's levels and paths")
    p.add_argument('--experimental', action='store_true',
                   help='acknowledge that storage-box upgrades were not seen in game')
    p.add_argument("--out", help="write to this path instead of in place")
    p = sub.add_parser("inv", help="same-size edits of inventory values (storage box: experimental)")
    p.add_argument("file")
    p.add_argument('--experimental', action='store_true',
                   help='acknowledge that storage-box edits were not seen in game')
    p.add_argument("--qty", action="append", default=[], metavar="INDEX=N",
                   help="inventory stack size (1..999)")
    p.add_argument("--durability", action="append", default=[], metavar="INDEX=N")
    p.add_argument("--box-qty", action="append", default=[], dest="box_qty", metavar="INDEX=N",
                   help="storage stack size (1..255, low byte)")
    p.add_argument("--out")

    p = sub.add_parser("selftest", help="validate the parser against real saves")
    p.add_argument("paths", nargs="+", metavar="FILE_OR_DIR")

    sub.add_parser("fields", help="print the recovered field table")

    p = sub.add_parser("patch")
    p.add_argument("file"); p.add_argument("patch")
    p.add_argument("--out")
    p = sub.add_parser("arrays", help="list fixed-slot arrays recovered by key analysis")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", dest="as_json")

    p = sub.add_parser("aslot", help="edit one slot of a recovered array")
    p.add_argument("file")
    p.add_argument("state", help="array state, e.g. 7516f500 (see the arrays command)")
    p.add_argument("--set", action="append", default=[], dest="sets", metavar="CHAR=VALUE")
    p.add_argument("--clear", action="append", default=[], metavar="CHAR")
    p.add_argument("--out")

    p = sub.add_parser("blobs", help="describe each blob; world-state containers are summarised")
    p.add_argument("file")

    p = sub.add_parser("world", help="list world-state entities and their records")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--group", type=int)
    p.add_argument("--filter", dest="text", help="only entries whose GUID, entity, key or name contains TEXT")

    p = sub.add_parser("wset", help="experimental same-size edit of a world-state record")
    p.add_argument("file")
    p.add_argument("guid", help="entity GUID, 32 hex digits as the world command prints it")
    p.add_argument("assignments", nargs="+", metavar="KEY=VALUE")
    p.add_argument("--occurrence", type=int, default=0, help="n-th record with that key (default 0)")
    p.add_argument('--experimental', action='store_true', help='acknowledge that world-state meanings are unverified')
    p.add_argument("--out")

    p = sub.add_parser("diff", help="record-level delta between two saves")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--json", action="store_true", dest="as_json")

    p = sub.add_parser("events", help="show or edit event flags (bosses, NPC quests, pickups)")
    p.add_argument("file", nargs="?", help="USR-DATA (not needed with --list)")
    p.add_argument("--list", action="store_true", dest="list_known",
                   help="list every known boss flag and NPC state machine")
    p.add_argument("--filter", dest="text", metavar="TEXT",
                   help="only entries whose name or description contains this")
    p.add_argument("--set", action="append", default=[], dest="sets", metavar="[AREA:]ID=0|1",
                   help="set or clear one flag: global by number (--set 4096=0), "
                        "area-local (0..3199, 8192..12287) with its map (--set m02:200=0)")
    p.add_argument("--respawn", metavar="BOSS",
                   help="clear a boss's death flag and its soul-taken flag (name from --list)")
    p.add_argument("--full", action="store_true",
                   help="with --respawn: also clear the fight's fog/cutscene flags and boss-room flags")
    p.add_argument("--defeat", metavar="BOSS",
                   help="mark a boss defeated and hand over what its soul pickup gives "
                        "(the demon soul goes to the inventory)")
    p.add_argument("--no-soul", action="store_true",
                   help="with --defeat: set only the death flag (no soul handed over)")
    p.add_argument("--forgive", metavar="NPC",
                   help="what seeking forgiveness does: a hostile NPC returns to their previous state")
    p.add_argument("--reset-map", metavar="AREA",
                   help="clear every local flag of one map (m01..m08): doors, levers, pickups, events")
    p.add_argument("--rearm-pickups", metavar="AREA", dest="rearm",
                   help="let one map's one-time pickups be picked up again")
    p.add_argument("--sync-copy", action="store_true",
                   help="rebuild the main flag block's copy of the current map's flags from that "
                        "map's own slots (what the game does on load; repairs a mismatch)")
    p.add_argument("--npc", metavar="NPC=STATE",
                   help="put an NPC into exactly one quest state (e.g. baldwin=work)")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument('--experimental', action='store_true',
                   help="acknowledge that event-flag edits are kept by the game but not yet seen in game")
    p.add_argument("--out", help="write to this path instead of in place")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--bank-only", action="store_true", help=argparse.SUPPRESS)

    p = sub.add_parser("tendency", help="show or edit world and character tendency; trigger tendency events")
    p.add_argument("file", nargs="?", help="USR-DATA (not needed with --events)")
    p.add_argument("--set", action="append", default=[], dest="sets", metavar="TARGET=VALUE",
                   help="character, character_lr or a world (boletaria, stonefang, latria, storms, valley); -200..200")
    p.add_argument("--trigger", action="append", default=[], dest="triggers", metavar="EVENT",
                   help="event number from --events: set the tendency its condition needs")
    p.add_argument("--events", action="store_true", dest="list_events", help="list every tendency event")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--out", help="write to this path instead of in place")
    p.add_argument("--no-backup", action="store_true")

    a = ap.parse_args(argv)
    if a.cmd == "tendency" and not a.file and not a.list_events:
        ap.error("tendency needs a file (or --events)")
    reason = EXPERIMENTAL[a.cmd](a) if a.cmd in EXPERIMENTAL else None
    if reason and not a.experimental:
        ap.error(f'{a.cmd} requires --experimental here: {reason}')
    return COMMANDS[a.cmd](a)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, OverflowError, TypeError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
