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


def _blob(bits: dict[int, int], size: int) -> bytes:
    raw = bytearray(size)
    for flag, value in bits.items():
        if value:
            raw[flag >> 3] |= 1 << (flag & 7)
    return bytes(raw)


def flags_save(primary: dict[int, int] | None = None,
               others: dict[int, bytes] | None = None,
               area: int | None = None,
               local: dict[tuple[int, int], int] | None = None) -> save.SaveFile:
    """A save with event-flag blobs; `primary` maps flag -> 0/1.

    With `area` (0-based) the save gets a MAPUID on that map and both per-area
    banks; `local` maps (area, flag) -> 0/1 for flags in either local range,
    mirrored into the primary blob for the current area like the game does.
    """
    primary = dict(primary or {})
    records = [save.Field(save.name_key('PLAYER_NAME'), save.T_STR, b'T')]
    if area is not None:
        local = local or {}
        for (a, flag), value in local.items():
            if a == area:
                primary[flag] = value
        records.append(save.Field(save.name_key('MAPUID'), save.T_BLOB,
                                  bytes([0, 0, 0, area + 1])))
        for first, end, key, slot in flags.RANGES:
            bank = {a * slot + flag - first: v for (a, flag), v in local.items()
                    if first <= flag < end}
            records.append(save.Field(key, save.T_BLOB,
                                      _blob(bank, flags.BLOBS[key][0] // 8)))
    records.append(save.Field(flags.PRIMARY, save.T_BLOB,
                              _blob(primary, flags.BLOBS[flags.PRIMARY][0] // 8)))
    for key, raw in (others or {}).items():
        records.append(save.Field(key, save.T_BLOB, raw))
    sf = save.SaveFile()
    sf.records = records
    return save.SaveFile(sf.build())


def defeat_save(primary: dict[int, int] | None = None, entries=None, area: int | None = None,
                local: dict[tuple[int, int], int] | None = None) -> save.SaveFile:
    """A save with an inventory the editor can add to (test_save.creation_save)
    and the event-flag blobs of flags_save."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_save
    grass = {'cat': 'G', 'id': 1001, 'quantity': 32, 'sort': 2}
    inv = test_save.creation_save(entries or [grass], rings=[105])
    extra = [r for r in flags_save(primary, area=area, local=local).records
             if r.key != save.name_key('PLAYER_NAME')]
    sf = save.SaveFile()
    sf.records = inv.records + extra
    return save.SaveFile(sf.build())


def inventory_ids(sf: save.SaveFile) -> dict[tuple[str, int], int]:
    import des_inventory
    return {(r['category'], r['id']): r.get('quantity', 1) for r in des_inventory.inventory(sf)}


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
        flags.set_flag(sf, 8084, True)
        again = save.SaveFile(sf.build())
        self.assertFalse(flags.get_flag(again, 4096))
        self.assertTrue(flags.get_flag(again, 8084))
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
        sf = flags_save({4096: 1, 4103: 1, 8084: 1})
        result = flags.respawn_boss(sf, self.db, 'phalanx')
        self.assertEqual([4096, 4103], result['cleared'])
        again = save.SaveFile(sf.build())
        rows = {b['name']: b for b in flags.bosses(again, self.db)}
        self.assertFalse(rows['Phalanx']['defeated'])
        self.assertFalse(rows['Phalanx']['soul_taken'])
        self.assertTrue(flags.get_flag(again, 8084))    # untouched

    def test_set_npc_state_mirrors_set_npc_state_flag(self):
        sf = flags_save({16440: 1, 16541: 1})           # working, stale twin of hostile
        result = flags.set_npc_state(sf, self.db, 'baldwin', 'dead')
        self.assertEqual('BALDWIN_STATE_DEAD', result['state'])
        self.assertEqual(16440, result['previous'])
        again = save.SaveFile(sf.build())
        rows = {n['list']: n for n in flags.npc_states(again, self.db)}
        self.assertEqual(['BALDWIN_STATE_DEAD'], rows['baldwin_flag_list']['set'])
        # the old twins are cleared and the outgoing state becomes the twin
        self.assertEqual(['BALDWIN_STATE_WORK'], rows['baldwin_flag_list']['backup'])

    def test_choosing_the_current_state_changes_nothing(self):
        sf = flags_save({16440: 1, 16541: 1})
        before = sf.build()
        flags.set_npc_state(sf, self.db, 'baldwin', 'work')
        self.assertEqual(before, sf.build())

    def test_marker_states_are_left_alone(self):
        sf = flags_save({16350: 1, 16354: 1})           # Thomas: storage + talked to
        flags.set_npc_state(sf, self.db, 'tomasu', 'angry')
        self.assertTrue(flags.get_flag(sf, 16354))
        self.assertTrue(flags.get_flag(sf, 16351))
        self.assertFalse(flags.get_flag(sf, 16350))

    def test_full_respawn_clears_the_fight(self):
        god = self.db.find_boss('dragon god')
        sf = flags_save({6400: 1, 6403: 1, 6401: 1, 6410: 1, 8050: 1}, area=0,
                        local={(5, 1050): 1, (5, 200): 1})
        result = flags.respawn_boss(sf, self.db, 'dragon god', full=True)
        self.assertEqual([6400, 6403, 6401, 6410], result['cleared'])
        self.assertEqual([1050], result['cleared_local'])
        self.assertTrue(flags.get_flag(sf, 8050))          # world counter left alone
        self.assertTrue(flags.get_local(sf, 5, 200))       # not a boss-room flag
        self.assertEqual(5, god['area'] - 1)

    def test_defeat_hands_over_the_demon_soul(self):
        sf = defeat_save({})
        before = sf.build()
        out, result = flags.defeat_boss(sf, self.db, 'phalanx')
        self.assertEqual(before, sf.build())                   # source untouched
        self.assertTrue(flags.get_flag(out, 4096))
        self.assertTrue(flags.get_flag(out, 4103))             # soul taken
        self.assertEqual(1, inventory_ids(out).get(('Goods', 15)))   # Lead Demon Soul
        self.assertEqual(['Lead Demon Soul'], result['items'])
        self.assertEqual([4103, 4096], sorted(result['set'], reverse=True))

    def test_defeat_adds_to_an_existing_soul_stack(self):
        soul = {'cat': 'G', 'id': 15, 'quantity': 1, 'sort': 1}
        out, _ = flags.defeat_boss(defeat_save({}, entries=[soul]), self.db, 'phalanx')
        self.assertEqual(2, inventory_ids(out)[('Goods', 15)])

    def test_defeat_gives_the_nexial_agent_once(self):
        out, first = flags.defeat_boss(defeat_save({}), self.db, 'old monk')
        self.assertIn('Nexial Agent', first['items'])
        self.assertTrue(flags.get_flag(out, 17800))
        out, second = flags.defeat_boss(out, self.db, 'dragon god')
        self.assertNotIn('Nexial Agent', second['items'])
        self.assertEqual(['Dragon Demon Soul', 'Pure Dragonstone'], second['items'])
        self.assertEqual(1, inventory_ids(out)[('Goods', 9993)])

    def test_defeat_hands_over_every_item_of_the_pickup(self):
        out, result = flags.defeat_boss(defeat_save({}), self.db, 'maiden astrea')
        self.assertEqual(['Pureblood Demon Soul', 'Ring of Sincere Prayer', 'Nexial Agent'], result['items'])
        self.assertIn(('Ring', 112), inventory_ids(out))

    def test_defeat_without_soul_or_after_the_soul_was_taken(self):
        out, result = flags.defeat_boss(defeat_save({}), self.db, 'phalanx', give_soul=False)
        self.assertEqual(([4096], []), (result['set'], result['items']))
        self.assertFalse(flags.get_flag(out, 4103))
        out, result = flags.defeat_boss(defeat_save({4103: 1}), self.db, 'phalanx')
        self.assertEqual([], result['items'])                  # soul already taken
        self.assertNotIn(('Goods', 15), inventory_ids(out))

    def test_defeat_refuses_a_dead_boss_and_fails_atomically(self):
        with self.assertRaises(ValueError):
            flags.defeat_boss(defeat_save({4096: 1}), self.db, 'phalanx')
        two = [{'cat': 'G', 'id': 15, 'quantity': 1, 'sort': 1}, {'cat': 'G', 'id': 15, 'quantity': 1, 'sort': 1}]
        sf = defeat_save({}, entries=two)                      # two stacks: the add refuses
        before = sf.build()
        with self.assertRaises(ValueError):
            flags.defeat_boss(sf, self.db, 'phalanx')
        self.assertEqual(before, sf.build())

    def test_forgive_mirrors_restore_backup_npc_state_flag(self):
        backup = self.db.backup_offset
        sf = flags_save({16441: 1, 16440 + backup: 1}, area=0, local={(0, 390): 1})
        npc = self.db.find_npc('baldwin')
        self.assertIsNotNone(flags.forgivable(sf, self.db, npc))
        result = flags.forgive_npc(sf, self.db, 'baldwin')
        self.assertEqual(16440, result['restored'])
        self.assertTrue(flags.get_flag(sf, 16440))
        self.assertFalse(flags.get_flag(sf, 16441))
        self.assertFalse(flags.get_flag(sf, 16440 + backup))
        self.assertFalse(flags.get_local(sf, 0, 390))
        self.assertTrue(flags.mirror_ok(sf))
        self.assertIsNone(flags.forgivable(sf, self.db, npc))

    def test_forgive_without_a_previous_state_only_clears_twins(self):
        sf = flags_save({16441: 1}, area=0, local={(0, 390): 1})
        result = flags.forgive_npc(sf, self.db, 'baldwin')
        self.assertIsNone(result['restored'])
        self.assertTrue(flags.get_flag(sf, 16441))
        self.assertTrue(flags.get_local(sf, 0, 390))

    def test_reset_map_and_rearm_pickups(self):
        sf = flags_save({}, area=5, local={(5, 11266): 1, (5, 1050): 1, (1, 200): 1})
        self.assertEqual([11266], flags.rearm_pickups(sf, self.db, 5))
        self.assertTrue(flags.get_local(sf, 5, 1050))
        self.assertEqual(1, flags.reset_map(sf, 5))
        self.assertEqual([], flags.local_flags(sf, 5))
        self.assertEqual([200], flags.local_flags(sf, 1))
        self.assertTrue(flags.mirror_ok(sf))

    def test_take_pickup_hands_over_its_items(self):
        sf = defeat_save({}, area=1, local={(1, 10240): 1})
        before = sf.build()
        out, result = flags.take_pickups(sf, self.db, 1, [10241, 10250])
        self.assertEqual(before, sf.build())                   # source untouched
        self.assertEqual([10241, 10250], result['taken'])
        self.assertEqual(['Old Ragged Robes', 'Old Ragged Gloves', 'Light Crossbow',
                          'Wooden Bolt ×16'], result['items'])
        have = inventory_ids(out)
        self.assertIn(('Armor', 202100), have)
        self.assertIn(('Armor', 302100), have)
        self.assertEqual(16, have[('Weapon', 170300)])          # ammo stacks
        self.assertTrue(flags.get_local(out, 1, 10241))
        self.assertTrue(flags.get_local(out, 1, 10250))
        self.assertTrue(flags.mirror_ok(out))                   # current map: copy written too

    def test_take_all_pickups_skips_the_taken_ones(self):
        sf = defeat_save({}, area=1, local={(1, 10240): 1})
        out, result = flags.take_pickups(sf, self.db, 1)
        self.assertNotIn(10240, result['taken'])
        self.assertEqual(len(self.db.pickups[1]) - 1, len(result['taken']))
        self.assertEqual([], flags.take_pickups(out, self.db, 1)[1]['taken'])
        self.assertTrue(all(flags.get_local(out, 1, f) for f in self.db.pickups[1]))
        self.assertNotIn('Jade Hair Ornament', result['items'])
        # 32 Half Moon Grass held + 22 lying in Boletaria: 18 fill the stack to
        # its limit of 50, the rest goes to the storage box as in game
        self.assertEqual(50, inventory_ids(out)[('Goods', 1001)])
        import des_inventory
        box = {(r['category'], r['id']): r for r in des_inventory.storage(out)}
        self.assertEqual(4, box[('Goods', 1001)]['low_quantity'])
        self.assertTrue(any(i.endswith('to storage)') for i in result['items']))

    def test_take_pickup_refuses_and_fails_atomically(self):
        sf = defeat_save({}, area=1, local={(1, 10240): 1})
        with self.assertRaises(ValueError):
            flags.take_pickups(sf, self.db, 1, [10240])       # already taken
        with self.assertRaises(ValueError):
            flags.take_pickups(sf, self.db, 1, [200])         # not a pickup
        two = [{'cat': 'G', 'id': 1002, 'quantity': 1, 'sort': 1}, {'cat': 'G', 'id': 1002, 'quantity': 1, 'sort': 1}]
        sf = defeat_save({}, entries=two, area=1)               # two Late Moon Grass stacks
        before = sf.build()
        with self.assertRaises(ValueError):
            flags.take_pickups(sf, self.db, 1, [10241, 10242])
        self.assertEqual(before, sf.build())

    def test_shop_counters_read_eight_flags_as_a_byte(self):
        sf = flags_save({15041: 1})
        rows = {s['flag']: s for s in flags.shop_counters(sf, self.db)}
        self.assertEqual(2, rows[15040]['value'])
        self.assertEqual(0, rows[15112]['value'])

    def test_every_list_has_a_name_and_labels(self):
        names = {n['name'] for n in self.db.npcs}
        for expected in ('Sage Freke', 'Graverobber Blige', 'Master Satsuki', 'Rydell',
                         'Scirvir, the Wanderer', 'Filthy Woman', 'Dregling Merchant'):
            self.assertIn(expected, names)
        for npc in self.db.npcs:
            self.assertTrue(npc['about'], npc['list'])
            for state in npc['states']:
                self.assertTrue(state['label'], state['name'])


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
            for npc in flags.npc_states(sf, self.db):   # markers (Thomas's ACTIVE) excluded
                self.assertLessEqual(len(npc['set']), 1, (path.name, npc['list']))

    def test_primary_copy_matches_the_current_area_slot(self):
        checked = 0
        for path in sorted(SAVES.glob('*/USR-DATA')):
            sf = save.load(path)
            if sf.find(flags.PRIMARY) is None or flags.current_area(sf) is None:
                continue
            self.assertTrue(flags.mirror_ok(sf), path)
            checked += 1
        self.assertGreater(checked, 0)

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


class LocalFlagTests(unittest.TestCase):
    """Area-local flags: per-area slots, and the primary copy of the current one."""

    def test_area_comes_from_mapuid(self):
        self.assertEqual(4, flags.current_area(flags_save(area=4)))
        self.assertIsNone(flags.current_area(flags_save()))

    def test_parse_area_and_target(self):
        self.assertEqual(1, flags.parse_area('m02'))
        self.assertEqual(1, flags.parse_area('2'))
        self.assertEqual(5, flags.parse_area('m06_02_00_00'))
        self.assertEqual((None, 4096), flags.parse_target('4096'))
        self.assertEqual((1, 200), flags.parse_target('m02:200'))
        for bad in ('m09', '0', 'x2'):
            with self.assertRaises(ValueError):
                flags.parse_area(bad)

    def test_local_bit_position(self):
        sf = flags_save(area=0, local={(5, 1050): 1})
        raw = sf.find(flags.LOCAL).raw
        bit = 5 * flags.LOCAL_SIZE + 1050
        self.assertEqual(1 << (bit & 7), raw[bit >> 3])
        self.assertTrue(flags.get_local(sf, 5, 1050))
        self.assertEqual([1050], flags.local_flags(sf, 5))

    def test_set_local_mirrors_only_the_current_area(self):
        sf = flags_save(area=1)
        flags.set_local(sf, 1, 200, True)
        flags.set_local(sf, 0, 200, True)
        primary = sf.find(flags.PRIMARY).raw
        self.assertTrue(flags.get(primary, 200))
        self.assertTrue(flags.get_local(sf, 0, 200))
        self.assertTrue(flags.mirror_ok(sf))
        flags.set_local(sf, 1, 201, True, mirror=False)    # the in-game diagnostic
        self.assertFalse(flags.mirror_ok(sf))

    def test_global_accessors_refuse_local_ids(self):
        sf = flags_save(area=1)
        with self.assertRaises(ValueError):
            flags.set_flag(sf, 200, True)
        with self.assertRaises(ValueError):
            flags.get_flag(sf, 3199)
        with self.assertRaises(ValueError):
            flags.set_local(sf, 1, 3200, True)
        with self.assertRaises(ValueError):
            flags.set_local(sf, 8, 1, True)

    def test_high_range_lives_in_bank_b(self):
        sf = flags_save(area=5, local={(5, 11265): 1, (0, 9045): 1})
        raw = sf.find(flags.BANK_B).raw
        for area, flag in ((5, 11265), (0, 9045)):
            bit = area * flags.BANK_B_AREA + flag - 8192
            self.assertTrue(flags.get(raw, bit))
        self.assertEqual([11265], flags.local_flags(sf, 5))
        self.assertTrue(flags.get(sf.find(flags.PRIMARY).raw, 11265))   # current area copy
        self.assertFalse(flags.get(sf.find(flags.PRIMARY).raw, 9045))
        self.assertTrue(flags.mirror_ok(sf))
        flags.set_local(sf, 5, 11266, True)
        self.assertTrue(flags.get(sf.find(flags.PRIMARY).raw, 11266))
        self.assertTrue(flags.mirror_ok(sf))
        flags.set_local(sf, 5, 11267, True, mirror=False)
        self.assertFalse(flags.mirror_ok(sf))

    def test_both_ranges_are_local_and_the_rest_global(self):
        for flag in (0, 3199, 8192, 12287):
            self.assertTrue(flags.is_local(flag), flag)
        for flag in (3200, 8191, 12288, 16140):
            self.assertFalse(flags.is_local(flag), flag)
        sf = flags_save(area=1)
        with self.assertRaises(ValueError):
            flags.set_flag(sf, 10240, True)
        self.assertEqual([0, 0, 0, 0, 0, 0, 0, 0], flags.local_counts(sf))
        self.assertIsNone(flags.local_counts(flags_save()))


class LocalDBTests(unittest.TestCase):
    def setUp(self):
        self.db = flags.load_db()
        if self.db is None:
            self.skipTest('flagdb.json not found (run tools/build_flagdb.py)')

    def test_local_labels_are_per_area(self):
        # 200 is a different event in the Nexus and in Boletaria
        self.assertNotEqual(self.db.event_label(200, 0), self.db.event_label(200, 1))
        self.assertIn('boss room', self.db.event_label(1050, 5).lower())

    def test_global_labels_from_params_and_npcs(self):
        self.assertIn('Shop stock', self.db.event_label(15112))
        self.assertIn('Makoto', self.db.event_label(15510))
        self.assertIn('Maiden in Black', self.db.event_label(16140))
        self.assertIn('previous state', self.db.event_label(16140 + self.db.backup_offset))
        self.assertIn('demon soul', self.db.event_label(4103))

    def test_every_documented_local_flag_fits_an_area(self):
        for area, rows in self.db.local.items():
            self.assertTrue(1 <= area <= flags.AREAS)
            self.assertTrue(all(flags.is_local(f) for f in rows))
        self.assertTrue(all(not flags.is_local(f) for f in self.db.globals))

    def test_pickups_come_from_the_map_layouts(self):
        # the Dragon God kill picked up these three in Stonefang 2-3
        self.assertIn("Master's Ring", self.db.event_label(11266, 5))
        self.assertIn('Pickup:', self.db.event_label(10240, 1))
        self.assertIn(11266, self.db.pickups[5])
        self.assertGreater(sum(map(len, self.db.pickups.values())), 400)

    def test_every_boss_soul_pickup_starts_with_its_demon_soul(self):
        import des_inventory
        catalog = des_inventory._catalog()
        for boss in self.db.bosses:
            category, item, count, _ = boss['soul_items'][0]
            self.assertEqual('demonsoul', catalog[(category, item)]['kind'], boss['name'])
        phalanx = self.db.find_boss('phalanx')
        self.assertEqual([['Goods', 15, 1, 'Lead Demon Soul']], phalanx['soul_items'])
        finals = sorted(b['name'] for b in self.db.bosses if b['bonus'])
        self.assertEqual(['Dragon God', 'Maiden Astrea', 'Old Monk', 'Storm King'], finals)
        for boss in self.db.bosses:
            for extra in boss['bonus']:
                self.assertEqual((17800, [['Goods', 9993, 1, 'Nexial Agent']]), (extra['flag'], extra['items']))

    def test_pickup_items_keep_ids_for_icons(self):
        rows = self.db.pickup_items
        for area, by_flag in rows.items():
            for flag, row in by_flag.items():
                self.assertTrue(flags.is_local(flag))
                self.assertIn('Pickup:', self.db.event_label(flag, area))
                for category, item, count, name in row['items']:
                    self.assertIn(category, ('Weapon', 'Armor', 'Ring', 'Goods'))
                    self.assertGreater(item, 0)
        grass = rows[1][10242]
        self.assertEqual('Boletaria 1-1', grass['level'])
        self.assertEqual([['Goods', grass['items'][0][1], 2, 'Late Moon Grass']], grass['items'])
        self.assertIn('Late Moon Grass ×2', self.db.event_label(10242, 1))   # labels unchanged

    def test_talk_sources_name_conversation_flags(self):
        self.assertIn('Heard:', self.db.event_label(10160, 1))
        self.assertIn('Stockpile Thomas', self.db.event_label(8512, 0))
        speakers = {s['script']: s['npc'] for s in self.db.doc['talk_scripts']}
        self.assertEqual('Acolyte of God', speakers['t0682'])
        self.assertEqual('Disciple of God', speakers['t0683'])
        self.assertEqual('Worshiper of God', speakers['t0684'])

    def test_curated_labels_and_glossary_win(self):
        self.assertTrue(self.db.event_label(720, 1).startswith('Ostrava thanked you'))
        self.assertEqual('Fog wall (host only)', self.db.event_label(240, 1))
        self.assertIn('Prison door', self.db.event_label(4, 3))
        self.assertEqual('Ever seen Phalanx', self.db.event_label(16901))

    def test_bosses_carry_their_fight_flags(self):
        god = self.db.find_boss('dragon god')
        self.assertTrue({6401, 6402, 6410, 6411} <= set(god['block']))
        self.assertIn(1050, god['room'])
        self.assertNotIn(god['soul'], god['block'])

    def test_forgiveness_table_matches_the_script(self):
        entries = [f for f in self.db.forgiveness if f['list'] == 'baldwin_flag_list']
        self.assertEqual([(16441, {'1': [390]})], [(f['id'], f['reset']) for f in entries])
        self.assertEqual(48, len(self.db.forgiveness))


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

    def test_defeat_cli_hands_over_the_soul(self):
        save.save(defeat_save({}), self.path)
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--defeat', 'phalanx', '--out', out]))   # seen in game: no flag
        written = save.load(out)
        self.assertTrue(flags.get_flag(written, 4096))
        self.assertEqual(1, inventory_ids(written).get(('Goods', 15)))
        out2 = str(Path(self.tmp.name) / 'out2')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--defeat', 'phalanx', '--no-soul', '--experimental', '--out', out2]))
        self.assertNotIn(('Goods', 15), inventory_ids(save.load(out2)))

    def test_sync_copy_needs_no_experimental_flag(self):
        sf = flags_save({}, area=1, local={(1, 200): 1})
        flags.set_local(sf, 1, 201, True, mirror=False)               # a mismatched copy
        self.assertFalse(flags.mirror_ok(sf))
        save.save(sf, self.path)
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(['events', self.path, '--sync-copy', '--out', out]))
        fixed = save.load(out)
        self.assertTrue(flags.mirror_ok(fixed))
        self.assertTrue(flags.get_local(fixed, 1, 201))

    def test_respawn_needs_no_experimental_flag(self):
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--respawn', 'phalanx', '--full', '--out', out]))
        self.assertFalse(flags.get_flag(save.load(out), 4096))

    def test_set_requires_experimental(self):
        argv = ['events', self.path, '--set', '200=1']
        with self.assertRaises(SystemExit):
            self.des_editor.main(argv)

    def test_set_flag_round_trip(self):
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--set', '8084=1', '--set', '4096=0',
             '--experimental', '--out', out]))
        sf = save.load(out)
        self.assertTrue(flags.get_flag(sf, 8084))
        self.assertFalse(flags.get_flag(sf, 4096))

    def test_bare_local_flag_is_an_error_naming_the_area(self):
        import io
        from contextlib import redirect_stderr
        des_save = self.des_editor.des_save
        des_save.save(flags_save({4096: 1}, area=1), self.path)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            code = self.des_editor.cmd_events(self.path, False, None, False, ['200=1'],
                                              None, None, None, True)
        self.assertEqual(2, code)
        self.assertIn('m02:200=1', buffer.getvalue())

    def test_local_flag_round_trip_writes_slot_and_copy(self):
        des_save = self.des_editor.des_save
        des_save.save(flags_save({}, area=1), self.path)
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--set', 'm02:200=1', '--set', '6:1050=1',
             '--experimental', '--out', out, '--no-backup']))
        sf = save.load(out)
        self.assertTrue(flags.get_local(sf, 1, 200))
        self.assertTrue(flags.get(sf.find(flags.PRIMARY).raw, 200))   # current area
        self.assertTrue(flags.get_local(sf, 5, 1050))
        self.assertFalse(flags.get(sf.find(flags.PRIMARY).raw, 1050))  # not current
        self.assertTrue(flags.mirror_ok(sf))

    def test_respawn_round_trip(self):
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--respawn', 'Phalanx', '--experimental',
             '--out', out]))
        sf = save.load(out)
        self.assertFalse(flags.get_flag(sf, 4096))
        self.assertFalse(flags.get_flag(sf, 4103))

    def test_high_range_and_recipes_round_trip(self):
        des_save = self.des_editor.des_save
        des_save.save(flags_save({16441: 1, 16440 + self.db.backup_offset: 1}, area=0,
                                 local={(0, 390): 1, (5, 11266): 1}), self.path)
        out = str(Path(self.tmp.name) / 'out')
        self.assertEqual(0, self.des_editor.main(
            ['events', self.path, '--set', 'm01:9045=1', '--forgive', 'baldwin',
             '--rearm-pickups', 'm06', '--experimental', '--out', out, '--no-backup']))
        sf = save.load(out)
        self.assertTrue(flags.get_local(sf, 0, 9045))
        self.assertTrue(flags.get(sf.find(flags.PRIMARY).raw, 9045))
        self.assertTrue(flags.get_flag(sf, 16440))
        self.assertFalse(flags.get_local(sf, 5, 11266))
        self.assertTrue(flags.mirror_ok(sf))

    def test_raw_flag_edits_require_experimental(self):
        # the recipes were seen working in game; a raw flag's effect depends on the flag
        for extra in (['--set', '4096=0'], ['--set', 'm02:200=0']):
            with self.assertRaises(SystemExit):
                self.des_editor.main(['events', self.path, *extra])

    def test_confirmed_recipes_need_no_opt_in(self):
        out = str(Path(self.tmp.name) / 'out')
        # (this fixture has no 78a5c2d7 bank, so --rearm-pickups is covered by the page tests)
        for extra in (['--forgive', 'baldwin'], ['--reset-map', 'm02'], ['--npc', 'baldwin=work']):
            self.assertEqual(0, self.des_editor.main(['events', self.path, *extra, '--out', out]), extra)

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
