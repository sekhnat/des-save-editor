"""Integration tests that run against real decrypted saves.

These are skipped unless a compatible save set is available. Point the suite at
your own copy with:

    DES_SAVE_DIR=/path/to/_SaveData/PPSA01341 python3 -m unittest discover -s tests -v

The directory must contain SAVEDATA0PlayerProfile1/USR-DATA and
SAVEDATA0PlayerProfile0/USR-DATA (the smaller and larger character profiles).
No save files are shipped with this repository, and these tests never write to
the originals: every edit happens on an in-memory copy and the SHA-256 of each
source file is asserted unchanged at the end of the run.
"""
from pathlib import Path
import hashlib
import io
import os
import unittest
import zipfile

from playwright.sync_api import sync_playwright

EDITOR = Path(__file__).resolve().parents[1]
SAVES = Path(os.environ.get('DES_SAVE_DIR', EDITOR.parent / '_SaveData' / 'PPSA01341'))
PLAYER = SAVES / 'SAVEDATA0PlayerProfile1' / 'USR-DATA'
LARGE = SAVES / 'SAVEDATA0PlayerProfile0' / 'USR-DATA'
HAVE_SAVES = PLAYER.exists() and LARGE.exists()


@unittest.skipUnless(HAVE_SAVES, f'no sample saves in {SAVES} (set DES_SAVE_DIR to run these)')
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in SAVES.glob('*/USR-DATA')}
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        for path, digest in cls.hashes.items():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f'Original changed: {path}'

    def setUp(self):
        self.page = self.browser.new_page(accept_downloads=True)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto((EDITOR / 'des_editor.html').as_uri())

    def tearDown(self):
        self.page.close()
        self.assertEqual([], self.errors)

    def load(self, path=PLAYER):
        self.page.set_input_files('#file', str(path))
        self.page.wait_for_function('state.files.length > 0 && !!current()')

    def test_all_real_saves_round_trip(self):
        for path in SAVES.glob('*/USR-DATA'):
            with self.subTest(path=path.parent.name):
                data = list(path.read_bytes())
                self.assertTrue(self.page.evaluate('(data) => bytesEq(new SaveFile(new Uint8Array(data)).build(), new Uint8Array(data))', data))

    def test_signed_integer(self):
        self.assertEqual(-1, self.page.evaluate('new Field(1,T.I32,new Uint8Array([255,255,255,255])).value'))
        self.assertEqual(-2147483648, self.page.evaluate('new Field(1,T.I32,new Uint8Array([0,0,0,128])).value'))

    def test_invalid_scalar_edits_are_atomic(self):
        self.assertTrue(self.page.evaluate(r'''() => {
          for (const [type, values] of [[T.U8,[-1,256,1.5,NaN]], [T.U16,[-1,65536]],
                                       [T.I32,[-2147483649,2147483648,9999999999]], [T.F32,[Infinity,NaN,1e40]]]) {
            const f=new Field(1,type,new Uint8Array(SIZES[type]));
            for (const value of values) {
              const before=f.hex;
              try { f.value=value; return false; } catch (_) { if(f.hex!==before) return false; }
            }
          }
          return true;
        }'''))

    def test_strict_hex_and_fixed_sizes(self):
        self.assertTrue(self.page.evaluate(r'''() => {
          for (const hex of ['0g','abc','12zz','-1']) {
            try { hexToBytes(hex); return false; } catch (_) {}
          }
          const f=new Field(1,T.RAW4,new Uint8Array(4));
          try { f.value='aa'; return false; } catch (_) {}
          return f.hex==='00000000' && hexToBytes('aa bb\ncc dd').length===4;
        }'''))

    def test_truncated_records_and_varints_rejected(self):
        self.assertTrue(self.page.evaluate(r'''() => {
          for(const bytes of [[1,0,0,0,T.I32,1],[1,0,0,0,T.STR,4,65],
                              [1,0,0,0,T.BLOB,128],[1,0,0,0,T.CONT,1], [1,0,0,0]]) {
            const b=new Uint8Array(bytes);
            try { parseFields(b,0,b.length,null); return false; } catch (_) {}
          }
          return true;
        }'''))

    def test_invalid_json_preserves_edits_and_history(self):
        self.load()
        self.page.evaluate(r'''() => {
          current().save.set('PLAYER_SOULS',24680);
          const doc=JSON.parse(jsonDump());
          doc.fields[doc.fields.length-1].key='12345678';
          document.querySelector('#json').value=JSON.stringify(doc);
          applyJson();
        }''')
        self.assertEqual(24680, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.assertEqual(0, self.page.evaluate('current().undo.length'))

    def test_noop_json_is_byte_identical(self):
        self.load(LARGE)
        self.assertTrue(self.page.evaluate(r'''() => {
          const before=current().save.build();
          document.querySelector('#json').value=jsonDump(); applyJson();
          return bytesEq(before,current().save.build());
        }'''))

    def test_json_rejects_type_changes(self):
        self.load()
        self.assertTrue(self.page.evaluate(r'''() => {
          const before=current().save.build(), doc=JSON.parse(jsonDump());
          doc.fields[0].type='0x08';
          document.querySelector('#json').value=JSON.stringify(doc); applyJson();
          return bytesEq(before,current().save.build());
        }'''))

    def test_json_undo_redo(self):
        self.load()
        self.page.evaluate(r'''() => {
          const doc=JSON.parse(jsonDump());
          const visit=rows=>{ for(const f of rows) { if(f.name==='PLAYER_SOULS') f.value=777777; if(f.children) visit(f.children); } };
          visit(doc.fields); document.querySelector('#json').value=JSON.stringify(doc); applyJson();
        }''')
        self.assertEqual(777777, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.page.evaluate('doUndo()')
        self.assertEqual(176, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.page.evaluate('doRedo()')
        self.assertEqual(777777, self.page.evaluate("current().save.get('PLAYER_SOULS')"))

    def test_dirty_checks_are_cached(self):
        self.load(LARGE)
        self.assertLessEqual(self.page.evaluate(r'''() => {
          const s=current().save, original=s.build.bind(s); let calls=0;
          s.build=()=>{calls++;return original();};
          for(let i=0;i<10;i++) isDirty(current());
          return calls;
        }'''), 1)

    def test_inactive_panels_are_lazy(self):
        self.load(LARGE)
        self.assertEqual(0, self.page.locator('#alltable input').count())
        self.assertEqual('', self.page.input_value('#json'))
        self.page.click('[data-tab=all]')
        self.assertLessEqual(self.page.locator('#alltable input').count(), 100)

    def test_invalid_form_input_does_not_wrap_or_save(self):
        self.load()
        self.page.locator('[data-field=PLAYER_SOULS]').fill('9999999999')
        self.assertEqual(176, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.assertTrue(self.page.locator('#save').is_disabled())
        self.page.locator('[data-field=PLAYER_SOULS]').fill('424242')
        self.assertFalse(self.page.locator('#save').is_disabled())
        self.assertEqual(424242, self.page.evaluate("current().save.get('PLAYER_SOULS')"))

    def test_empty_array_inserted_before_count_and_invalid_edit_atomic(self):
        self.load()
        self.assertTrue(self.page.evaluate('''() => {
          const s=current().save, before=s.build();
          try { setInv(s,[100,70000]); return false; } catch (_) {}
          if(!bytesEq(before,s.build())) return false;
          setInv(s,[113]);
          const list=allLists(s).find(list=>list.includes(s.find(COUNT_KEY)));
          return list.indexOf(invSlots(s)[0]) < list.indexOf(s.find(COUNT_KEY)) && s.get(COUNT_KEY)===1;
        }'''))

    def test_download_preserves_original_and_has_valid_checksum(self):
        self.load()
        self.page.evaluate("window.showSaveFilePicker=undefined; current().save.set('PLAYER_SOULS',424242)")
        original = self.page.evaluate('Array.from(current().original)')
        with self.page.expect_download() as download:
            self.page.evaluate('saveFile()')
        payload = Path(download.value.path()).read_bytes()
        self.assertEqual(original, self.page.evaluate('Array.from(current().original)'))
        self.assertEqual(424242, self.page.evaluate('(bytes)=>new SaveFile(new Uint8Array(bytes)).get("PLAYER_SOULS")', list(payload)))
        self.assertTrue(self.page.evaluate('(bytes)=>new SaveFile(new Uint8Array(bytes)).checksumOk', list(payload)))

    def test_patch_import_atomic(self):
        self.load()
        self.page.evaluate('document.querySelector("#json").value=JSON.stringify({PLAYER_SOULS:5555}); applyJson()')
        self.assertEqual(5555, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.page.evaluate('document.querySelector("#json").value=JSON.stringify({PLAYER_SOULS:123,DOES_NOT_EXIST:1}); applyJson()')
        self.assertEqual(5555, self.page.evaluate("current().save.get('PLAYER_SOULS')"))

    def test_save_cancel_and_error_do_not_clear_dirty(self):
        self.load()
        self.page.evaluate("current().save.set('PLAYER_SOULS',424242)")
        for name in ('AbortError', 'NotAllowedError'):
            self.page.evaluate('(name)=>{window.showSaveFilePicker=async()=>{throw new DOMException("test",name);};}', name)
            self.page.evaluate('saveFile()')
            self.assertTrue(self.page.evaluate('isUnsaved(current())'))

    def test_bundle_has_profiles_and_original_backups(self):
        self.load()
        self.page.evaluate("current().save.set('PLAYER_SOULS',424242)")
        with self.page.expect_download() as download:
            self.page.evaluate('saveAll()')
        with zipfile.ZipFile(io.BytesIO(Path(download.value.path()).read_bytes())) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertIn('manifest.json', bundle.namelist())
            self.assertTrue(any(name.startswith('originals/') and name.endswith('/USR-DATA') for name in bundle.namelist()))
            self.assertTrue(any(name.startswith('edited/') and name.endswith('/USR-DATA') for name in bundle.namelist()))

    def test_catalog_preserves_category_collisions_and_wide_ids(self):
        self.load()
        self.assertTrue(self.page.evaluate("ITEMDB.some(r=>r[0]===1000&&r[2]==='G'&&r[1]==='Crescent Moon Grass')"))
        self.assertTrue(self.page.evaluate("ITEMDB.some(r=>r[0]===1000&&r[2]==='S'&&r[1]==='Soul Arrow')"))
        self.assertTrue(self.page.evaluate("ITEMDB.some(r=>r[0]>=100000&&r[2]==='A')"))
        self.page.click('[data-tab=catalog]')
        self.page.select_option('#catalogcategory', 'A')
        self.assertGreater(self.page.locator('#catalogbody tr').count(), 0)

    def test_json_drafts_survive_tabs_and_detect_staleness(self):
        self.load()
        self.page.click('[data-tab=json]')
        draft = self.page.input_value('#json').replace('"value": 176', '"value": 12345', 1)
        self.page.fill('#json', draft)
        self.page.click('[data-tab=editor]')
        self.page.fill('[data-field=PLAYER_SOULS]', '8888')
        self.page.click('[data-tab=json]')
        self.assertEqual(draft, self.page.input_value('#json'))
        self.page.click('#applyjson')
        self.assertEqual(8888, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.assertIn('stale', self.page.text_content('#message'))

    def test_form_edits_group_and_focusing_does_not_destroy_redo(self):
        self.load()
        field = self.page.locator('[data-field=PLAYER_SOULS]')
        field.focus()
        self.assertEqual(0, self.page.evaluate('current().undo.length'))
        field.fill('1234')
        field.fill('12345')
        self.assertEqual(1, self.page.evaluate('current().undo.length'))
        self.page.evaluate('doUndo()')
        self.page.locator('[data-field=PLAYER_SOULS]').focus()
        self.assertEqual(1, self.page.evaluate('current().redo.length'))

    def test_experimental_mapping_is_opt_in(self):
        self.load()
        self.assertFalse(self.page.is_checked('#experimental'))
        self.assertTrue(self.page.get_by_text('+ Add value…', exact=True).is_disabled())
        self.page.check('#experimental')
        self.page.get_by_text('+ Add value…', exact=True).click()
        self.page.fill('#pickersearch', 'Cling Ring')
        self.page.locator('.pickrow').first.click()
        self.assertEqual([113], self.page.evaluate('invIds(current().save)'))
        self.page.evaluate('doUndo()')
        self.assertEqual([], self.page.evaluate('invIds(current().save)'))

    def test_blob_edit_is_undoable_and_download_is_exact(self):
        self.load()
        self.page.evaluate("openBlob(current().save.flat.find(([f])=>f.type===T.BLOB)[0])")
        before = self.page.input_value('#blobhex')
        with self.page.expect_download() as download:
            self.page.click('#downloadblob')
        self.assertEqual(bytes.fromhex(before), Path(download.value.path()).read_bytes())
        self.page.fill('#blobhex', '01020304')
        self.page.click('#applyblob')
        self.assertEqual('01020304', self.page.evaluate("current().save.flat.find(([f])=>f.type===T.BLOB)[0].hex"))
        self.page.evaluate('doUndo()')
        self.assertEqual(before, self.page.evaluate("current().save.flat.find(([f])=>f.type===T.BLOB)[0].hex"))

    def test_exported_patch_reapplies_and_conflicts_atomically(self):
        self.load()
        self.page.fill('[data-field=PLAYER_SOULS]', '424242')
        with self.page.expect_download() as download:
            self.page.evaluate('downloadPatch()')
        patch = Path(download.value.path()).read_text()
        self.page.evaluate('revertOriginal()')
        self.page.evaluate('(patch)=>{document.querySelector("#json").value=patch;applyJson();}', patch)
        self.assertEqual(424242, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.page.evaluate('(patch)=>{document.querySelector("#json").value=patch;applyJson();}', patch)
        self.assertEqual(424242, self.page.evaluate("current().save.get('PLAYER_SOULS')"))
        self.assertIn('conflict', self.page.text_content('#message'))

    def test_source_checksum_warning_also_for_options(self):
        path = SAVES / 'SAVEDATA0OptionsProfile0/USR-DATA'
        raw = bytearray(path.read_bytes())
        raw[4] ^= 1
        self.page.set_input_files('#file', {'name':'USR-DATA','mimeType':'application/octet-stream','buffer':bytes(raw)})
        self.page.wait_for_function('state.files.length === 1')
        self.assertFalse(self.page.evaluate('current().sourceChecksumOk'))
        self.assertTrue(self.page.evaluate('current().roundtrip'))
        self.assertIn('checksum', self.page.text_content('#diagbox'))

    def test_async_write_does_not_mark_later_edits_exported(self):
        self.load()
        self.page.evaluate(r'''() => {
          current().save.set('PLAYER_SOULS',1111);
          window.showSaveFilePicker=async()=>({createWritable:async()=>({
            write:async()=>{current().save.set('PLAYER_SOULS',2222);},close:async()=>{},abort:async()=>{}
          })});
        }''')
        self.page.evaluate('saveFile()')
        self.assertTrue(self.page.evaluate('isUnsaved(current())'))
        self.assertEqual(2222, self.page.evaluate("current().save.get('PLAYER_SOULS')"))

    def test_estimated_soul_level_has_no_off_by_one(self):
        self.load()
        self.assertEqual(1, self.page.evaluate('current().save.summary().soulLevel'))
        self.page.evaluate("for(const a of ATTRS) current().save.set('PLAYER_CURRENT'+a,99)")
        self.assertEqual(712, self.page.evaluate('current().save.summary().soulLevel'))

    def test_seeded_python_javascript_differential_roundtrips(self):
        import random
        import sys
        sys.path.insert(0, str(EDITOR))
        import des_save
        rng = random.Random(20261019)
        fixtures = []
        for index in range(100):
            sf = des_save.SaveFile()
            children = [des_save.Field(100 + kind, kind, rng.randbytes(size))
                        for kind, size in des_save.SIZES.items()]
            children.extend([des_save.Field(500, des_save.T_STR, rng.randbytes(index)),
                             des_save.Field(501, des_save.T_BLOB, rng.randbytes(index * 13))])
            sf.records = [des_save.Field(des_save.name_key('PLAYER_SOULS'), des_save.T_I32, (176).to_bytes(4, 'little')),
                          des_save.Field(502, des_save.T_CONTAINER, children=children)]
            original = sf.build()
            sf.set('PLAYER_SOULS', 424242)
            fixtures.append({'original': list(original), 'edited': list(sf.build())})
        self.assertTrue(self.page.evaluate(r'''fixtures => fixtures.every(({original,edited}) => {
          const source=new Uint8Array(original), s=new SaveFile(source);
          if(!bytesEq(source,s.build())) return false;
          s.set('PLAYER_SOULS',424242);
          return bytesEq(new Uint8Array(edited),s.build());
        })''', fixtures))

    def test_unchanged_json_preserves_float_bit_patterns(self):
        import sys
        sys.path.insert(0, str(EDITOR))
        import des_save
        sf = des_save.SaveFile()
        sf.records = [des_save.Field(index, des_save.T_F32, bytes.fromhex(bits))
                      for index, bits in enumerate(['00000080', '0100c07f', '0000807f', '01000000'])]
        raw = sf.build()
        self.page.set_input_files('#file', {'name':'USR-DATA', 'mimeType':'application/octet-stream', 'buffer':raw})
        self.page.wait_for_function('!!current()')
        self.assertTrue(self.page.evaluate(r'''() => {
          const before=current().save.build(); document.querySelector('#json').value=jsonDump(); applyJson();
          return bytesEq(before,current().save.build());
        }'''))

    def test_recovered_arrays_card_matches_python(self):
        import sys
        sys.path.insert(0, str(EDITOR))
        import des_arrays, des_save
        for path in sorted(SAVES.glob('*/USR-DATA')):
            with self.subTest(path=path.parent.name):
                self.load(path)
                expected = [[group['state'],
                             [f.value if isinstance(f.value, int) else None
                              for f in group['members']]]
                            for group in des_arrays.discover(des_save.load(str(path)))]
                got = self.page.evaluate(
                    'discoverArrays(current().save).map(g => [g.state,'
                    ' g.members.map(f => typeof f.value === "number" ? f.value : null)])')
                self.assertEqual(expected, got)

    def test_recovered_arrays_card_renders_and_edits(self):
        self.load(PLAYER)
        self.page.wait_for_selector('#arraycard')
        text = self.page.evaluate("document.querySelector('#arraycard').textContent")
        self.assertIn('Recovered structures', text)
        self.assertIn('container v3', text)                     # the blob header is surfaced
        self.assertIn('Crescent Moon Grass', text)             # the 7-slot item array
        index = self.page.evaluate(
            """() => [...document.querySelectorAll('#arraycard input[type=number]')]
                     .findIndex(el => el.value === '1000')""")
        self.assertGreaterEqual(index, 0)
        slot = self.page.query_selector_all('#arraycard input[type=number]')[index]
        slot.fill('1002')
        slot.dispatch_event('change')
        self.page.wait_for_timeout(200)
        values = self.page.evaluate('discoverArrays(current().save).map(g => g.members.map(f => f.value))')
        self.assertIn(1002, [value for group in values for value in group])
        self.page.evaluate('doUndo()')
        values = self.page.evaluate('discoverArrays(current().save).map(g => g.members.map(f => f.value))')
        self.assertIn(1000, [value for group in values for value in group])

    def test_blob_is_not_compressed_and_has_no_network_use(self):
        self.load(LARGE)
        info = self.page.evaluate("""() => {
          const blob = current().save.flat.map(([f]) => f)
            .filter(f => f.type === T.BLOB && f.raw.length > 1000)
            .find(f => new DataView(f.raw.buffer, f.raw.byteOffset).getUint32(0, true) === 3).raw;
          const counts = new Array(256).fill(0);
          for (let i = 16; i < blob.length; i++) counts[blob[i]]++;
          let h = 0; const n = blob.length - 16;
          for (const c of counts) if (c) h -= (c / n) * Math.log2(c / n);
          return { entropy: h, distinct: counts.filter(c => c > 0).length };
        }""")
        self.assertTrue(info['distinct'] > 200)                # dense payload, not a text blob
        self.assertLess(info['entropy'], 7.9)                  # below what compression or encryption gives

if __name__ == '__main__':
    unittest.main()
