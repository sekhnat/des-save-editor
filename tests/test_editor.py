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
sys.path.insert(0, str(EDITOR / 'src'))
import des_save
import des_arrays
import des_inventory
sys.path.insert(0, str(EDITOR / 'tests'))
import test_save
import test_flags
import des_flags


class SyntheticBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    # These suites drive the full editor; EasyModeBrowserTests covers Easy mode.
    mode = 'advanced'

    def setUp(self):
        self.page = self.browser.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        if self.mode:
            self.page.add_init_script(f"localStorage.setItem('des-editor-mode', '{self.mode}')")
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

    def test_respec_matches_python_and_needs_balanced_points(self):
        import des_character
        raw = test_save.character_save().build()
        expected = des_save.SaveFile(raw)
        des_character.redistribute(expected, {'VIT': 60, 'STR': 40})
        self.load_bytes(raw)
        vit = self.page.locator('[data-respec=VITALITY]')
        vit.fill('60')
        vit.dispatch_event('input')
        self.assertIn('too many', self.page.text_content('#respecstatus'))
        self.assertTrue(self.page.locator('#respecapply').is_disabled())
        strength = self.page.locator('[data-respec=STRENGTH]')
        strength.fill('40')
        strength.dispatch_event('input')
        self.assertFalse(self.page.locator('#respecapply').is_disabled())
        self.page.click('#respecapply')
        self.assertEqual(list(expected.build()), self.page.evaluate('Array.from(current().save.build())'))
        self.assertEqual(['VITALITY must be 8–99', 'points'], self.page.evaluate('''() => {
          const out = [];
          for (const values of [[7,50,50,50,50,50,50,93], [60,50,50,50,50,50,50,50]])
            try { redistribute(current().save, values); out.push("accepted"); } catch (e) { out.push(e.message); }
          return [out[0].replace(/^vitality/, "VITALITY").split(" (")[0], out[1].includes("points") ? "points" : out[1]];
        }'''))

    def test_weapon_variant_matches_python(self):
        raw = test_save.inventory_save([(0, 21605, 1, 900), (0x40000000, 1001, 3, 0)], [(20100, 1)]).build()
        expected = des_save.SaveFile(raw)
        des_inventory.set_weapon_variant(expected, 0, 21600)
        des_inventory.set_weapon_variant(expected, 0, 20111, 'storage')
        self.load_bytes(raw)
        self.assertEqual([n['name'] for n in des_inventory.upgrade_family('Weapon', 21605)],
                         self.page.evaluate('upgradeFamily(21605).map(id => ITEM_BY_CAT.get("W:"+id))'))
        result = self.page.evaluate('''() => {
          const s = current().save, before = s.build();
          for (const [index, id, where] of [[0, 20100, "inventory"], [1, 21600, "inventory"], [0, 1.5, "inventory"]]) {
            try { setWeaponVariant(s, index, id, where); return "accepted a bad edit"; } catch (_) {}
          }
          if (!bytesEq(before, s.build())) return "a refused edit changed bytes";
          editCandidate(t => { setWeaponVariant(t, 0, 21600, "inventory"); setWeaponVariant(t, 0, 20111, "storage"); });
          return Array.from(current().save.build());
        }''')
        self.assertEqual(list(expected.build()), result)

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



