"""Self-contained browser tests: no save files required.

Run: python3 -m unittest discover -s tests -v

Needs Playwright and its Chromium build (test-only dependency). The editor itself
has no dependencies and needs neither Python nor Node. All fixtures are generated
in memory, so this suite never reads or writes a real save.
"""
from pathlib import Path
import sys
import unittest

from playwright.sync_api import sync_playwright

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))
import des_save
import des_arrays


class SyntheticBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto((EDITOR / 'des_editor.html').as_uri())

    def tearDown(self):
        self.page.close()
        self.assertEqual([], self.errors)

    def load_bytes(self, raw: bytes):
        self.page.set_input_files('#file', {'name': 'USR-DATA',
                                            'mimeType': 'application/octet-stream',
                                            'buffer': raw})
        self.page.wait_for_function('!!current()')

    @staticmethod
    def build(records) -> bytes:
        sf = des_save.SaveFile()
        sf.records = records
        return sf.build()

    def test_page_loads_offline_with_no_dependency_on_game_files(self):
        self.assertTrue(self.page.evaluate('typeof SaveFile === "function"'))
        self.assertGreater(self.page.evaluate('ITEMDB.length'), 2000)
        self.assertEqual(0, self.page.locator('#alltable input').count())
        self.assertEqual('', self.page.input_value('#json'))

    def test_page_names_match_python(self):
        import des_fields
        expected = {**{k: m['name'] for k, m in des_fields.FIELDS.items()}, **des_fields.FAMILY_KEYS}
        got = dict(self.page.evaluate('[...NAME_BY_KEY.entries()]'))
        self.assertEqual(expected, got)
        world = dict(self.page.evaluate('[...WORLD_NAME_BY_KEY.entries()]'))
        self.assertEqual(des_fields.WORLD_KEYS, world)

    def test_signed_int32(self):
        self.assertEqual(-1, self.page.evaluate('new Field(1,T.I32,new Uint8Array([255,255,255,255])).value'))
        self.assertEqual(-2147483648, self.page.evaluate('new Field(1,T.I32,new Uint8Array([0,0,0,128])).value'))
        self.assertEqual(7, self.page.evaluate('(()=>{const f=new Field(1,T.I32,new Uint8Array(4));f.value=7;return f.value})()'))

    def test_invalid_scalar_edits_are_atomic(self):
        self.assertTrue(self.page.evaluate('''() => {
          for (const [type, values] of [[T.U8,[-1,256,1.5,NaN]], [T.U16,[-1,65536]],
                                       [T.I32,[-2147483649,2147483648,9999999999]], [T.F32,[Infinity,NaN,1e40]]]) {
            const f = new Field(1, type, new Uint8Array(SIZES[type]));
            for (const value of values) {
              const before = f.hex;
              try { f.value = value; return false; } catch (_) { if (f.hex !== before) return false; }
            }
          }
          return true;
        }'''))

    def test_strict_hex_and_fixed_width(self):
        self.assertTrue(self.page.evaluate(r'''() => {
          for (const hex of ['0g', 'abc', '12zz', '-1']) {
            try { hexToBytes(hex); return false; } catch (_) {}
          }
          const raw = new Field(1, T.RAW4, new Uint8Array(4));
          try { raw.value = 'aa'; return false; } catch (_) {}
          return raw.hex === '00000000' && hexToBytes('aa bb\ncc dd').length === 4;
        }'''))

    def test_malformed_records_and_varints_rejected(self):
        self.assertTrue(self.page.evaluate('''() => {
          for (const bytes of [[1,0,0,0,T.I32,1],[1,0,0,0,T.STR,4,65],
                               [1,0,0,0,T.BLOB,128],[1,0,0,0,T.CONT,1], [1,0,0,0]]) {
            const data = new Uint8Array(bytes);
            try { parseFields(data, 0, data.length, null); return false; } catch (_) {}
          }
          return true;
        }'''))

    def test_round_trips_generated_saves_byte_for_byte(self):
        fixtures = []
        for count in (0, 1, 31, 400):
            records = [des_save.Field(des_save.name_key('PLAYER_SOULS'), des_save.T_I32, (176).to_bytes(4, 'little')),
                       des_save.Field(des_save.name_key('PLAYER_NAME'), des_save.T_STR, b'Test'),
                       des_save.Field(9, des_save.T_CONTAINER, children=[
                           des_save.Field(10 + index, des_save.T_U16, index.to_bytes(2, 'little'))
                           for index in range(count)])]
            raw = self.build(records)
            fixtures.append(list(raw))
        self.assertTrue(self.page.evaluate('''fixtures => fixtures.every(raw => {
          const bytes = new Uint8Array(raw);
          return bytesEq(bytes, new SaveFile(bytes).build());
        })''', fixtures))

    def test_seeded_python_javascript_differential_edits(self):
        import random
        rng = random.Random(20261019)
        fixtures = []
        for index in range(100):
            children = [des_save.Field(100 + kind, kind, rng.randbytes(size))
                        for kind, size in des_save.SIZES.items()]
            children.extend([des_save.Field(500, des_save.T_STR, rng.randbytes(index)),
                             des_save.Field(501, des_save.T_BLOB, rng.randbytes(index * 13))])
            sf = des_save.SaveFile()
            sf.records = [
                des_save.Field(des_save.name_key('PLAYER_SOULS'), des_save.T_I32, (176).to_bytes(4, 'little')),
                des_save.Field(502, des_save.T_CONTAINER, children=children)]
            original = sf.build()
            sf.set('PLAYER_SOULS', 424242)
            fixtures.append({'original': list(original), 'edited': list(sf.build())})
        self.assertTrue(self.page.evaluate(r'''fixtures => fixtures.every(({original, edited}) => {
          const source = new Uint8Array(original), save = new SaveFile(source);
          if (!bytesEq(source, save.build())) return false;
          save.set('PLAYER_SOULS', 424242);
          return bytesEq(new Uint8Array(edited), save.build());
        })''', fixtures))

    def test_float_bit_patterns_survive_an_unchanged_json_round_trip(self):
        sf = des_save.SaveFile()
        sf.records = [des_save.Field(index, des_save.T_F32, bytes.fromhex(bits))
                      for index, bits in enumerate(['00000080', '0100c07f', '0000807f', '01000000'])]
        self.load_bytes(sf.build())
        self.assertTrue(self.page.evaluate('''() => {
          const before = current().save.build();
          document.querySelector('#json').value = jsonDump();
          applyJson();
          return bytesEq(before, current().save.build());
        }'''))

    def test_invalid_json_never_discards_existing_edits(self):
        sf = des_save.SaveFile()
        sf.records = [des_save.Field(des_save.name_key('PLAYER_SOULS'), des_save.T_I32, (176).to_bytes(4, 'little'))]
        self.load_bytes(sf.build())
        self.assertTrue(self.page.evaluate('''() => {
          current().save.set('PLAYER_SOULS', 24680);
          const doc = JSON.parse(jsonDump());
          doc.fields[0].key = '12345678';
          document.querySelector('#json').value = JSON.stringify(doc);
          applyJson();
          return current().save.get('PLAYER_SOULS') === 24680 && current().undo.length === 0;
        }'''))

    def test_structural_patch_is_validated_before_mutation(self):
        sf = des_save.SaveFile()
        sf.records = [des_save.Field(des_save.name_key('PLAYER_SOULS'), des_save.T_I32, (176).to_bytes(4, 'little')),
                      des_save.Field(7, des_save.T_BLOB, b'\x01\x02\x03\x04')]
        self.load_bytes(sf.build())
        self.assertTrue(self.page.evaluate('''() => {
          const before = current().save.build(), blob = () => current().save.flat.find(([f]) => f.type === T.BLOB)[0];
          const bad = JSON.parse(jsonDump());
          bad.fields[1].hex = 'zz';                 // not hex
          document.querySelector('#json').value = JSON.stringify(bad);
          applyJson();
          const rejected = bytesEq(before, current().save.build()) && blob().hex === '01020304';
          const wrongType = JSON.parse(jsonDump());
          wrongType.fields[1].type = '0x0e';
          document.querySelector('#json').value = JSON.stringify(wrongType);
          applyJson();
          const typeChecked = bytesEq(before, current().save.build());
          const good = JSON.parse(jsonDump());
          good.fields[1].hex = 'aabbccdd';
          document.querySelector('#json').value = JSON.stringify(good);
          applyJson();
          return rejected && typeChecked && blob().hex === 'aabbccdd';
        }'''))

    def test_inventory_rows_and_atomic_edits(self):
        k = des_save.name_key
        i32 = lambda v: (v & 0xFFFFFFFF).to_bytes(4, 'little')
        records = [des_save.Field(k('EQUIPMENT_INVENTORY_COUNT'), des_save.T_I32, i32(2))]
        for n, (bits, item, qty) in enumerate([(0, 150000, 1), (0x40000000, 1001, 32)]):
            p = f'EQUIPMENT_INVENTORY{n:02d}_'
            records += [des_save.Field(k(p + part), des_save.T_I32, i32(value)) for part, value in
                        (('INDEX', n), ('TYPE', bits), ('EQUIPID', item), ('VARIATIONID', n),
                         ('DISPLAYID', 0), ('DURABILITY_CURRENT', 200), ('DURABILITY_ACCUMULATEDHITS', 0))]
            records.append(des_save.Field(k(p + 'QUANTITY'), des_save.T_RAW4, qty.to_bytes(4, 'little')))
        self.load_bytes(self.build(records))
        self.assertEqual([['W', 150000, 'Buckler', 1], ['G', 1001, 'Half Moon Grass', 32]],
                         self.page.evaluate('inventoryRows(current().save).map(r => [r.cat, r.id, r.name, r.quantity])'))
        self.assertTrue(self.page.evaluate('''() => {
          const before = current().save.build();
          for (const bad of [0, 1000, 1.5]) { try { setInvQuantity(current().save, 1, bad); return false; } catch (_) {} }
          if (!bytesEq(before, current().save.build())) return false;
          editCandidate(s => setInvQuantity(s, 1, 50));
          if (inventoryRows(current().save)[1].quantity !== 50) return false;
          doUndo();
          return inventoryRows(current().save)[1].quantity === 32;
        }'''))

    def test_entries_past_index_99_count_and_export(self):
        k = des_save.name_key
        i32 = lambda v: (v & 0xFFFFFFFF).to_bytes(4, 'little')
        total = 150
        records = [des_save.Field(k('EQUIPMENT_INVENTORY_COUNT'), des_save.T_I32, i32(total))]
        for n in range(total):
            p = f'EQUIPMENT_INVENTORY{n:02d}_'
            records += [des_save.Field(k(p + part), des_save.T_I32, i32(value)) for part, value in
                        (('INDEX', n), ('TYPE', 0x40000000), ('EQUIPID', 1001), ('VARIATIONID', n),
                         ('DISPLAYID', 0), ('DURABILITY_CURRENT', 0), ('DURABILITY_ACCUMULATEDHITS', 0))]
            records.append(des_save.Field(k(p + 'QUANTITY'), des_save.T_RAW4, (n + 1).to_bytes(4, 'little')))
        self.load_bytes(self.build(records))
        self.assertTrue(self.page.evaluate('''() => {
          if (inventoryRows(current().save).length !== 150) return false;
          if (diagnostics().some(d => d[0] === "err")) return false;
          editCandidate(t => setInvQuantity(t, 120, 55));
          if (inventoryRows(current().save)[120].quantity !== 55) return false;
          return !!validatedExport(current());
        }'''))

    def test_dirty_state_is_cached_per_revision(self):
        sf = des_save.SaveFile()
        sf.records = [des_save.Field(1, des_save.T_U8, b'\x00')]
        self.load_bytes(sf.build())
        self.assertLessEqual(self.page.evaluate('''() => {
          const save = current().save, build = save.build.bind(save);
          let calls = 0;
          save.build = () => { calls++; return build(); };
          for (let i = 0; i < 50; i++) isDirty(current());
          return calls;
        }'''), 1)

    def test_rejecting_oversized_or_wrong_version_files(self):
        self.assertTrue(self.page.evaluate('''() => {
          try { new SaveFile(new Uint8Array(8)); return false; } catch (_) {}
          const empty = new Uint8Array(16), view = new DataView(empty.buffer);
          view.setUint32(0, 7, true); view.setUint32(12, 1, true);
          new SaveFile(empty);                        // a bare 16-byte header is valid
          view.setUint32(0, 6, true);
          try { new SaveFile(empty); return false; } catch (_) {}
          view.setUint32(0, 7, true); view.setUint32(8, 4, true);
          try { new SaveFile(empty); return false; } catch (_) {}   // size mismatch
          return true;
        }'''))

    def test_recovered_arrays_card_needs_no_sample_save(self):
        state, values = 0x7516F500, [100, 101, 102, 103]
        raw = self.build([des_save.Field(des_arrays.key_for_state(state, str(index)),
                                         des_save.T_I32,
                                         value.to_bytes(4, 'little', signed=True))
                          for index, value in enumerate(values)])
        self.load_bytes(raw)
        self.page.wait_for_selector('#arraycard')
        self.assertEqual([[state, values]],
                         self.page.evaluate('discoverArrays(current().save)'
                                            '.map(g => [g.state, g.members.map(f => f.value)])'))
        slot = self.page.evaluate(
            """() => [...document.querySelectorAll('#arraycard input[type=number]')]
                     .findIndex(el => el.value === '101')""")
        element = self.page.query_selector_all('#arraycard input[type=number]')[slot]
        element.fill('113')
        element.dispatch_event('change')
        self.page.wait_for_timeout(150)
        self.assertIn(113, self.page.evaluate(
            'discoverArrays(current().save).flatMap(g => g.members.map(f => f.value))'))
        self.page.evaluate('doUndo()')
        self.assertIn(101, self.page.evaluate(
            'discoverArrays(current().save).flatMap(g => g.members.map(f => f.value))'))


if __name__ == '__main__':
    unittest.main()
