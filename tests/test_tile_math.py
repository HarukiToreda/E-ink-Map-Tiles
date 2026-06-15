import unittest

from eink_map_tiles.cli import BBox, parse_zooms, tiles_for_bbox


class TileMathTests(unittest.TestCase):
    def test_parse_zoom_list_and_ranges(self):
        self.assertEqual(parse_zooms("6-8,10"), [6, 7, 8, 10])

    def test_world_at_zoom_zero_is_one_tile(self):
        tiles = tiles_for_bbox(BBox(west=-180, south=-85, east=180, north=85), [0])
        self.assertEqual([(tile.z, tile.x, tile.y) for tile in tiles], [(0, 0, 0)])

    def test_antimeridian_bbox_splits_without_duplicates(self):
        tiles = tiles_for_bbox(BBox(west=179, south=-1, east=-179, north=1), [2])
        self.assertTrue(tiles)
        self.assertEqual(len(tiles), len({(tile.z, tile.x, tile.y) for tile in tiles}))


if __name__ == "__main__":
    unittest.main()
