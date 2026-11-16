"""UI atlas reader, icon mapping and the embedded icon pack."""
from pathlib import Path
import json
import os
import struct
import subprocess
import sys
import unittest

try:
    import numpy as np
except ImportError:                     # the atlas reader needs numpy; the embed checks do not
    np = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
if np is not None:
    import des_uiatlas as atlas  # noqa: E402
import des_gamedata as gamedata  # noqa: E402
import embed_icons  # noqa: E402

GAME = Path(os.environ.get('DES_GAME_DIR', ROOT.parent / 'PPSA01342-app'))
HAVE_GAME = (GAME / 'ui/textures/_ps5/global.ctal').exists()


@unittest.skipIf(np is None, 'numpy is not installed')
class AtlasFormatTests(unittest.TestCase):
    def test_sprite_names_hash_with_fnv1a_over_the_uppercased_name(self):
        self.assertEqual(atlas.fnv1a_upper('TEX_INVICON_PLACEHOLDER'), atlas.fnv1a_upper('Tex_InvIcon_Placeholder'))
        self.assertEqual(0x811C9DC5, atlas.fnv1a_upper(''))
        self.assertEqual((0x811C9DC5 ^ ord('A')) * 0x01000193 & 0xFFFFFFFF, atlas.fnv1a_upper('a'))

    def test_parse_ctal(self):
        path = b'$/ui/x.ctxr'
        records = b''
        for name_hash, (u0, v0, u1, v1), page in ((7, (0.0, 0.0, 0.25, 0.5), 0), (9, (0.5, 0.25, 0.75, 1.0), 3)):
            records += struct.pack('<I8fI', name_hash, u0, v0, u0, v1, u1, v1, u1, v0, page)
        data = bytes([len(path)]) + path + struct.pack('<I', 2) + records
        name, sprites = atlas.parse_ctal(data, size=16)
        self.assertEqual('$/ui/x.ctxr', name)
        self.assertEqual([atlas.Sprite(7, 0, 0, 4, 8, 0), atlas.Sprite(9, 8, 4, 4, 12, 3)], sprites)
        with self.assertRaises(ValueError):
            atlas.parse_ctal(data[:-1])

    def test_detile_inverts_tile(self):
        rng = np.random.default_rng(1)
        image = rng.integers(0, 256, (256, 384, 4), dtype=np.uint8)
        tiled = atlas.tile_64kb_32bpp(image)
        self.assertNotEqual(image.tobytes(), tiled)
        np.testing.assert_array_equal(image, atlas.detile_64kb_32bpp(tiled, 384, 256))

    def test_swizzle_fills_each_block_exactly_once(self):
        xt, yt = atlas._swizzle_tables()
        offsets = (yt[:, None] ^ xt[None, :]).reshape(-1)
        self.assertEqual(atlas.BLOCK * atlas.BLOCK, len(set(offsets.tolist())))
        self.assertEqual(atlas.BLOCK_BYTES - 4, int(offsets.max()))

    def test_param_strings_follow_row_pointers(self):
        fields = [('iconId', 'u16', 2), ('pad', 'dummy8', 6), ('bpPreviewKey', 'string', 8)]
        definition = bytearray(0x30 + 0xB0 * len(fields))
        struct.pack_into('<IHHH', definition, 0, len(definition), 0x30, 1, len(fields))
        definition[0x0C:0x0C + 6] = b'TEST_P'
        for i, (name, kind, size) in enumerate(fields):
            at = 0x30 + i * 0xB0
            definition[at + 0x40:at + 0x40 + len(kind)] = kind.encode()
            struct.pack_into('<i', definition, at + 0x64, size)
            definition[at + 0x90:at + 0x90 + len(name)] = name.encode()
        rows = 2
        data = bytearray(0x30 + rows * 12)
        data[0x0C:0x0C + 6] = b'TEST_P'
        struct.pack_into('<H', data, 0x0A, rows)
        strings = b'Elixir\0'
        base = len(data) + rows * 16
        for i, row_id in enumerate((5, 6)):
            struct.pack_into('<III', data, 0x30 + i * 12, row_id, len(data) + i * 16, 0)
        body = struct.pack('<H6xQ', 1, base) + struct.pack('<H6xQ', 2, 0)
        data += body + strings
        self.assertEqual({5: {'bpPreviewKey': 'Elixir'}, 6: {}},
                         gamedata.param_strings(bytes(definition), bytes(data)))


