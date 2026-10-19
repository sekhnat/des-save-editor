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

Writing always leaves a timestamped `.bak` copy next to the file and
recomputes the FNV-1a checksum in the header, so the result is a valid save.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
import time

import des_arrays
import des_diff
import des_fields
import des_items
import des_save
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
    print(f"  souls           : {s['souls']:,}" if isinstance(s['souls'], int) else s['souls'])
    if "soul_level" in s:
        print(f"  soul level      : {s['soul_level']}  (derived from attributes)")
    hp, hpmax, hpbase = s["hp"]
    mp, mpmax, mpbase = s["mp"]
    sp, spmax, spbase = s["sp"]
    print(f"  HP              : {hp} / {hpmax} (body form max {hpbase})")
    print(f"  MP              : {mp} / {mpmax} (body form max {mpbase})")
    print(f"  SP              : {sp} / {spmax} (max {spbase})")
    print(f"  attributes      : " + ", ".join(f"{k[:3].upper()} {v}" for k, v in s["attributes"].items()))
    if s.get("playtime_s") is not None:
        print(f"  play time       : {s['playtime_s']:.0f} s "
              f"({s['playtime_s']/3600:.2f} h)   [raw {s['playtime_ms']:.0f}]")
    print(f"  deaths          : {s['deaths']}")
    ids = des_items.inventory_ids(sf)
    if ids:
        db = des_items.load_db()
        known = sum(1 for i in ids if i in db)
        print(f"  inventory       : {len(ids)} item(s), {known} resolved "
              f"(see `items` command)")
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


def _coerce(meta: dict | None, field: des_save.Field, text: str):
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
        value = _coerce(meta, field, text)
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

    dest = out or path
    if changed:
        if os.path.abspath(dest) == os.path.abspath(path) and not no_backup:
            _backup(path)
        des_save.save(sf, dest)
        print(f"  wrote {dest} ({os.path.getsize(dest)} bytes, checksum recalculated)")
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
    dest = out or path
    if os.path.abspath(dest) == os.path.abspath(path):
        _backup(path)
    des_save.save(sf, dest)
    print(f'  wrote {dest}')
    return 0


def cmd_items(path: str) -> int:
    """List observed u16 values and category-aware candidate names."""
    sf = des_save.load(path)
    db = des_items.load_db()
    ids = des_items.inventory_ids(sf)
    if not db:
        print("itemdb.json not found next to this script - run tools/build_itemdb.py",
              file=sys.stderr)
    print(f"{path}\n  {len(ids)} observed u16 record(s); experimental name candidates, not a verified full inventory")
    for i, item_id in enumerate(ids, 1):
        e = db.get(item_id)
        name = e["name"] if e else "unknown item id"
        cat = e["category"] if e else "?"
        print(f"  {i:2d}. {item_id:6d}  {name:<40} {cat}")
    return 0


def cmd_inv(path: str, add: list[int], rm: list[int], sets: list[str],
            out: str | None) -> int:
    """Add / remove / replace inventory entries."""
    sf = des_save.load(path)
    ids = des_items.inventory_ids(sf)
    for spec in sets:
        idx, _, val = spec.partition("=")
        i, v = int(idx) - 1, int(val, 0)
        if not 0 <= i < len(ids):
            print(f"slot {i + 1} does not exist", file=sys.stderr)
            return 2
        print(f"  slot {i + 1}: {ids[i]} -> {v}")
        ids[i] = v
    for i in sorted((int(x) - 1 for x in rm), reverse=True):
        if not 0 <= i < len(ids):
            print(f"slot {i + 1} does not exist", file=sys.stderr)
            return 2
        print(f"  removed slot {i + 1} ({ids[i]})")
        del ids[i]
    for v in add:
        print(f"  added {v}")
        ids.append(v)
    des_items.set_inventory(sf, ids)
    dest = out or path
    if os.path.abspath(dest) == os.path.abspath(path):
        _backup(path)
    des_save.save(sf, dest)
    db = des_items.load_db()
    print(f"  wrote {dest}: {len(ids)} item(s), count field "
          f"{sf.find(des_items.COUNT_KEY).value}")
    for i, item_id in enumerate(sorted(ids), 1):
        e = db.get(item_id)
        print(f"    {i:2d}. {item_id:6d}  {e['name'] if e else '?'}")
    return 0


