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
