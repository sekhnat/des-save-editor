"""Event-flag regressions: bit addressing, named views, recipes, CLI wiring."""
from pathlib import Path
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SAVES = Path(os.environ.get('DES_SAVE_DIR', ROOT.parent / '_SaveData' / 'PPSA01341'))
HAVE_SAVES = any(SAVES.glob('*/USR-DATA'))
sys.path.insert(0, str(ROOT / 'src'))
import des_flags as flags
import des_save as save


def flags_save(primary: dict[int, int] | None = None,
               others: dict[int, bytes] | None = None) -> save.SaveFile:
    """A save with the three event-flag blobs; `primary` maps flag -> 0/1."""
    primary = primary or {}

    def blob(bits: dict[int, int], size: int) -> bytes:
        raw = bytearray(size)
        for flag, value in bits.items():
            if value:
                raw[flag >> 3] |= 1 << (flag & 7)
        return bytes(raw)

    records = [save.Field(save.name_key('PLAYER_NAME'), save.T_STR, b'T'),
               save.Field(flags.PRIMARY, save.T_BLOB,
                          blob(primary, flags.BLOBS[flags.PRIMARY][0] // 8))]
    for key, raw in (others or {}).items():
        records.append(save.Field(key, save.T_BLOB, raw))
    sf = save.SaveFile()
    sf.records = records
    return save.SaveFile(sf.build())


class FlagDBTests(unittest.TestCase):
    def setUp(self):
        self.db = flags.load_db()
        if self.db is None:
            self.skipTest('flagdb.json not found (run tools/build_flagdb.py)')

    def test_boss_table_matches_the_game_script(self):
        self.assertEqual(16, len(self.db.bosses))
        ids = sorted(b['id'] for b in self.db.bosses)
        self.assertEqual([4096, 4224, 4360, 4480, 4756, 4895, 4992, 5123,
                          5251, 5380, 5650, 5770, 5888, 6174, 6272, 6400], ids)
        for boss in self.db.bosses:
            self.assertIn(boss['area'], range(1, 9), boss)
            self.assertIsNotNone(boss.get('soul'), boss)

    def test_boss_lookup_by_name_fragment(self):
        self.assertEqual(4096, self.db.find_boss('phalanx')['id'])
        self.assertEqual(6400, self.db.find_boss('Dragon God')['id'])
        with self.assertRaises(ValueError):
            self.db.find_boss('boss')
        with self.assertRaises(ValueError):
            self.db.find_boss('octopus')

    def test_npc_lists_have_distinct_state_ids(self):
        for npc in self.db.npcs:
            ids = [s['id'] for s in npc['states']]
            self.assertEqual(len(ids), len(set(ids)), npc['list'])
            self.assertTrue(ids, npc['list'])

    def test_npc_state_lookup_is_exact(self):
        npc = self.db.find_npc('baldwin')
        self.assertEqual(16442, self.db.find_state(npc, 'dead')['id'])
        with self.assertRaises(ValueError):
            self.db.find_state(npc, 'state')     # matches several
        with self.assertRaises(ValueError):
            self.db.find_npc('nobody')


class BitAddressingTests(unittest.TestCase):
    def test_bit_position_is_the_flag_id(self):
        raw = bytearray(flags.BLOBS[flags.PRIMARY][0] // 8)
        for flag in (0, 7, 8, 4096, 16146, 18047):
            raw[flag >> 3] |= 1 << (flag & 7)
        self.assertEqual([0, 7, 8, 4096, 16146, 18047], list(flags.iter_flags(bytes(raw))))

    def test_set_bit_flips_exactly_one_bit(self):
        raw = bytes(flags.BLOBS[flags.PRIMARY][0] // 8)
        one = flags.set_bit(raw, 4096, True)
        self.assertEqual(1, sum(bin(b).count('1') for b in one))
        self.assertEqual(raw, flags.set_bit(one, 4096, False))

    def test_ranges_are_enforced(self):
        with self.assertRaises(ValueError):
            flags.set_bit(bytes(8), flags.BLOBS[flags.PRIMARY][0], True)
        with self.assertRaises(ValueError):
            flags.get(bytes(8), -1)

    def test_set_flag_writes_through_the_save(self):
        sf = flags_save({4096: 1, 4103: 1})
        flags.set_flag(sf, 4096, False)
        flags.set_flag(sf, 200, True)
        again = save.SaveFile(sf.build())
        self.assertFalse(flags.get_flag(again, 4096))
        self.assertTrue(flags.get_flag(again, 200))
        self.assertTrue(again.checksum_ok())


class NamedViewTests(unittest.TestCase):
    def setUp(self):
        self.db = flags.load_db()
        if self.db is None:
            self.skipTest('flagdb.json not found (run tools/build_flagdb.py)')

    def test_bosses_read_their_flags(self):
        sf = flags_save({4096: 1, 4103: 1})
        rows = {b['name']: b for b in flags.bosses(sf, self.db)}
        self.assertTrue(rows['Phalanx']['defeated'])
        self.assertTrue(rows['Phalanx']['soul_taken'])
        self.assertFalse(rows['Tower Knight']['defeated'])
        self.assertFalse(rows['Flamelurker']['defeated'])

    def test_npc_states_read_one_state_per_npc(self):
        sf = flags_save({16140: 1, 16440: 1, 16441: 1, 17440: 1})
        rows = {n['list']: n for n in flags.npc_states(sf, self.db)}
        self.assertEqual(['HEROINE_STATE_WAIT_FOR_PLAYER'], rows['heroine_flag_list']['set'])
        # Baldwin has two states set (a broken save): both are reported
        self.assertEqual(['BALDWIN_STATE_WORK', 'BALDWIN_STATE_HOSTILE'],
                         rows['baldwin_flag_list']['set'])
        # 17440 = BALDWIN_STATE_WORK + backup offset: reported as the backup
        self.assertEqual(['BALDWIN_STATE_WORK'], rows['baldwin_flag_list']['backup'])


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.db = flags.load_db()
        if self.db is None:
            self.skipTest('flagdb.json not found (run tools/build_flagdb.py)')

    def test_respawn_boss_clears_death_and_soul(self):
        sf = flags_save({4096: 1, 4103: 1, 200: 1})
        result = flags.respawn_boss(sf, self.db, 'phalanx')
        self.assertEqual([4096, 4103], result['cleared'])
        again = save.SaveFile(sf.build())
        rows = {b['name']: b for b in flags.bosses(again, self.db)}
        self.assertFalse(rows['Phalanx']['defeated'])
        self.assertFalse(rows['Phalanx']['soul_taken'])
        self.assertTrue(flags.get_flag(again, 200))     # untouched

    def test_set_npc_state_leaves_exactly_one(self):
        sf = flags_save({16440: 1, 16540: 1})           # work + its backup
        result = flags.set_npc_state(sf, self.db, 'baldwin', 'dead')
        self.assertEqual('BALDWIN_STATE_DEAD', result['state'])
        again = save.SaveFile(sf.build())
        rows = {n['list']: n for n in flags.npc_states(again, self.db)}
        self.assertEqual(['BALDWIN_STATE_DEAD'], rows['baldwin_flag_list']['set'])
        self.assertEqual([], rows['baldwin_flag_list']['backup'])


@unittest.skipUnless(HAVE_SAVES, 'no sample saves (set DES_SAVE_DIR to run this)')
class SampleSaveTests(unittest.TestCase):
    """The real saves: every NPC has at most one state; bosses match the ends."""

    def setUp(self):
        self.db = flags.load_db()
        if self.db is None:
            self.skipTest('flagdb.json not found (run tools/build_flagdb.py)')

    def test_every_npc_has_at_most_one_state(self):
        for path in sorted(SAVES.glob('*/USR-DATA')):
            sf = save.load(path)
            if sf.find(flags.PRIMARY) is None:
                continue                     # the options profile has no blobs
            for npc in flags.npc_states(sf, self.db):
                if npc['list'] != 'tomasu_flag_list':      # WAIT + ACTIVE coexist
                    self.assertLessEqual(len(npc['set']), 1, (path.name, npc['list']))

    def test_fresh_character_has_no_boss_flags(self):
        for path in sorted(SAVES.glob('*/USR-DATA')):
            sf = save.load(path)
            if sf.find(flags.PRIMARY) is None:
                continue                     # the options profile has no blobs
            killed = sf.get('DEMONSKILLED')
            if killed != 0:
                continue
            dead = [b['name'] for b in flags.bosses(sf, self.db) if b['defeated']]
            self.assertEqual([], dead, path)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.db = flags.load_db()
        if self.db is None:
            self.skipTest('flagdb.json not found (run tools/build_flagdb.py)')
        import des_editor
        self.des_editor = des_editor
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'USR-DATA')
        des_editor.des_save.save(flags_save({4096: 1, 4103: 1, 16140: 1}), self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_only_report(self):
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = self.des_editor.cmd_events(self.path, False, None, False, [],
                                              None, None, None, True)
        self.assertEqual(0, code)
        self.assertIn('DEAD  Phalanx', buffer.getvalue())
        self.assertIn('HEROINE_STATE', buffer.getvalue())
    def test_list_known(self):
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.des_editor.cmd_events(None, False, None, True, [],
                                       None, None, None, True)
        text = buffer.getvalue()
        self.assertIn('Phalanx', text)
        self.assertIn('baldwin_flag_list', text)

    def test_set_requires_experimental(self):
        argv = ['events', self.path, '--set', '200=1']
        with self.assertRaises(SystemExit):
            self.des_editor.main(argv)

    def test_set_flag_round_trip(self):
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--set', '200=1', '--set', '4096=0',
             '--experimental', '--out', out]))
        sf = save.load(out)
        self.assertTrue(flags.get_flag(sf, 200))
        self.assertFalse(flags.get_flag(sf, 4096))

    def test_respawn_round_trip(self):
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--respawn', 'Phalanx', '--experimental',
             '--out', out]))
        sf = save.load(out)
        self.assertFalse(flags.get_flag(sf, 4096))
        self.assertFalse(flags.get_flag(sf, 4103))

    def test_npc_round_trip(self):
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--npc', 'baldwin=hostile', '--experimental',
             '--out', out]))
        sf = save.load(out)
        self.assertTrue(flags.get_flag(sf, 16441))
        self.assertFalse(flags.get_flag(sf, 16440))

    def test_bad_boss_name_is_an_error(self):
        # cmd_events reports CLI errors as an exit code, not an exception
        self.assertEqual(2, self.des_editor.cmd_events(
            self.path, False, None, False, [], 'octopus', None, None, True))


if __name__ == '__main__':
    unittest.main()
