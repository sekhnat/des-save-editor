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
sys.path.insert(0, str(ROOT))
import des_save as save
import des_items as items
import des_arrays as arrays
import des_diff as diff

spec = importlib.util.spec_from_file_location('build_itemdb', ROOT / 'tools/build_itemdb.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


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

    def test_empty_array_inserts_before_its_count(self):
        sf = save.SaveFile()
        count = save.Field(items.COUNT_KEY, save.T_U16, b'\0\0')
        tail = save.Field(1, save.T_U8, b'\0')
        sf.records = [count, tail]
        items.set_inventory(sf, [113])
        self.assertEqual([items.slot_key(0), items.COUNT_KEY, 1], [f.key for f in sf.records])
        self.assertEqual(1, count.value)

    def test_invalid_array_write_is_atomic(self):
        sf = save.SaveFile()
        sf.records = [save.Field(items.COUNT_KEY, save.T_U16, b'\0\0')]
        before = sf.build()
        with self.assertRaises(ValueError):
            items.set_inventory(sf, [100, 70000])
        self.assertEqual(before, sf.build())

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

    def test_blob_header_and_embedded_records(self):
        head = (3).to_bytes(4, 'little') + (188).to_bytes(4, 'little') + bytes.fromhex('b13668dff82e7044')
        self.assertEqual({'version': 3, 'count': 188, 'signature': 'b13668dff82e7044',
                          'size': 16}, arrays.blob_header(head))
        self.assertIsNone(arrays.blob_header(b'\x01' * 16))
        record = ((7).to_bytes(4, 'little') + (9).to_bytes(4, 'little')
                  + (0x11223344).to_bytes(4, 'little') + b'\x08' + (5).to_bytes(4, 'little', signed=True))
        self.assertEqual([{'offset': 16, 'key': 0x11223344, 'value': 5, 'name': None}],
                         arrays.blob_records(head + record))

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


if __name__ == '__main__':
    unittest.main()