def cmd_arrays(path: str, as_json: bool) -> int:
    """List fixed-slot arrays recovered by FNV-state discovery."""
    sf = des_save.load(path)
    rows = des_arrays.report(sf)
    if as_json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{path}\n  {len(rows)} fixed-slot array(s) recovered structurally "
          f"(base names still unknown)")
    for row in rows:
        print(f"\n  @0x{row['offset']:04x}  {row['count']} slots of {row['type']:#04x}"
              f"  state {row['state']:08x}  [{row['kind']}]")
        print(f"      {row['description']}")
        for slot in row['slots']:
            print(f"      slot '{slot['char']}'  0x{slot['key']:08x}  "
                  f"{slot['value']:>10}  {slot['name'] or ''}")
    return 0


def cmd_blobs(path: str) -> int:
    """Describe every blob, including the versioned container header."""
    sf = des_save.load(path)
    rows = des_arrays.blobs(sf)
    total = sum(row['size'] for row in rows)
    print(f"{path}\n  {len(rows)} blob(s), {total} bytes "
          f"({total * 100 // max(len(sf.build()), 1)}% of the file)")
    for row in rows:
        name = row['name'] or f"<{row['key']:08x}>"
        print(f"\n  {name:<28} {row['size']:>7} B  @0x{row['offset']:05x}")
        header = row['header']
        if header:
            print(f"      container v{header['version']}  count {header['count']}  "
                  f"signature {header['signature']}")
            print(f"      {len(row['records'])} embedded typed record(s)")
            for record in row['records'][:8]:
                print(f"        0x{record['key']:08x} "
                      f"{record['name'] or '<unnamed>':<26} = {record['value']}")
    return 0


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
    dest = out or path
    if os.path.abspath(dest) == os.path.abspath(path):
        _backup(path)
    des_save.save(sf, dest)
    print(f"  wrote {dest}")
    return 0


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
        raw = open(path, "rb").read()
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
    raw = open(path, "rb").read()
    sf = SaveFile(raw)
    rebuilt = sf.build()
    print(f"{path}")
    print(f"  size            : {len(raw)} bytes")
    print(f"  fields          : {sum(1 for _ in sf.walk())}")
    print(f"  header checksum : {'valid' if sf.checksum_ok() else 'INVALID'}")
    print(f"  rebuild         : {'byte identical' if rebuilt == raw else 'differs'}")
    return 0 if rebuilt == raw else 1


# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Demon's Souls (PS5) save editor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn, extra in [
        ("info", cmd_info, 0), ("list", cmd_list, 0),
        ("tree", cmd_tree, 0), ("verify", cmd_verify, 0),
    ]:
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

    p = sub.add_parser("items", help="list observed u16 values with candidate item names")
    p.add_argument("file")

    p = sub.add_parser("inv", help="experimental observed-u16-array editing (not a verified inventory)")
    p.add_argument("file")
    p.add_argument('--experimental', action='store_true', help='acknowledge unverified inventory semantics')
    p.add_argument("--add", action="append", default=[], type=lambda x: int(x, 0))
    p.add_argument("--rm", action="append", default=[], metavar="SLOT")
    p.add_argument("--set", action="append", default=[], dest="sets", metavar="SLOT=ID")
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

    p = sub.add_parser("blobs", help="describe each opaque blob and its container header")
    p.add_argument("file")

    p = sub.add_parser("diff", help="record-level delta between two saves")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--json", action="store_true", dest="as_json")

    a = ap.parse_args(argv)
    if a.cmd == 'inv' and not a.experimental:
        ap.error('inv requires --experimental: observed u16 values are not a verified full inventory')
    if a.cmd == "info":   return cmd_info(a.file)
    if a.cmd == "list":   return cmd_list(a.file)
    if a.cmd == "tree":   return cmd_tree(a.file)
    if a.cmd == "verify": return cmd_verify(a.file)
    if a.cmd == "get":    return cmd_get(a.file, a.field)
    if a.cmd == "set":    return cmd_set(a.file, a.assignments, a.out, a.no_backup)
    if a.cmd == "dump":   return cmd_dump(a.file, a.out)
    if a.cmd == "patch":  return cmd_patch(a.file, a.patch, a.out)
    if a.cmd == "items":    return cmd_items(a.file)
    if a.cmd == "inv":      return cmd_inv(a.file, a.add, a.rm, a.sets, a.out)
    if a.cmd == "arrays":   return cmd_arrays(a.file, a.as_json)
    if a.cmd == "aslot":    return cmd_aslot(a.file, a.state, a.sets, a.clear, a.out)
    if a.cmd == "blobs":    return cmd_blobs(a.file)
    if a.cmd == "diff":     return cmd_diff(a.before, a.after, a.as_json)
    if a.cmd == "selftest": return cmd_selftest(a.paths)
    if a.cmd == "fields":   return cmd_fields()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, OverflowError, TypeError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