class AddItemBrowserTests(SyntheticBrowserTests):
    """The add-item dialog drives the same rules and bytes as des_inventory."""

    @staticmethod
    def fixture(**kwargs):
        entries = [{'cat': 'W', 'id': 150000, 'ref': 0, 'sort': 16101, 'durability': 200},
                   {'cat': 'G', 'id': 1001, 'quantity': 32, 'sort': 2}]
        storage = [{'cat': 'G', 'id': 2000, 'quantity': 25}]
        return test_save.creation_save(entries, storage=storage, rings=[105],
                                       slot_ref=0, equipitem=5, **kwargs)

    def add_via_dialog(self, search, cat, item_id, destination='inventory', quantity=None):
        self.page.click('#additem')
        self.page.select_option('#itemdestination', destination)
        if quantity is not None:
            self.page.fill('#itemquantity', str(quantity))
        self.page.fill('#itemsearch', search)
        self.page.wait_for_selector(f'#itemlist tr[data-cat="{cat}"][data-id="{item_id}"]')
        self.page.click(f'#itemlist tr[data-cat="{cat}"][data-id="{item_id}"]')
        self.page.click('#additemapply')

    def test_storage_additions_need_the_experimental_toggle(self):
        source = self.fixture().build()
        self.load_bytes(source)
        self.add_via_dialog('Mail Coif', 'A', 100400, destination='storage')
        self.assertIn('experimental', self.page.text_content('#message'))
        self.assertEqual(source, bytes(self.page.evaluate('current().save.build()')))
        self.page.evaluate('closeItemDialog()')
        self.page.check('#experimental')
        self.add_via_dialog('Mail Coif', 'A', 100400, destination='storage')
        expected = des_inventory.with_added_item(des_save.SaveFile(source), 'Armor', 100400,
                                                 destination='storage').build()
        self.assertEqual(expected, bytes(self.page.evaluate('current().save.build()')))

    def test_dialog_creates_the_same_bytes_as_python(self):
        source = self.fixture().build()
        self.load_bytes(source)
        self.page.check('#experimental')
        self.add_via_dialog('Dragon Bone', 'W', 20700)
        made = bytes(self.page.evaluate('current().save.build()'))
        expected = des_inventory.with_added_item(des_save.SaveFile(source), 'Weapon', 20700).build()
        self.assertEqual(expected, made)
        rows = self.page.evaluate('inventoryRows(current().save).map(r => [r.cat, r.id, r.quantity])')
        self.assertIn(['W', 20700, 1], rows)
        self.page.evaluate('doUndo()')
        self.assertEqual(source, bytes(self.page.evaluate('current().save.build()')))
        self.page.evaluate('doRedo()')
        self.assertEqual(expected, bytes(self.page.evaluate('current().save.build()')))

    def test_dialog_matches_python_when_the_count_sits_in_a_container(self):
        source = self.fixture(count_in_container=True).build()
        self.load_bytes(source)
        self.page.check('#experimental')
        self.add_via_dialog('Dragon Bone', 'W', 20700)
        made = bytes(self.page.evaluate('current().save.build()'))
        expected = des_inventory.with_added_item(des_save.SaveFile(source), 'Weapon', 20700).build()
        self.assertEqual(expected, made)
        self.assertEqual(3, self.page.evaluate('current().save.get("EQUIPMENT_INVENTORY_COUNT")'))

    def test_dialog_matches_python_when_references_have_gaps(self):
        entries = [{'cat': 'W', 'id': 150000, 'ref': 0, 'sort': 16101, 'durability': 200},
                   {'cat': 'G', 'id': 1001, 'ref': 2, 'quantity': 7, 'sort': 2},
                   {'cat': 'G', 'id': 1002, 'ref': 3, 'quantity': 9, 'sort': 3}]
        source = test_save.creation_save(entries, storage=[{'cat': 'G', 'id': 2000, 'quantity': 25,
                                                             'display': (5 << 16) | 1}],
                                         rings=[105], slot_ref=3, equipitem=0).build()
        self.load_bytes(source)
        self.page.check('#experimental')
        self.add_via_dialog('Dragon Bone', 'W', 20700)
        made = bytes(self.page.evaluate('current().save.build()'))
        expected = des_inventory.with_added_item(des_save.SaveFile(source), 'Weapon', 20700).build()
        self.assertEqual(expected, made)
        refs = self.page.evaluate('inventoryRows(current().save).map(r => [r.id, r.ref])')
        self.assertEqual([[150000, 0], [20700, 1], [1001, 2], [1002, 3]], refs)

    def test_catalog_row_adds_to_storage_like_python(self):
        source = self.fixture().build()
        self.load_bytes(source)
        self.page.check('#experimental')
        self.page.click('[data-tab=catalog]')
        self.page.fill('#catalogsearch', 'Dragon Bone Smasher')
        self.page.click('#catalogbody tr:has-text("Dragon Bone Smasher") button')
        self.page.select_option('#itemdestination', 'storage')
        self.page.click('#additemapply')
        made = bytes(self.page.evaluate('current().save.build()'))
        expected = des_inventory.with_added_item(des_save.SaveFile(source), 'Weapon', 20700,
                                                 destination='storage').build()
        self.assertEqual(expected, made)
        self.assertNotEqual(source, made)

    def test_dialog_guards_cancellation_and_keyboard_use(self):
        source = self.fixture().build()
        self.load_bytes(source)
        self.assertTrue(self.page.evaluate('!!$("#additem") && !$("#additem").disabled'),
                        'inventory additions need no experimental toggle')
        self.assertEqual(source, bytes(self.page.evaluate('current().save.build()')))
        self.page.evaluate('openItemDialog()')
        self.assertEqual('itemsearch', self.page.evaluate('document.activeElement.id'))
        self.page.keyboard.press('Tab')
        self.assertTrue(self.page.evaluate('document.activeElement.closest("#itemdialog") !== null'))
        self.page.keyboard.press('Escape')
        self.assertTrue(self.page.evaluate('$("#itemdialog").classList.contains("hidden")'))
        # a draft blocks opening
        self.page.evaluate('$("#json").value = "{}"; $("#json").dispatchEvent(new Event("input"))')
        self.page.evaluate('openItemDialog()')
        self.assertIn('draft', self.page.text_content('#message'))
        self.assertTrue(self.page.evaluate('$("#itemdialog").classList.contains("hidden")'))
        # stale dialog after an unrelated edit
        self.page.evaluate('$("#refreshjson").click()')
        self.page.evaluate('openItemDialog()')
        self.page.fill('#itemsearch', 'Dragon Bone')
        self.page.wait_for_selector('#itemlist tr[data-cat="W"][data-id="20700"]')
        self.page.click('#itemlist tr[data-cat="W"][data-id="20700"]')
        self.page.evaluate('editCandidate(s => setInvQuantity(s, 0, 5))')
        with_edits = bytes(self.page.evaluate('current().save.build()'))
        self.page.click('#additemapply')
        self.assertIn('reopen', self.page.text_content('#message'))
        self.assertEqual(with_edits, bytes(self.page.evaluate('current().save.build()')))
        # cancel records no history and changes nothing
        self.page.evaluate('doUndo()')
        clean = bytes(self.page.evaluate('current().save.build()'))
        self.page.evaluate('openItemDialog()')
        self.page.keyboard.press('Escape')
        self.assertTrue(self.page.evaluate('$("#itemdialog").classList.contains("hidden")'))
        self.assertEqual(clean, bytes(self.page.evaluate('current().save.build()')))
        self.assertEqual(0, self.page.evaluate('current().undo.length'))

    def test_creation_eligibility_matches_python_catalog(self):
        import json
        import des_items
        doc = json.loads((EDITOR / 'itemdb.json').read_text(encoding='utf-8'))
        letters = {'Weapon': 'W', 'Armor': 'A', 'Ring': 'R', 'Goods': 'G',
                   'Spell': 'S', 'Skill': 'K'}
        expected = {(letters[e['category']], e['id']): des_items.creation_problem(e) is None
                    for e in doc['items']}
        got = self.page.evaluate('[...ITEMDB].map(row => [row[2], row[0], creationProblem(row[2], row[0]) === null])')
        self.assertEqual(expected, {(letter, item_id): ok for letter, item_id, ok in got})

    def test_changes_after_creation_are_real_additions(self):
        source = self.fixture().build()
        self.load_bytes(source)
        self.page.check('#experimental')
        self.add_via_dialog('Dragon Bone', 'W', 20700)
        added, changed = self.page.evaluate("""() => {
          const rows = collectChanges(current());
          return [rows.filter(c => !c.before).map(c => (c.after.name || "0x" + c.after.key.toString(16))),
                  rows.filter(c => c.before && c.after).map(c => c.before.name || "0x" + c.before.key.toString(16))];
        }""")
        self.assertEqual({f"EQUIPMENT_INVENTORY02_{part}" for part in des_inventory.INVENTORY_PARTS},
                         set(added))
        self.assertEqual(['EQUIPMENT_INVENTORY_COUNT'], changed)
        self.page.click('[data-tab=changes]')
        self.assertIn('9 changed', self.page.evaluate('$("#changescount").textContent'))
        self.page.evaluate('downloadPatch()')
        self.assertIn('Structural changes require a full USR-DATA export',
                      self.page.text_content('#message'))
        out = self.page.evaluate('validatedExport(current())')
        expected = des_inventory.with_added_item(des_save.SaveFile(source), 'Weapon', 20700).build()
        self.assertEqual(expected, bytes(out))

    def test_scalar_changes_after_insertion_pair_by_identity(self):
        source = self.fixture().build()
        self.load_bytes(source)
        self.page.check('#experimental')
        self.add_via_dialog('Dragon Bone', 'W', 20700)
        self.page.evaluate('setInvQuantity(current().save, 1, 50)')
        added, changed = self.page.evaluate("""() => {
          const rows = collectChanges(current());
          return [rows.filter(c => !c.before).length,
                  rows.filter(c => c.before && c.after).map(c => c.before.name || "0x" + c.before.key.toString(16))];
        }""")
        self.assertEqual(8, added)
        self.assertEqual({'EQUIPMENT_INVENTORY01_QUANTITY', 'EQUIPMENT_INVENTORY_COUNT'},
                         set(changed))

    def test_options_profiles_cannot_add_items(self):
        sf = des_save.SaveFile()
        sf.records = [des_save.Field(des_save.name_key('BRIGHTNESS'), des_save.T_I32,
                                     (40).to_bytes(4, 'little'))]
        self.load_bytes(sf.build())
        self.assertTrue(self.page.evaluate('document.querySelector("#additem") === null'))
        self.assertTrue(self.page.evaluate('''() => {
          try { openItemDialog(); return false; }
          catch (error) { return String(error.message).includes("Options"); }
        }'''))


