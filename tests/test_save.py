"""Dependency-free format, item-array and item-catalog regressions."""
from pathlib import Path
import importlib.util
import math
import os
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SAVES = Path(os.environ.get('DES_SAVE_DIR', ROOT.parent / '_SaveData' / 'PPSA01341'))
HAVE_SAVES = any(SAVES.glob('*/USR-DATA'))
GAME = Path(os.environ.get('DES_GAME_DIR', ROOT.parent / 'PPSA01342-app'))
HAVE_GAME = (GAME / 'misc/cachedsavedata').is_dir()
sys.path.insert(0, str(ROOT))
import des_save as save
import des_items as items
import des_arrays as arrays
import des_diff as diff
import des_world as world
import des_inventory as inventory

spec = importlib.util.spec_from_file_location('build_itemdb', ROOT / 'tools/build_itemdb.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


GUID_A = bytes.fromhex('b13668dff82e7044840eea38f10b0286')
GUID_B = bytes.fromhex('ca79214aa62b1a4cb67a4ab427a13259')
GUID_C = bytes.fromhex('668f4b49e8017852b0ef502ef9baaa72')


def entry(guid, payload, kind=7):
    return guid + struct.pack('<II', kind, len(payload)) + payload


def record(key, ftype, raw):
    return struct.pack('<IB', key, ftype) + raw


def world_blob():
    """Two groups: two decodable entries, then one entry kept raw."""
    first = (record(0xE02849CE, save.T_I32, (0).to_bytes(4, 'little'))
             + record(0x0D935360, save.T_BOOL, b'\x01'))
    second = record(0xE9EB7C2A, save.T_U16, b'\x05\x00')
    unknown = struct.pack('<IB', 0x11223344, 0x10) + b'\xaa\xbb'
    return (struct.pack('<II', 3, 2) + entry(GUID_A, first) + entry(GUID_B, second, 8)
            + struct.pack('<II', 3, 1) + entry(GUID_C, unknown, 13))


class WorldTests(unittest.TestCase):
    """World-state framing: strict decode, exact rebuild, same-size edits."""

    def test_decode_and_exact_rebuild(self):
        raw = world_blob()
        groups = world.decode(raw)
        self.assertEqual([2, 1], [len(group.entries) for group in groups])
        listed = [entry for _, _, entry in world.entries(groups)]
        self.assertEqual([GUID_A, GUID_B, GUID_C], [entry.guid for entry in listed])
        self.assertEqual([7, 8, 13], [entry.kind for entry in listed])
        self.assertEqual([0xE02849CE, 0x0D935360], [r.key for r in listed[0].records])
        self.assertIsNone(listed[2].records)
        self.assertEqual(raw, world.encode(groups))

    def test_malformed_framing_is_left_opaque(self):
        raw = world_blob()
        bad = [raw[:-1], raw + b'\0', b'\x04' + raw[1:], raw[:4] + b'\xff\xff\x00\x00' + raw[8:],
               b'', b'\x03\0\0\0', raw[:8] + raw[8:24] + b'\x07\0\0\0\xff\xff\xff\x7f']
        for data in bad:
            with self.subTest(data=data[:12].hex()):
                self.assertIsNone(world.decode(data))

    def test_set_value_changes_exactly_one_value(self):
        raw = world_blob()
        edited = world.set_value(raw, GUID_A, 0xE02849CE, 1)
        self.assertEqual(len(raw), len(edited))
        self.assertEqual(1, sum(a != b for a, b in zip(raw, edited)))
        self.assertEqual(1, world.decode(edited)[0].entries[0].records[0].value)
        self.assertEqual(7, world.decode(world.set_value(raw, GUID_B, 0xE9EB7C2A, 7))[0].entries[1].records[0].value)

    def test_set_value_refuses_what_it_cannot_do_safely(self):
        raw = world_blob()
        for args in ((GUID_A, 0x0D935360, 2),            # bool outside 0/1
                     (GUID_B, 0xE9EB7C2A, 65536),        # u16 overflow
                     (GUID_B, 0xE9EB7C2A, 1.5),          # fractional integer
                     (GUID_A, 0xE02849CE, 1, 1),         # occurrence that does not exist
                     (GUID_C, 0x11223344, 1),            # raw entry
                     (GUID_A, 0x99999999, 1)):           # unknown key
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    world.set_value(raw, *args)
        with self.assertRaises(ValueError):
            world.set_value(b'\x01' * 16, GUID_A, 0xE02849CE, 1)

    def test_world_diff_reports_the_changed_entity_record(self):
        before = save.SaveFile()
        before.records = [save.Field(0x6D87F588, save.T_BLOB, world_blob())]
        after = save.SaveFile(before.build())
        after.records[0].raw = world.set_value(after.records[0].raw, GUID_A, 0xE02849CE, 1)
        delta = diff.compare(save.SaveFile(before.build()), save.SaveFile(after.build()))['world']
        self.assertEqual([(GUID_A.hex(), 0xE02849CE, '0', '1')],
                         [(r['guid'], r['key'], r['before'], r['after']) for r in delta['changed']])
        self.assertEqual([], delta['added_entities'])

    def test_cli_wset_needs_experimental_and_writes_a_valid_save(self):
        import des_editor
        sf = save.SaveFile()
        sf.records = [save.Field(0x6D87F588, save.T_BLOB, world_blob())]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'USR-DATA'
            path.write_bytes(sf.build())
            with self.assertRaises(SystemExit):
                des_editor.main(['wset', str(path), GUID_A.hex(), '0xe02849ce=1'])
            self.assertEqual(0, des_editor.main(['wset', str(path), GUID_A.hex(), '0xe02849ce=1',
                                                 '--experimental']))
            again = save.SaveFile(path.read_bytes())
            self.assertTrue(again.checksum_ok())
            self.assertEqual(1, world.decode(again.records[0].raw)[0].entries[0].records[0].value)

    def test_entity_index_lookup_and_ambiguity(self):
        import gzip
        paths = ['cp11/objects/_cmn/o0300_archstone', 'worlds/m02_00_00_00/a/_cmn/m02_00_sec05_towerl']
        text = ('\n'.join(paths) + '\n\nm02_00\tBoletaria 1-1').encode()
        prefixes = sorted([GUID_A[:6], GUID_C[:6], b'\xff' * 6])
        owners = {GUID_A[:6]: 0, GUID_C[:6]: 1, b'\xff' * 6: 0xFFFF}
        raw = (b'DESE' + struct.pack('<III', 1, len(prefixes), len(text)) + text
               + b''.join(bytes(p[i] for p in prefixes) for i in range(6))
               + struct.pack(f'<{len(prefixes)}H', *(owners[p] for p in prefixes)))
        index = world.EntityIndex(gzip.compress(raw))
        self.assertEqual('o0300_archstone', index.lookup(GUID_A))
        self.assertEqual('Boletaria 1-1 · m02_00_sec05_towerl', index.lookup(GUID_C))
        self.assertIsNone(index.lookup(GUID_B))
        self.assertIsNone(index.lookup(b'\xff' * 16))              # ambiguous prefix
        with self.assertRaises(ValueError):
            world.EntityIndex(gzip.compress(raw[:-1]))

    def test_page_carries_the_current_entity_index(self):
        spec = importlib.util.spec_from_file_location('embed_entitydb', ROOT / 'tools/embed_entitydb.py')
        embed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(embed)
        db = ROOT / 'entitydb.bin'
        html = (ROOT / 'des_editor.html').read_text(encoding='utf-8')
        self.assertEqual(html, embed.embed(html, db.read_bytes() if db.exists() else None),
                         'run tools/embed_entitydb.py')

    @unittest.skipUnless(HAVE_SAVES and (ROOT / 'entitydb.bin').exists(), 'needs sample saves and entitydb.bin')
    def test_entity_index_labels_the_sample_entities(self):
        index = world.default_index()
        self.assertEqual('o0300_archstone', index.lookup(GUID_A))
        for path in SAVES.glob('*PlayerProfile*/USR-DATA'):
            with self.subTest(path=path):
                for _, groups in world.world_blobs(save.SaveFile(path.read_bytes())):
                    listed = [entry for _, _, entry in world.entries(groups)]
                    labelled = sum(1 for entry in listed if index.lookup(entry.guid))
                    # three GUIDs in the larger sample occur nowhere in the game files
                    self.assertGreaterEqual(labelled, len(listed) - 6)

    @unittest.skipUnless(HAVE_SAVES, 'no sample saves (set DES_SAVE_DIR to run this)')
    def test_real_world_blobs_decode_and_rebuild(self):
        for path in SAVES.glob('*PlayerProfile*/USR-DATA'):
            with self.subTest(path=path):
                found = world.world_blobs(save.SaveFile(path.read_bytes()))
                self.assertEqual([0x6D87F588], [blob.key for blob, _ in found])
                for blob, groups in found:
                    self.assertEqual(blob.raw, world.encode(groups))
                    self.assertEqual(4, len(groups))

    @unittest.skipUnless(HAVE_GAME, 'no game files (set DES_GAME_DIR to run this)')
    def test_game_baseline_files_use_the_same_framing(self):
        files = sorted((GAME / 'misc/cachedsavedata').glob('*.txt'))
        self.assertGreater(len(files), 100)
        for path in files:
            raw = path.read_bytes()
            groups = world.decode(raw)
            self.assertIsNotNone(groups, path.name)
            self.assertEqual(raw, world.encode(groups), path.name)


def inventory_save(entries, storage=()):
    """Records laid out like the game: count, then 8 records per inventory entry."""
    k = save.name_key
    i32 = lambda v: (v & 0xFFFFFFFF).to_bytes(4, 'little')
    records = [save.Field(k('EQUIPMENT_INVENTORY_COUNT'), save.T_I32, i32(len(entries)))]
    for n, (type_bits, equip_id, quantity, durability) in enumerate(entries):
        p = f'EQUIPMENT_INVENTORY{n:02d}_'
        records += [save.Field(k(p + 'INDEX'), save.T_I32, i32(n)),
                    save.Field(k(p + 'TYPE'), save.T_I32, i32(type_bits)),
                    save.Field(k(p + 'EQUIPID'), save.T_I32, i32(equip_id)),
                    save.Field(k(p + 'QUANTITY'), save.T_RAW4, quantity.to_bytes(4, 'little')),
                    save.Field(k(p + 'VARIATIONID'), save.T_I32, i32(n)),
                    save.Field(k(p + 'DISPLAYID'), save.T_I32, i32(0)),
                    save.Field(k(p + 'DURABILITY_CURRENT'), save.T_I32, i32(durability)),
                    save.Field(k(p + 'DURABILITY_ACCUMULATEDHITS'), save.T_I32, i32(0))]
    for n, (typed_id, low) in enumerate(storage):
        p = f'EQUIPMENT_STORAGEBOX{n:02d}_'
        records += [save.Field(k(p + 'DISPLAYID'), save.T_I32, i32(0)),
                    save.Field(k(p + 'EQUIPTYPEID'), save.T_I32, i32(typed_id)),
                    save.Field(k(p + 'DURABILITY'), save.T_I32, i32(0)),
                    save.Field(k(p + 'DURABILITY_ACCUMULATEDHITS'), save.T_I32, i32(0)),
                    save.Field(k(p + 'LOWQUANTITY'), save.T_U8, bytes([low])),
                    save.Field(k(p + 'HIGHQUANTITY'), save.T_U8, b'\0')]
    records += [save.Field(k('EQUIPMENT_SLOT00_INVENTORYID'), save.T_I32, i32(0)),
                save.Field(k('EQUIPMENT_SLOT00_EQUIPMENTID'), save.T_I32, i32(entries[0][1]))]
    sf = save.SaveFile()
    sf.records = records
    return save.SaveFile(sf.build())


class InventoryTests(unittest.TestCase):
    ITEMS = [(0, 150000, 1, 200), (0x10000000, 100100, 1, 98), (0x20000000, 105, 1, 0),
             (0x40000000, 1001, 32, 0)]

    def test_categories_names_and_quantities(self):
        sf = inventory_save(self.ITEMS, [(0x40000000 | 2000, 25), (20400, 1)])
        rows = inventory.inventory(sf)
        self.assertEqual(['Weapon', 'Armor', 'Ring', 'Goods'], [r['category'] for r in rows])
        self.assertEqual(['Buckler', 'Silver Coronet', 'Fragrant Ring', 'Half Moon Grass'],
                         [r['name'] for r in rows])
        self.assertEqual([1, 1, 1, 32], [r['quantity'] for r in rows])
        self.assertTrue(all(r['complete'] for r in rows))
        box = inventory.storage(sf)
        self.assertEqual([('Goods', 2000, 'Hardstone Shard', 25), ('Weapon', 20400, 'Bastard Sword', 1)],
                         [(r['category'], r['id'], r['name'], r['low_quantity']) for r in box])
        self.assertEqual([(0, 0, 'Buckler')],
                         [(r['slot'], r['inventory'], r['name']) for r in inventory.equipment(sf)])

    def test_entries_past_index_99_are_read_and_edited(self):
        # "%02d" prints three digits from 100 on; the original game holds 0x800 entries
        many = [(0x40000000, 1001 + n % 5, 1 + n % 90, 0) for n in range(300)]
        sf = save.SaveFile(inventory_save(many, [(0x40000000 | 2000, 7)] * 130).build())
        rows = inventory.inventory(sf)
        self.assertEqual(list(range(300)), [r['index'] for r in rows])
        self.assertTrue(all(r['complete'] and r['name'] for r in rows))
        self.assertEqual(130, len(inventory.storage(sf)))
        inventory.set_quantity(sf, 250, 77)
        inventory.set_storage_quantity(sf, 120, 9)
        again = save.SaveFile(sf.build())
        self.assertEqual(77, inventory.inventory(again)[250]['quantity'])
        self.assertEqual(9, inventory.storage(again)[120]['low_quantity'])
        import des_fields
        self.assertEqual('EQUIPMENT_INVENTORY250_QUANTITY',
                         des_fields.field_name(save.name_key('EQUIPMENT_INVENTORY250_QUANTITY')))

    def test_edits_change_only_the_addressed_value(self):
        sf = inventory_save(self.ITEMS, [(0x40000000 | 2000, 25)])
        before = sf.build()
        inventory.set_quantity(sf, 3, 99)
        inventory.set_durability(sf, 0, 150)
        inventory.set_storage_quantity(sf, 0, 30)
        after = sf.build()
        self.assertEqual(len(before), len(after))
        rows = inventory.inventory(save.SaveFile(after))
        self.assertEqual((99, 150), (rows[3]['quantity'], rows[0]['durability']))
        self.assertEqual(30, inventory.storage(save.SaveFile(after))[0]['low_quantity'])

    def test_invalid_edits_are_refused_without_changes(self):
        sf = inventory_save(self.ITEMS)
        before = sf.build()
        for call in (lambda: inventory.set_quantity(sf, 3, 0),
                     lambda: inventory.set_quantity(sf, 3, 1000),
                     lambda: inventory.set_quantity(sf, 3, 1.5),
                     lambda: inventory.set_quantity(sf, 9, 1),
                     lambda: inventory.set_durability(sf, 0, -1),
                     lambda: inventory.set_storage_quantity(sf, 0, 1)):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(before, sf.build())

    def test_incomplete_entries_are_listed_but_not_edited(self):
        sf = inventory_save(self.ITEMS)
        sf.records = [f for f in sf.records if f.key != save.name_key('EQUIPMENT_INVENTORY01_QUANTITY')]
        rows = inventory.inventory(sf)
        self.assertFalse(rows[1]['complete'])
        with self.assertRaises(ValueError):
            inventory.set_durability(sf, 1, 10)

    def test_cli_inv_needs_experimental_and_writes_a_valid_save(self):
        import des_editor
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'USR-DATA'
            path.write_bytes(inventory_save(self.ITEMS).build())
            with self.assertRaises(SystemExit):
                des_editor.main(['inv', str(path), '--qty', '3=50'])
            self.assertEqual(0, des_editor.main(['inv', str(path), '--qty', '3=50', '--experimental']))
            self.assertEqual(50, inventory.inventory(save.SaveFile(path.read_bytes()))[3]['quantity'])

    @unittest.skipUnless(HAVE_SAVES, 'no sample saves (set DES_SAVE_DIR to run this)')
    def test_every_sample_item_resolves_and_counts_match(self):
        for path in SAVES.glob('*PlayerProfile*/USR-DATA'):
            with self.subTest(path=path):
                sf = save.SaveFile(path.read_bytes())
                rows = inventory.inventory(sf)
                self.assertEqual(sf.get('EQUIPMENT_INVENTORY_COUNT'), len(rows))
                self.assertTrue(all(r['complete'] and r['name'] for r in rows))
                box = inventory.storage(sf)
                self.assertEqual(sf.get('EQUIPMENT_STORAGEBOX_COUNT') or 0, len(box))
                self.assertTrue(all(r['name'] for r in box))
                self.assertEqual(sf.get('DEADENEMIES_COUNT') or 0, len(items.dead_enemies(sf)))


class SaveTests(unittest.TestCase):
    def test_signed_int_round_trip(self):
        f = save.Field(1, save.T_I32, b'\xff' * 4)
        self.assertEqual(-1, f.value)
        for value in (-2147483648, -1, 0, 2147483647):
            f.value = value
            self.assertEqual(value, f.value)

    def test_invalid_values_leave_bytes_unchanged(self):
        for ftype, values in ((save.T_U8, (-1, 256, 1.5)), (save.T_U16, (-1, 65536)),
                              (save.T_I32, (-2147483649, 2147483648)),
                              (save.T_F32, (math.nan, math.inf, 1e40))):
            for value in values:
                with self.subTest(type=ftype, value=value):
                    f = save.Field(1, ftype, bytes(save.SIZES[ftype]))
                    before = f.raw
                    with self.assertRaises((ValueError, OverflowError, TypeError)):
                        f.value = value
                    self.assertEqual(before, f.raw)

    def test_truncated_data_rejected(self):
        for data in (b'\x01\0\0\0\x08\x01', b'\x01\0\0\0\x0d\x04A',
                     b'\x01\0\0\0\x0e\x80', b'\x01\0\0\0\x06\x01', b'\x01\0\0\0'):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    save.parse(data)

    def test_invalid_varints_rejected(self):
        for value in (-1, 2**32):
            with self.assertRaises(ValueError):
                save._write_varint(value)
        for data in (b'\x80', b'\xff' * 5, b'\x80' * 6):
            with self.assertRaises(ValueError):
                save._read_varint(data, 0)

    @unittest.skipUnless(HAVE_SAVES, 'no sample saves (set DES_SAVE_DIR to run this)')
    def test_real_saves_round_trip(self):
        for path in SAVES.glob('*/USR-DATA'):
            with self.subTest(path=path):
                original = path.read_bytes()
                sf = save.SaveFile(original)
                self.assertTrue(sf.checksum_ok())
                self.assertEqual(original, sf.build())

    def test_slot_index_bounds(self):
        for index in (-1, 40, 1.5):
            with self.assertRaises((ValueError, TypeError)):
                items.slot_key(index)

    def test_atomic_writer_keeps_original_on_replace_failure(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'USR-DATA'
            path.write_bytes(b'original bytes')
            sf = save.SaveFile()
            sf.records = [save.Field(1, save.T_U8, b'\x01')]
            with patch('des_save.os.replace', side_effect=OSError('simulated failure')):
                with self.assertRaises(OSError):
                    save.save(sf, str(path))
            self.assertEqual(b'original bytes', path.read_bytes())
            self.assertEqual([path], list(Path(tmp).iterdir()))

    def test_cli_rejects_partial_patch_and_preserves_original(self):
        import des_editor
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'USR-DATA'
            patch = Path(tmp) / 'patch.json'
            sf = save.SaveFile()
            sf.records = [save.Field(save.name_key('PLAYER_SOULS'), save.T_I32, (176).to_bytes(4, 'little'))]
            path.write_bytes(sf.build())
            original = path.read_bytes()
            patch.write_text(json.dumps({'PLAYER_SOULS': 42, 'DOES_NOT_EXIST': 1}))
            with self.assertRaises(ValueError):
                des_editor.cmd_patch(str(path), str(patch), None)
            self.assertEqual(original, path.read_bytes())
            self.assertEqual([], list(Path(tmp).glob('*.bak')))

    def test_cli_change_patch_supports_repeated_keys_by_path(self):
        import des_editor
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path, out = Path(tmp) / 'USR-DATA', Path(tmp) / 'edited'
            patch = Path(tmp) / 'patch.json'
            sf = save.SaveFile()
            sf.records = [save.Field(123, save.T_U8, b'\x01'), save.Field(123, save.T_U8, b'\x02')]
            path.write_bytes(sf.build())
            patch.write_text(json.dumps({'format': 'des-patch-1', 'version': 7,
                                        'changes': [{'path': '/1', 'key': '7b', 'type': 2, 'before': '02', 'hex': '03'}]}))
            des_editor.cmd_patch(str(path), str(patch), str(out))
            self.assertEqual([1, 3], [f.value for f in save.load(str(out)).records])


class StructureTests(unittest.TestCase):
    """Fixed-slot array recovery, slot addressing and the differential harness."""

    STATE = 0x7516F500

    def array_save(self, values, state=None):
        state = self.STATE if state is None else state
        sf = save.SaveFile()
        sf.records = [save.Field(arrays.key_for_state(state, str(index)), save.T_I32,
                                 int(value).to_bytes(4, 'little', signed=True))
                      for index, value in enumerate(values)]
        return sf

    def parsed(self, sf):
        return save.SaveFile(sf.build())

    def test_slot_key_set_is_unchanged_by_the_relabelling(self):
        observed = {((prefix ^ (0x30 + digit)) * items.P) & items.M
                    for prefix in (0x1544B3EC, 0x1444B25A, 0x1344B0C6, 0x1244AF34)
                    for digit in range(10)}
        self.assertEqual(observed, set(items.ALL_SLOT_KEYS))
        self.assertEqual(40, len(observed))

    def test_slot_key_follows_the_observed_file_order(self):
        # first two records of the real profile-0 array, in file order
        self.assertEqual(0x582724E7, items.slot_key(0))
        self.assertEqual(0x57272354, items.slot_key(1))
        self.assertEqual(0xC61F834C, items.slot_key(30))

    def test_canonical_state_labels_slots_from_zero(self):
        members = [save.Field(arrays.key_for_state(self.STATE, str(index)), save.T_I32, b'\0' * 4)
                   for index in range(4)]
        self.assertEqual(self.STATE, arrays.canonical_state(members, self.STATE ^ 0x07))

    def test_discovery_finds_a_contiguous_digit_array(self):
        sf = self.parsed(self.array_save([105, 9962, 113]))
        groups = arrays.discover(sf)
        self.assertEqual(1, len(groups))
        self.assertEqual(self.STATE, groups[0]['state'])
        self.assertEqual([105, 9962, 113], [f.value for f in groups[0]['members']])
        self.assertEqual('012', ''.join(slot['char'] for slot in arrays.report(sf)[0]['slots']))

    def test_a_gap_stops_array_detection(self):
        sf = self.array_save([105, 9962, 113])
        sf.records.insert(1, save.Field(0xDEADBEEF, save.T_U8, b'\x00'))
        self.assertEqual([], arrays.discover(self.parsed(sf)))

    def test_set_and_clear_slot_round_trip(self):
        sf = self.parsed(self.array_save([105, 9962, 113, 116]))
        arrays.set_slot(sf, self.STATE, '2', 1002)
        arrays.clear_slot(sf, self.STATE, '3')
        again = self.parsed(sf)
        self.assertEqual([105, 9962, 1002, -1],
                         [f.value for f in arrays.discover(again)[0]['members']])
        self.assertEqual(sf.build(), again.build())

    def test_set_slot_rejects_unknown_state_and_non_integer(self):
        sf = self.parsed(self.array_save([105, 9962, 113]))
        before = sf.build()
        for call in (lambda: arrays.set_slot(sf, 0x12345678, '0', 1),
                     lambda: arrays.set_slot(sf, self.STATE, 'x', 1),
                     lambda: arrays.set_slot(sf, self.STATE, '0', 't')):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(before, sf.build())

    def test_blobs_summarise_world_state(self):
        sf = save.SaveFile()
        sf.records = [save.Field(0x6D87F588, save.T_BLOB, world_blob()),
                      save.Field(0x1234, save.T_BLOB, b'\x01' * 16)]
        rows = {row['key']: row for row in arrays.blobs(self.parsed(sf))}
        self.assertEqual({'groups': 2, 'entries': 3, 'parsed': 2}, rows[0x6D87F588]['world'])
        self.assertIsNone(rows[0x1234]['world'])

    def test_diff_of_a_save_with_itself_is_empty(self):
        sf = self.parsed(self.array_save([1, 2, 3]))
        delta = diff.compare(sf, sf)
        self.assertEqual(([], [], []), (delta['added'], delta['removed'], delta['changed']))

    def test_diff_reports_changed_added_and_removed(self):
        before = save.SaveFile()
        before.records = [save.Field(1, save.T_U8, b'\x01'), save.Field(2, save.T_U8, b'\x09')]
        after = save.SaveFile()
        after.records = [save.Field(1, save.T_U8, b'\x02'), save.Field(3, save.T_U16, b'\x05\x00')]
        delta = diff.compare(before, after)
        self.assertEqual(1, len(delta['changed']))
        self.assertEqual(1, len(delta['added']))
        self.assertEqual(1, len(delta['removed']))
        self.assertIn('added', diff.summarise(delta))

    def test_cli_aslot_writes_a_valid_save(self):
        import des_editor
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'USR-DATA'
            path.write_bytes(self.array_save([105, 9962, 113]).build())
            self.assertEqual(0, des_editor.main(['aslot', str(path), '7516f500', '--set', '1=1002']))
            self.assertEqual(0, des_editor.main(['verify', str(path)]))
            again = save.SaveFile(path.read_bytes())
            self.assertEqual([105, 1002, 113],
                             [f.value for f in arrays.discover(again)[0]['members']])


class ParamdefTests(unittest.TestCase):
    """PARAMDEF layout: byte sizes, bit fields, and refusal of mismatched rows."""

    @staticmethod
    def paramdef(kind, fields):
        import des_gamedata
        head = struct.pack('<IHHH', 0, 0x30, 1, len(fields)) + b'\0\0' + kind.encode().ljust(0x20, b'\0')
        head = head.ljust(0x30, b'\0')
        body = b''
        for display_type, size, name in fields:
            rec = bytearray(des_gamedata.PARAMDEF_FIELD)
            rec[0x40:0x40 + len(display_type)] = display_type.encode()
            struct.pack_into('<i', rec, 0x64, size)
            rec[0x90:0x90 + len(name)] = name.encode()
            body += bytes(rec)
        return head + body

    @staticmethod
    def param(kind, rows, stride):
        head = bytearray(0x30)
        struct.pack_into('<H', head, 0x0A, len(rows))
        head[0x0C:0x0C + len(kind)] = kind.encode()
        index = b''
        data = b''
        start = 0x30 + 12 * len(rows)
        for n, (row_id, payload) in enumerate(rows):
            index += struct.pack('<III', row_id, start + n * stride, 0)
            data += payload.ljust(stride, b'\0')
        return bytes(head) + index + data

    def test_layout_with_bit_fields_reads_values(self):
        import des_gamedata
        definition = self.paramdef('T_ST', [('s32', 4, 'hp'), ('u8', 1, 'a:1'), ('u8', 1, 'b:3'),
                                            ('u8', 1, 'c:4'), ('u16', 2, 'n')])
        layout, size = des_gamedata.paramdef_layout(des_gamedata.parse_paramdef(definition)['fields'])
        self.assertEqual(7, size)          # s32 + one byte shared by 1+3+4 bits + u16
        packed = 1 | (0b101 << 1) | (1 << 4)
        payload = struct.pack('<i', 450) + bytes([packed]) + struct.pack('<H', 99)
        self.assertEqual([0, 4, 4, 4, 5], [field['offset'] for field in layout])
        rows = des_gamedata.read_param(definition, self.param('T_ST', [(7, payload)], 7))
        self.assertEqual({'hp': 450, 'a': 1, 'b': 0b101, 'c': 1, 'n': 99}, {k: rows[7][k] for k in 'hp a b c n'.split()})

    def test_mismatched_row_size_or_type_is_refused(self):
        import des_gamedata
        definition = self.paramdef('T_ST', [('s32', 4, 'hp')])
        rows = [(1, b''), (2, b'')]
        with self.assertRaises(ValueError):
            des_gamedata.read_param(definition, self.param('T_ST', rows, 8))     # rows were extended
        with self.assertRaises(ValueError):
            des_gamedata.read_param(definition, self.param('OTHER_ST', rows, 4))

    @unittest.skipUnless(HAVE_GAME, 'no game files (set DES_GAME_DIR to run this)')
    def test_game_tables_and_classes(self):
        import des_gamedata
        tables = des_gamedata.load_params(GAME)
        self.assertIn('CHARACTER_INIT_PARAM', tables)
        self.assertNotIn('MAGIC_PARAM_ST', tables)          # remaster extended its rows
        self.assertEqual(50, tables['EQUIP_PARAM_GOODS_ST'][1000]['maxQuantity'])
        catalog = builder.build_catalog(GAME, 'en-gb')
        names = [c['name'] for c in catalog['classes']]
        self.assertEqual(['Soldier', 'Knight', 'Hunter', 'Priest', 'Magician', 'Wanderer',
                          'Barbarian', 'Thief', 'Temple Knight', 'Royalty'], names)

    @unittest.skipUnless(HAVE_SAVES, 'no sample saves (set DES_SAVE_DIR to run this)')
    def test_sample_archetypes_match_their_class_rows(self):
        classes = {c['archetype']: c for c in items.load_classes()}
        stats = ['VITALITY', 'INTELLIGENCE', 'ENDURANCE', 'STRENGTH', 'DEXTERITY', 'MAGIC', 'FAITH', 'LUCK']
        for path in SAVES.glob('*PlayerProfile*/USR-DATA'):
            with self.subTest(path=path):
                sf = save.SaveFile(path.read_bytes())
                base = [sf.get('PLAYER_BASE' + name) for name in stats]
                start = classes[sf.get('PLAYER_ARCHETYPE')]['baseStats']
                self.assertTrue(all(b >= c for b, c in zip(base, start)), (base, start))
                if sum(base) - 80 == classes[sf.get('PLAYER_ARCHETYPE')]['soulLevel']:
                    self.assertEqual(start, base)


class LoadoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('parse_loadouts', ROOT / 'tools/parse_loadouts.py')
        cls.loadouts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.loadouts)

    def test_statements_arguments_and_quirks(self):
        text = ('waitForLevelLoading\nprint "Applying player loadout"\n*stage "General"\n'
                '\tcp11_setPlayerName name = "Soul Gooder"\n\tcp11_numSpellSlotsUnlocked 1\n'
                '\tcp11_addGoods id = 1000 quantity = 6 // Crescent Moon Grass\r\n*endstage\n'
                '*gowaitForLevelLoading\n')
        rows = self.loadouts.parse(text, 'x.txt')
        self.assertEqual(['cp11_setPlayerName', 'cp11_numSpellSlotsUnlocked', 'cp11_addGoods'],
                         [r['command'] for r in rows])
        self.assertEqual({'name': 'Soul Gooder'}, rows[0]['args'])
        self.assertEqual([1], rows[1]['positional'])
        self.assertEqual(({'id': 1000, 'quantity': 6}, 'Crescent Moon Grass', 'General'),
                         (rows[2]['args'], rows[2]['comment'], rows[2]['stage']))

    def test_unparseable_lines_raise_or_are_recorded(self):
        bad = 'cp11_setPlayerName name = Berserker"\nmystery 1\ncp11_setSouls souls = 5\n'
        with self.assertRaises(ValueError):
            self.loadouts.parse(bad, 'x.txt')
        errors = []
        rows = self.loadouts.parse(bad, 'x.txt', errors)
        self.assertEqual(['cp11_setSouls'], [r['command'] for r in rows])
        self.assertEqual(2, len(errors))

    @unittest.skipUnless(HAVE_GAME, 'no game files (set DES_GAME_DIR to run this)')
    def test_game_loadouts_agree_with_the_catalog_and_level_formula(self):
        errors = []
        report = self.loadouts.check(self.loadouts.load(GAME, errors), items.load_catalog(), errors)
        self.assertGreater(report['ids_checked'], 6000)
        self.assertLessEqual(len(report['missing_ids']), 2)      # Official Cap, Moon Mace
        self.assertGreater(len(report['soul_levels']), 50)
        self.assertEqual([], report['soul_level_mismatches'])   # SL = sum(base stats) - 80
        self.assertLessEqual(len(report['unparsed_lines']), 1)


class CatalogTests(unittest.TestCase):
    def test_bnd3_bad_bounds_rejected(self):
        with self.assertRaises(ValueError):
            builder.parse_bnd3(b'BND3')

    def test_param_only_reads_row_ids(self):
        data = bytearray(0x30 + 12)
        struct.pack_into('<H', data, 10, 1)
        struct.pack_into('<III', data, 0x30, 100, 0, 0xffffffff)
        self.assertEqual({100}, set(builder.parse_param(data)))

    def test_categories_with_shared_ids_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / 'text/ds/_cmn'
            text.mkdir(parents=True)
            (text / 'goods_name.en-gb.ctxt').write_text('GOODS_NAME_1000:12345678=Crescent Moon Grass\n', encoding='utf-8')
            (text / 'magic_name.en-gb.ctxt').write_text('MAGIC_NAME_1000:12345678=Soul Arrow\n', encoding='utf-8')
            doc = builder.build_catalog(root, 'en-gb')
            by_category = {(e['category'], e['id']): e['name'] for e in doc['items']}
            self.assertEqual('Crescent Moon Grass', by_category['Goods', 1000])
            self.assertEqual('Soul Arrow', by_category['Spell', 1000])


class FieldTableTests(unittest.TestCase):
    def test_family_names_match_the_measured_keys(self):
        import des_fields
        # slot_key(0) of the observed u16 array, measured long before its name was known
        self.assertEqual('DEADENEMIES_INDICES0000', des_fields.field_name(items.slot_key(0)))
        self.assertEqual('EQUIPMENT_INVENTORY00_EQUIPID', des_fields.field_name(0x5C607E92))
        # canonical slot letters are only defined up to an XOR of the alphabet,
        # so the set of names is what the hash inversion establishes
        self.assertEqual({f'TROPHIES_RING{i:02d}' for i in range(8)},
                         {des_fields.field_name(arrays.key_for_state(0x7516F500, c)) for c in '01234567'})
        self.assertEqual('BOSS_LOOT_VISIBLE', des_fields.world_name(0xE02849CE))
        self.assertIsNone(des_fields.lookup(0x5C607E92))      # names only, no editor metadata

    def test_keydb_template_expansion_and_matching(self):
        spec = importlib.util.spec_from_file_location('build_keydb', ROOT / 'tools/build_keydb.py')
        keydb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(keydb)
        self.assertEqual('CCSlot_Gender_03', keydb._expand('CCSlot_Gender_%02d')[3])
        self.assertEqual('DeadEnemies_Indices0042', keydb._expand('DeadEnemies_Indices%04d')[42])
        key = save.name_key('EQUIPMENT_INVENTORY00_EQUIPID')
        rows = keydb.match({'EQUIPMENT_INVENTORY00_EQUIPID': {'eboot.bin (template)'}, 'NOPE': {'x'}},
                           {key: {'types': {save.T_I32}, 'where': {'top'}, 'sample': 150000}})
        self.assertEqual([f'{key:08x}'], [row['key'] for row in rows])
        self.assertEqual('EQUIPMENT_INVENTORY00_EQUIPID', rows[0]['known'])

    def test_page_field_table_is_generated_from_des_fields(self):
        spec = importlib.util.spec_from_file_location('embed_fields', ROOT / 'tools/embed_fields.py')
        embed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(embed)
        html = (ROOT / 'des_editor.html').read_text(encoding='utf-8')
        self.assertEqual(html, embed.embed(html), 'run tools/embed_fields.py')

    def test_every_name_hashes_to_its_key_and_layout_names_exist(self):
        import des_fields
        for key, meta in des_fields.FIELDS.items():
            self.assertEqual(key, save.name_key(meta['name']))
        for names in des_fields.LAYOUT.values():
            for name in names:
                self.assertIn(name, des_fields.BY_NAME)


if __name__ == '__main__':
    unittest.main()