class EmbedTests(unittest.TestCase):
    def test_empty_pack_embeds_empty_tables(self):
        html = 'a\n/* ITEMDB:END */\nb'
        once = embed_icons.embed(html, None)
        self.assertIn('const ICON_IMAGES = [\n];', once)
        self.assertIn('const ICON_OF = new Map([]);', once)
        self.assertEqual(once, embed_icons.embed(once, None))

    def test_page_matches_the_committed_pack(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/embed_icons.py'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_committed_pack_is_consistent(self):
        pack = json.loads((ROOT / 'iconpack.json').read_text())
        count = len(pack['images'])
        for key, value in pack['items'].items():
            self.assertRegex(key, r'^[GWARS]:\d+$')
            for index in value if isinstance(value, list) else [value]:
                self.assertTrue(0 <= index < count, key)


@unittest.skipUnless(HAVE_GAME and np is not None, 'no game files (set DES_GAME_DIR) or no numpy')
class GameIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_icons
        cls.build = build_icons
        cls.mapping, cls.icons = build_icons.match(GAME)

    def icon(self, key, slot=0):
        return self.mapping[key][slot]

    def test_items_sharing_a_legacy_icon_id_get_their_own_icons(self):
        # Elixir and Bearbug Grains share iconId 1036 in the legacy PARAM.
        self.assertIsNotNone(self.icon('G:9926'))
        self.assertNotEqual(self.icon('G:9926'), self.icon('G:9922'))

    def test_upgrades_share_the_base_icon_and_armour_has_genders(self):
        self.assertEqual(self.icon('W:10000'), self.icon('W:10003'))
        self.assertNotEqual(self.icon('A:100700', 0), self.icon('A:100700', 1))
        self.assertIsNotNone(self.icon('A:199905'))           # enemy set: gender-neutral icon

    def test_large_weapons_use_their_bigger_tiles_and_placeholders_are_skipped(self):
        for key in ('W:20700', 'W:21605', 'W:40200', 'W:140100', 'W:140200'):
            sprite = self.icons[self.icon(key)]
            self.assertGreater(sprite.w * sprite.h, 260 * 300, key)
        self.assertIsNone(self.icon('R:200'))                 # only a 2048 x 2048 placeholder sheet

    def test_empty_slot_rows_get_no_icon(self):
        for key in ('A:101700', 'A:201700', 'A:301500', 'A:401500', 'W:100300'):
            self.assertNotIn(key, self.mapping)

    def test_coverage(self):
        stats = self.build.coverage(self.mapping)
        for cat, floor in (('G', 0.95), ('R', 0.9), ('S', 1.0), ('W', 0.9), ('A', 0.85)):
            hit, miss = stats[(cat, True)], stats[(cat, False)]
            self.assertGreaterEqual(hit / (hit + miss), floor, cat)

    def test_decoded_icon_has_transparent_corners_and_an_opaque_centre(self):
        sprite = self.icons[self.icon('G:9926')]
        page = atlas.read_page(GAME / self.build.ATLAS_PAGES, sprite.page)
        crop = page[sprite.y:sprite.y + sprite.h, sprite.x:sprite.x + sprite.w]
        self.assertEqual(0, int(crop[2:8, 2:8, 3].max()))
        self.assertGreater(int(crop[sprite.h // 2 - 10:sprite.h // 2 + 10, sprite.w // 2 - 10:sprite.w // 2 + 10, 3].mean()), 200)


if __name__ == '__main__':
    unittest.main()