class TendencyBrowserTests(unittest.TestCase):
    """The Tendency tab, with the fixtures of SyntheticBrowserTests (not a subclass,
    so the parent's tests do not run twice)."""
    mode = 'advanced'
    setUpClass = SyntheticBrowserTests.__dict__['setUpClass']
    tearDownClass = SyntheticBrowserTests.__dict__['tearDownClass']
    setUp = SyntheticBrowserTests.setUp
    tearDown = SyntheticBrowserTests.tearDown
    load_bytes = SyntheticBrowserTests.load_bytes

    # ---- tendency ---------------------------------------------------------
    def open_tendency(self, **kw):
        self.load_bytes(test_save.tendency_save(**kw).build())
        self.page.click('button[data-tab="tendency"]')

    def test_tendency_tab_lists_worlds_and_events(self):
        import des_tendency
        self.open_tendency(pc_wb=200, worlds={1: -200, 4: 200})
        names = self.page.locator('#tab-tendency .tdname:visible').all_inner_texts()
        self.assertEqual(['Character tendency'] + [w['name'] for w in des_tendency.WORLDS], names)
        self.assertEqual(len(des_tendency.EVENTS), self.page.locator('#tab-tendency .tdevent').count())
        active = {int(j) for j in self.page.eval_on_selector_all(
            '#tab-tendency .tdevent.on', 'rows => rows.map(r => r.dataset.judge)')}
        expected = set(des_tendency.active_events(des_tendency.read(test_save.tendency_save(
            pc_wb=200, worlds={1: -200, 4: 200}))))
        self.assertEqual(expected, active)
        self.assertEqual('Pure Black', self.page.inner_text('#td-boletaria >> xpath=ancestor::div[@class="tdctl"][1] >> .tdband'))

    def test_tendency_slider_commits_one_undo_step(self):
        self.open_tendency(worlds={1: 120}, copies={1: 180})
        self.page.fill('#td-boletaria-num', '-150')
        self.page.locator('#td-boletaria-num').dispatch_event('change')
        self.assertEqual([-150, -150], self.page.evaluate(
            '["TENDENCY_WORLD01_LEFTRIGHT","TENDENCY_WORLD01_BLACKWHITE"].map(n => current().save.get(n))'))
        self.assertTrue(self.page.locator('.tdevent[data-judge="20200"].on').count())
        self.page.click('#undo')
        self.assertEqual([120, 180], self.page.evaluate(
            '["TENDENCY_WORLD01_LEFTRIGHT","TENDENCY_WORLD01_BLACKWHITE"].map(n => current().save.get(n))'))

    def test_tendency_trigger_and_conflict(self):
        self.open_tendency(worlds={1: 120})
        self.page.click('.tdevent[data-judge="20300"] button')
        self.assertEqual(-181, self.page.evaluate('current().save.get("TENDENCY_WORLD01_LEFTRIGHT")'))
        self.assertIn('Also turns on', self.page.inner_text('#message'))
        self.assertTrue(self.page.locator('.tdevent[data-judge="20300"] button').is_disabled())
        self.page.check('.tdevent[data-judge="20300"] input')
        self.page.check('.tdevent[data-judge="20500"] input')
        self.page.click('#tdtriggerselected')
        self.assertIn('no value satisfies', self.page.inner_text('#message'))
        self.assertEqual(-181, self.page.evaluate('current().save.get("TENDENCY_WORLD01_LEFTRIGHT")'))
        self.page.click('button[data-allworlds="200"]')
        self.assertEqual([200] * 5, self.page.evaluate(
            '[1,2,3,4,5].map(i => current().save.get(`TENDENCY_WORLD0${i}_LEFTRIGHT`))'))

    def test_tendency_logic_matches_python(self):
        import random
        import des_tendency
        rng = random.Random(7)
        choices = [-200, -181, -180, -179.5, -150, -100, -99, -49, 0, 49, 50, 100, 150, 179, 180, 200]
        judges = [e['judge'] for e in des_tendency.EVENTS]
        cases = []
        for _ in range(60):
            st = {'pc_wb': rng.choice(choices), 'pc_lr': rng.choice(choices),
                  'worlds': {str(s): {'value': rng.choice(choices), 'copy': 0} for s in range(7)}}
            picks = rng.sample(judges, rng.randint(1, 3))
            py_state = {**st, 'worlds': {int(k): v for k, v in st['worlds'].items()}}
            plan = des_tendency.trigger_targets(py_state, picks)
            cases.append({'st': st, 'picks': picks, 'active': des_tendency.active_events(py_state),
                          'targets': plan['targets'], 'on': plan['turns_on'], 'off': plan['turns_off'],
                          'conflict': bool(plan['conflicts']),
                          'bands': [des_tendency.band(v) for v in choices]})
        mismatches = self.page.evaluate("""([cases, choices]) => cases.filter(c => {
            const plan = tdTriggerTargets(c.st, c.picks);
            const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
            return !same(tdActive(c.st), c.active) || !same(plan.targets, c.targets) || !same(plan.turnsOn, c.on)
              || !same(plan.turnsOff, c.off) || (plan.conflicts.length > 0) !== c.conflict
              || !same(choices.map(tdBand), c.bands);
        }).length""", [cases, choices])
        self.assertEqual(0, mismatches)


class EventsBrowserTests(unittest.TestCase):
    """The Events tab: bosses, NPC states and per-area flags, byte-identical to des_flags."""
    mode = 'advanced'
    setUpClass = SyntheticBrowserTests.__dict__['setUpClass']
    tearDownClass = SyntheticBrowserTests.__dict__['tearDownClass']
    setUp = SyntheticBrowserTests.setUp
    tearDown = SyntheticBrowserTests.tearDown
    load_bytes = SyntheticBrowserTests.load_bytes

    def setUp(self):
        self.db = des_flags.load_db()
        if self.db is None:
            self.skipTest('flagdb.json not found (run tools/build_flagdb.py)')
        SyntheticBrowserTests.setUp(self)

    @staticmethod
    def fixture():
        return test_flags.flags_save({4096: 1, 4103: 1, 16440: 1, 16540: 1}, area=1,
                                     local={(1, 200): 1, (5, 1050): 1})

    def open_events(self, sf=None, experimental=True):
        self.load_bytes((sf or self.fixture()).build())
        self.page.click('button[data-tab="events"]')
        if experimental:
            self.page.check('#eventsexperimental')

    def page_bytes(self) -> bytes:
        return bytes(self.page.evaluate('Array.from(current().save.build())'))

    def test_edits_wait_for_the_experimental_toggle(self):
        self.open_events(experimental=False)
        # respawn, defeat and take were seen working in game, so they need no toggle; the rest do
        self.assertTrue(self.page.locator('.evboss[data-boss="4096"] button[data-action="respawn"]').is_enabled())
        self.assertTrue(self.page.locator('.evboss[data-boss="4224"] button[data-action="defeat"]').is_enabled())
        self.assertTrue(self.page.locator('.evboss[data-boss="4096"] button[data-action="defeat"]').is_disabled())   # already dead
        self.assertTrue(self.page.locator('.evnpc[data-npc="baldwin_flag_list"] select').is_disabled())
        self.assertTrue(self.page.locator('#evlocal input[data-flag="200"]').is_disabled())
        self.page.check('#eventsexperimental')
        self.assertTrue(self.page.locator('.evnpc[data-npc="baldwin_flag_list"] select').is_enabled())

    def test_reads_match_python(self):
        self.open_events(experimental=False)
        dead = self.page.locator('.evboss.dead').evaluate_all('rows => rows.map(r => Number(r.dataset.boss))')
        self.assertEqual([4096], dead)
        self.assertIn('m02', self.page.inner_text('#evsummary'))
        self.assertEqual(0, self.page.locator('#evmirrorwarn').count())
        checked = self.page.locator('#evlocal .evlist input:checked').evaluate_all('b => b.map(x => Number(x.dataset.flag))')
        self.assertEqual([200], checked)
        self.page.select_option('#evarea', '5')
        self.page.check('#evundocumented')                             # only set flags
        checked = self.page.locator('#evlocal .evlist input:checked').evaluate_all('b => b.map(x => Number(x.dataset.flag))')
        self.assertEqual([1050], checked)
        self.assertEqual(1, self.page.locator('#evlocal .evflag').count())
        self.assertIn('boss room', self.page.locator('#evlocal .evflag.on').inner_text().lower())

    def test_respawn_matches_python_and_is_one_undo_step(self):
        self.open_events()
        self.page.click('.evboss[data-boss="4096"] button[data-action="respawn"]')
        expected = self.fixture()
        des_flags.respawn_boss(expected, self.db, 'phalanx')
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(1, self.page.evaluate('current().undo.length'))
        self.page.click('#undo')
        self.assertEqual(self.fixture().build(), self.page_bytes())

    def test_npc_state_matches_python(self):
        self.open_events()
        self.page.select_option('.evnpc[data-npc="baldwin_flag_list"] select', '16441')
        expected = self.fixture()
        des_flags.set_npc_state(expected, self.db, 'baldwin', 'hostile')
        self.assertEqual(expected.build(), self.page_bytes())

    def test_local_edits_match_python(self):
        self.open_events()
        self.page.uncheck('#evlocal input[data-flag="200"]')          # current area: both copies
        self.page.select_option('#evarea', '5')
        self.page.fill('#evlocalfilter', '1111')
        self.page.check('#evlocal input[data-flag="1111"]')           # another area: slot only
        expected = self.fixture()
        des_flags.set_local(expected, 1, 200, False)
        des_flags.set_local(expected, 5, 1111, True)
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(2, self.page.evaluate('current().undo.length'))

    def test_raw_and_global_edits_match_python(self):
        self.open_events()
        self.page.select_option('#evrawarea', '0')
        self.page.fill('#evrawid', '30')
        self.page.click('#evrawapply')
        self.page.fill('#evglobalfilter', '8084')
        self.page.check('#evglobal input[data-flag="8084"]')
        expected = self.fixture()
        des_flags.set_local(expected, 0, 30, True)
        des_flags.set_flag(expected, 8084, True)
        self.assertEqual(expected.build(), self.page_bytes())
        self.page.select_option('#evrawarea', 'g')
        self.page.fill('#evrawid', '200')                               # local id, no area
        self.page.click('#evrawapply')
        self.assertIn('area-local', self.page.inner_text('#message'))
        self.assertEqual(expected.build(), self.page_bytes())

    def test_high_range_and_recipes_match_python(self):
        backup = self.db.backup_offset
        sf = test_flags.flags_save({6400: 1, 6403: 1, 6410: 1, 16441: 1, 16440 + backup: 1}, area=0,
                                   local={(0, 390): 1, (0, 30): 1, (5, 1050): 1, (5, 11266): 1, (1, 10240): 1})
        fresh = lambda: test_flags.flags_save({6400: 1, 6403: 1, 6410: 1, 16441: 1, 16440 + backup: 1}, area=0,
                                              local={(0, 390): 1, (0, 30): 1, (5, 1050): 1, (5, 11266): 1, (1, 10240): 1})
        self.open_events(sf)
        self.page.click('.evboss[data-boss="6400"] button[data-action="respawn-full"]')
        self.page.click('.evnpc[data-npc="baldwin_flag_list"] button[data-action="forgive"]')
        self.page.select_option('#evpickarea', '5')
        self.page.click('#evrearm')
        self.page.select_option('#evarea', '1')
        self.page.fill('#evlocalfilter', '10240')
        self.page.uncheck('#evlocal input[data-flag="10240"]')        # high range, not current
        self.page.fill('#evlocalfilter', '')
        self.page.select_option('#evarea', '0')
        self.page.click('#evresetmap')
        expected = fresh()
        des_flags.respawn_boss(expected, self.db, 'dragon god', full=True)
        des_flags.forgive_npc(expected, self.db, 'baldwin')
        des_flags.rearm_pickups(expected, self.db, 5)
        des_flags.set_local(expected, 1, 10240, False)
        des_flags.reset_map(expected, 0)
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(5, self.page.evaluate('current().undo.length'))
        self.assertTrue(des_flags.mirror_ok(des_save.SaveFile(self.page_bytes())))

    def test_tendency_tab_lists_gated_events(self):
        self.open_events(experimental=False)
        self.page.click('button[data-tab="tendency"]')
        rows = self.page.locator('#tdgated tbody tr')
        self.assertGreater(rows.count(), 20)
        happened = self.page.locator('#tdgated tr[data-flag="200"]').first.inner_text()
        self.assertIn('Yes', happened)                                  # m02:200 set in the fixture

    def test_options_profile_has_no_event_flags(self):
        sf = des_save.SaveFile()
        sf.records = [des_save.Field(des_save.name_key('PLAYER_NAME'), des_save.T_STR, b'T')]
        self.open_events(des_save.SaveFile(sf.build()), experimental=False)
        self.assertIn('no event flags', self.page.inner_text('#tab-events'))

    def test_easy_mode_shows_bosses_npcs_and_pickups(self):
        self.page.evaluate('setMode("easy")')
        self.open_events(self.pickup_save(), experimental=False)
        cards = self.page.locator('#tab-events section.card').evaluate_all('c => c.map(x => x.id).filter(Boolean)')
        self.assertEqual(['evbosses', 'evnpcs', 'evpickups'], cards)
        self.assertEqual(0, self.page.locator('button[data-action="respawn-full"]').count())
        self.assertEqual(16, self.page.locator('.evboss').count())
        again = self.page.locator('.evpick[data-flag="10242"] button[data-action="rearm"]')
        self.assertTrue(again.is_disabled())                            # experimental
        self.page.check('#eventsexperimental')
        self.assertTrue(again.is_enabled())

    def test_defeat_matches_python_and_hands_over_the_soul(self):
        fresh = lambda: test_flags.defeat_save({4096: 1}, area=1, local={(1, 200): 1})
        self.open_events(fresh())
        knight = self.page.locator('.evboss[data-boss="4224"]')
        self.assertIn('Iron Demon Soul not taken', knight.inner_text())
        self.assertEqual(1, knight.locator('.evsoul .glyph').count())
        self.assertTrue(self.page.locator('.evboss[data-boss="4096"] button[data-action="defeat"]').is_disabled())
        knight.locator('button[data-action="defeat"]').click()
        self.assertIn('Iron Demon Soul', self.page.inner_text('#message'))
        self.page.click('.evboss[data-boss="5888"] button[data-action="defeat"]')   # soul + ring + Nexial Agent
        expected, _ = des_flags.defeat_boss(fresh(), self.db, 'tower knight')
        expected, _ = des_flags.defeat_boss(expected, self.db, 'maiden astrea')
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(2, self.page.evaluate('current().undo.length'))
        self.assertIn('Iron Demon Soul taken', self.page.locator('.evboss[data-boss="4224"]').inner_text())

    def test_easy_mode_can_mark_a_boss_defeated(self):
        self.page.evaluate('setMode("easy")')
        self.open_events(test_flags.defeat_save({}, area=1))
        self.page.click('.evboss[data-boss="4096"] button[data-action="defeat"]')
        expected, _ = des_flags.defeat_boss(test_flags.defeat_save({}, area=1), self.db, 'phalanx')
        self.assertEqual(expected.build(), self.page_bytes())

    @staticmethod
    def pickup_save():
        return test_flags.flags_save({4096: 1}, area=1, local={(1, 10240): 1, (1, 10242): 1, (5, 1050): 1})

    def test_pickups_show_items_and_rearm_one(self):
        self.open_events(self.pickup_save())
        rows = self.page.locator('#evpickups .evpick')
        self.assertEqual(len(self.db.pickups[1]), rows.count())         # current map: Boletaria
        grass = self.page.locator('.evpick[data-flag="10242"]')
        self.assertIn('Late Moon Grass ×2', grass.inner_text())
        self.assertIn('Taken', grass.inner_text())
        self.assertEqual(1, grass.locator('.glyph').count())
        self.assertEqual(0, self.page.locator('.evpick[data-flag="10241"] button[data-action="rearm"]').count())   # not taken
        grass.locator('button[data-action="rearm"]').click()
        expected = self.pickup_save()
        des_flags.set_local(expected, 1, 10242, False)
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(1, self.page.evaluate('current().undo.length'))
        self.page.select_option('#evpickarea', 'all')                 # search every map
        self.page.fill('#evpickfilter', "master's ring")
        ring = self.page.locator('.evpick[data-area="5"][data-flag="11266"]')
        self.assertEqual(1, ring.count())
        self.assertIn('Not taken', ring.inner_text())
        self.page.check('#evpicktaken')
        self.assertEqual(0, self.page.locator('#evpickups .evpick').count())

    def test_take_pickups_matches_python(self):
        fresh = lambda: test_flags.defeat_save({}, area=1, local={(1, 10240): 1})
        self.open_events(fresh(), experimental=False)
        robes = self.page.locator('.evpick[data-flag="10241"] button[data-action="take"]')
        self.assertTrue(robes.is_enabled())                             # seen working in game
        self.assertEqual(0, self.page.locator('.evpick[data-flag="10240"] button[data-action="take"]').count())
        robes.click()
        self.assertIn('Old Ragged Robes', self.page.inner_text('#message'))
        row = self.page.locator('.evpick[data-flag="10241"]')
        self.assertIn('Taken', row.inner_text())
        self.assertEqual(1, row.locator('button[data-action="rearm"]').count())
        expected, _ = des_flags.take_pickups(fresh(), self.db, 1, [10241])
        self.assertEqual(expected.build(), self.page_bytes())
        self.page.click('#evtakeall')
        expected, _ = des_flags.take_pickups(expected, self.db, 1)
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(2, self.page.evaluate('current().undo.length'))
        self.assertTrue(self.page.locator('#evtakeall').is_disabled())  # nothing left

    def test_map_flag_search_covers_all_maps(self):
        self.open_events()                                              # on Boletaria (m02)
        self.page.fill('#evlocalfilter', "master's ring")             # a Stonefang (m06) pickup
        self.assertEqual(0, self.page.locator('#evlocal .evflag').count())
        self.page.click('#evelsewhere button')
        self.assertEqual('all', self.page.eval_on_selector('#evarea', 's => s.value'))
        row = self.page.locator('#evlocal .evflag[data-area="5"]:has(input[data-flag="11266"])')
        self.assertIn('Stonefang', row.inner_text())
        row.locator('input').check()
        expected = self.fixture()
        des_flags.set_local(expected, 5, 11266, True)
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(0, self.page.locator('#evresetmap').count())  # per-map tools hidden

    def test_tendency_rearm_matches_python(self):
        self.open_events(experimental=False)
        self.page.click('button[data-tab="tendency"]')
        again = self.page.locator('#tdgated tr[data-flag="200"] button[data-action="rearm"]').first
        self.assertTrue(again.is_disabled())
        self.page.check('#tdexperimental')
        again = self.page.locator('#tdgated tr[data-flag="200"] button[data-action="rearm"]').first
        again.click()
        expected = self.fixture()
        des_flags.set_local(expected, 1, 200, False)
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertIn('No', self.page.locator('#tdgated tr[data-flag="200"]').first.inner_text())

    def test_fix_copy_matches_sync_mirror(self):
        broken = lambda: self.fixture()
        sf = broken()
        des_flags.set_local(sf, 1, 201, True, mirror=False)
        self.open_events(des_save.SaveFile(sf.build()), experimental=False)
        self.assertEqual(1, self.page.locator('#evmirrorwarn').count())
        self.page.click('#evsyncmirror')                               # confirmed: no toggle needed
        expected = des_save.SaveFile(sf.build())
        des_flags.sync_mirror(expected)
        self.assertEqual(expected.build(), self.page_bytes())
        self.assertEqual(0, self.page.locator('#evmirrorwarn').count())

    def test_buttons_say_whether_seen_in_game(self):
        self.open_events(self.pickup_save(), experimental=False)
        status = lambda sel: self.page.locator(sel).first.get_attribute('data-status')
        self.assertEqual('confirmed', status('button[data-action="respawn"]'))
        self.assertEqual('confirmed', status('button[data-action="respawn-full"]'))
        self.assertEqual('confirmed', status('button[data-action="defeat"]'))
        for action in ('rearm', 'reset-map'):
            self.assertEqual('experimental', status(f'button[data-action="{action}"]'), action)
        self.assertEqual('experimental', status('.evnpc select'))
        self.assertIn('✓', self.page.locator('button[data-action="respawn"]').first.inner_text())

    def test_phone_width_has_no_sideways_scroll(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        overflow = 'document.documentElement.scrollWidth - window.innerWidth'
        self.open_events(self.pickup_save())
        self.page.select_option('#evarea', 'all')
        self.assertLessEqual(self.page.evaluate(overflow), 0, 'Events, advanced')
        self.page.click('button[data-tab="tendency"]')
        self.assertLessEqual(self.page.evaluate(overflow), 0, 'Tendency, advanced')
        self.page.evaluate('setMode("easy")')
        self.page.click('button[data-tab="events"]')
        self.assertLessEqual(self.page.evaluate(overflow), 0, 'Events, easy')


class EasyModeBrowserTests(unittest.TestCase):
    """Easy mode: Character, Items and Tendency only, on the same edit rules."""
    mode = None                     # fresh browser storage: the page picks Easy itself
    setUpClass = SyntheticBrowserTests.__dict__['setUpClass']
    tearDownClass = SyntheticBrowserTests.__dict__['tearDownClass']
    setUp = SyntheticBrowserTests.setUp
    tearDown = SyntheticBrowserTests.tearDown
    load_bytes = SyntheticBrowserTests.load_bytes

    @staticmethod
    def player(archetype=9, values=(50,) * 8) -> bytes:
        sf = test_save.character_save(archetype, values)
        sf.records.insert(0, des_save.Field(des_save.name_key('PLAYER_NAME'), des_save.T_STR, b'Hero'))
        return des_save.SaveFile(sf.build()).build()

    def visible_tabs(self):
        return self.page.locator('.tabs button:visible').all_inner_texts()

    def test_easy_is_the_default_and_the_choice_is_remembered(self):
        self.load_bytes(self.player())
        self.assertEqual('easy', self.page.evaluate('state.mode'))
        self.assertEqual(['Character', 'Tendency', 'Events'], self.visible_tabs())
        self.assertTrue(self.page.locator('#tab-character #charcard').is_visible())
        self.assertFalse(self.page.locator('#quick').is_visible())
        self.page.click('#modeswitch [data-mode="advanced"]')
        self.assertEqual(['Editor', 'Tendency', 'Events', 'All fields', 'Tree', 'World state', 'Field reference',
                          'Item catalog', 'Changes', 'JSON'], self.visible_tabs())
        self.assertEqual('editor', self.page.evaluate('state.tab'))
        self.page.reload()
        self.load_bytes(self.player())
        self.assertEqual('advanced', self.page.evaluate('state.mode'))
        self.assertEqual(1, self.page.locator('[id="diagcard"]').count())

    def test_easy_attributes_level_change_and_redistribution_match_python(self):
        import des_character
        raw = self.player()
        self.load_bytes(raw)
        vit = self.page.locator('[data-attr=VITALITY]')
        vit.fill('60')
        vit.dispatch_event('input')
        self.assertIn('320 → 330', self.page.text_content('#easyattrstatus'))
        self.assertEqual('Apply level change', self.page.text_content('#easyattrapply'))
        self.page.click('#easyattrapply')
        expected = des_save.SaveFile(raw)
        des_character.set_attributes(expected, {'VIT': 60})
        self.assertEqual(list(expected.build()), self.page.evaluate('Array.from(current().save.build())'))
        for name, value in (('VITALITY', '55'), ('STRENGTH', '55')):
            box = self.page.locator(f'[data-attr={name}]')
            box.fill(value)
            box.dispatch_event('input')
        self.assertIn('stays 330', self.page.text_content('#easyattrstatus'))
        self.page.click('#easyattrapply')
        des_character.redistribute(expected, {'VIT': 55, 'STR': 55})
        self.assertEqual(list(expected.build()), self.page.evaluate('Array.from(current().save.build())'))
        luck = self.page.locator('[data-attr=LUCK]')
        luck.fill('3')
        luck.dispatch_event('input')
        self.assertTrue(self.page.locator('#easyattrapply').is_disabled())

    def test_easy_class_select_is_undoable(self):
        self.load_bytes(self.player())
        self.page.select_option('#easyclass', '0')
        self.assertEqual(0, self.page.evaluate('current().save.get("PLAYER_ARCHETYPE")'))
        self.page.click('#undo')
        self.assertEqual(9, self.page.evaluate('current().save.get("PLAYER_ARCHETYPE")'))

    def test_easy_tendency_shows_sliders_without_events(self):
        import des_tendency
        self.load_bytes(test_save.tendency_save(worlds={1: 120}).build())
        self.page.click('button[data-tab="tendency"]')
        names = self.page.locator('#tab-tendency .tdname:visible').all_inner_texts()
        self.assertEqual(['Character tendency'] + [w['name'] for w in des_tendency.WORLDS], names)
        self.assertEqual(0, self.page.locator('#tab-tendency .tdevent').count())
        self.assertEqual(0, self.page.locator('#tdselection').count())
        self.page.fill('#td-boletaria-num', '-150')
        self.page.locator('#td-boletaria-num').dispatch_event('change')
        self.assertEqual([-150, -150], self.page.evaluate(
            '["TENDENCY_WORLD01_LEFTRIGHT","TENDENCY_WORLD01_BLACKWHITE"].map(n => current().save.get(n))'))

    def test_easy_tables_and_storage_addition_match_python(self):
        source = AddItemBrowserTests.fixture().build()
        self.load_bytes(source)
        equipped = self.page.locator('#easyequipped .easyrow')
        self.assertEqual(1, equipped.count())
        self.assertEqual('L1', equipped.locator('.slot').inner_text())
        self.assertIn('Buckler', equipped.inner_text())
        self.assertEqual(2, self.page.locator('#easyinv .easyrow .glyph').count())
        self.assertEqual(1, self.page.locator('#easybox .easyrow .glyph').count())
        self.page.click('#easyaddbox')
        self.assertEqual('storage', self.page.input_value('#itemdestination'))
        self.assertTrue(self.page.locator('#itemstoragewarn').is_visible())
        self.page.fill('#itemsearch', 'Mail Coif')
        self.page.click('#itemlist tr[data-cat="A"][data-id="100400"]')
        self.page.click('#additemapply')
        expected = des_inventory.with_added_item(des_save.SaveFile(source), 'Armor', 100400,
                                                 destination='storage').build()
        self.assertEqual(expected, bytes(self.page.evaluate('current().save.build()')))
        self.assertTrue(self.page.evaluate('current().experimental'))
        self.assertIn('Mail Coif', self.page.inner_text('#easybox'))
        self.assertEqual('character', self.page.evaluate('state.tab'))

    def test_easy_inventory_filter_and_add_button(self):
        self.load_bytes(AddItemBrowserTests.fixture().build())
        self.page.fill('#easyinv input[type=text]', 'moon')
        self.assertEqual(1, self.page.locator('#easyinv .easyrow').count())
        self.assertIn('1 of 2', self.page.inner_text('#easyinv .gearhead'))
        self.assertEqual(1, self.page.locator('#easybox .easyrow').count())
        self.page.locator('#easyinv input[type=number]').fill('40')
        self.page.locator('#easyinv input[type=number]').dispatch_event('change')
        self.assertEqual(40, self.page.evaluate('inventoryRows(current().save)[1].quantity'))
        self.assertEqual('moon', self.page.input_value('#easyinv input[type=text]'))
        self.page.click('#easyaddinv')
        self.assertEqual('inventory', self.page.input_value('#itemdestination'))
        self.assertFalse(self.page.locator('#itemstoragewarn').is_visible())

    def test_game_icons_replace_glyphs_where_the_pack_has_one(self):
        self.load_bytes(AddItemBrowserTests.fixture().build())
        # The Buckler in L1 shows its game icon in the table and on the paper doll.
        self.assertEqual(1, self.page.locator('#easyequipped .easyrow img.glyph.icon').count())
        doll = self.page.locator('#charcard .figure.doll')
        self.assertEqual(1, doll.count())
        self.assertEqual(1, doll.locator('[data-part="l1"] img.glyph.icon').count())
        self.assertEqual(0, doll.locator('[data-part="head"] img').count())
        self.assertEqual(1, doll.locator('[data-part="head"] svg.glyph.empty').count())
        self.assertTrue(self.page.locator('#iconcredit').is_visible())
        kinds = self.page.evaluate('''[itemGlyph("W", 10000).tagName, itemGlyph("W", 1234567).tagName,
            itemGlyph("A", 100700, false).src === itemGlyph("A", 100700, true).src,
            iconFor("W", 10003) === iconFor("W", 10000), iconFor("G", 9926) === iconFor("G", 9922)]''')
        self.assertEqual(['IMG', 'svg', False, True, False], kinds)

    def test_paper_doll_uses_the_saves_gender(self):
        def save(is_male):
            sf = des_save.SaveFile(AddItemBrowserTests.fixture().build())
            sf.records.insert(0, des_save.Field(des_save.name_key('PLAYER_ISMALE'), des_save.T_U8, bytes([is_male])))
            return des_save.SaveFile(sf.build()).build()
        self.load_bytes(save(0))
        self.assertTrue(self.page.evaluate('saveIsFemale(current().save)'))
        self.assertEqual(self.page.evaluate('iconFor("A", 100700, true)'),
                         self.page.evaluate('itemGlyph("A", 100700).src'))
        self.assertIn('Female', self.page.get_attribute('#charcard .figure.doll', 'aria-label'))
        self.page.reload()
        self.load_bytes(save(1))
        self.assertEqual(self.page.evaluate('iconFor("A", 100700, false)'),
                         self.page.evaluate('itemGlyph("A", 100700).src'))

    def test_empty_slot_items_are_named_by_slot_and_count_as_nothing_worn(self):
        names = self.page.evaluate('["W:100300","A:101700","A:201700","A:301500","A:401500"].map(k => ITEM_BY_CAT.get(k))')
        self.assertEqual(['Bare hands (No Equipment)', 'Bare head (No Equipment)', 'Bare body (No Equipment)',
                          'Bare arms (No Equipment)', 'Bare legs (No Equipment)'], names)
        self.assertEqual(['svg', 'glyph empty'], self.page.evaluate(
            '[itemGlyph("A", 201700).tagName, itemGlyph("A", 201700).getAttribute("class")]'))
        self.assertIsNone(self.page.evaluate('iconFor("A", 201700)'))
        self.assertIsNotNone(self.page.evaluate('creationProblem("W", 100300)'))   # still not addable

    def test_without_icons_the_drawn_figure_returns(self):
        self.load_bytes(AddItemBrowserTests.fixture().build())
        self.assertEqual('svg', self.page.evaluate(
            '(() => { const keep = new Map(ICON_OF); ICON_OF.clear();'
            ' try { return characterFigure(current().save).tagName; } finally { for (const [k, v] of keep) ICON_OF.set(k, v); } })()'))

    def test_every_catalog_kind_has_a_glyph(self):
        self.assertEqual([], self.page.evaluate(
            '[...new Set(ITEMDB.map(r => itemKind(r[2], r[0])))].filter(k => !GLYPHS[k])'))
        self.assertEqual('head', self.page.evaluate('itemKind("A", 100000)'))
        self.assertEqual('unknown', self.page.evaluate('itemKind(null, 5)'))


if __name__ == '__main__':
    unittest.main()
