"""Tests for the sprite pipeline in art/.

The PNGs under skins/ are build output, checked in so the pet runs without a
build step. These tests keep them honest: every skin validates (16x16, no
unknown palette keys, contiguous frame indices, every required animation),
and what is on disk is exactly what the generator draws today.
"""

import os
import struct
import sys
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "art"))

import generate_sprites as gen  # noqa: E402


def read_png_rgba(path):
    """Decode the 8-bit RGBA, filter-0 PNGs pixelart writes."""
    with open(path, "rb") as handle:
        data = handle.read()
    pos = 8
    width = height = None
    idat = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4 + 1
    rows = [raw[y * stride + 1:(y + 1) * stride] for y in range(height)]
    return width, height, b"".join(rows)


class TestSkins(unittest.TestCase):
    def test_every_skin_validates(self):
        for skin in gen.MODULES:
            module, frames = gen.frame_set(skin)
            self.assertEqual(gen.validate(skin, module, frames), [], skin)

    def test_pngs_on_disk_match_the_generator(self):
        for skin in gen.MODULES:
            module, frames = gen.frame_set(skin)
            palette = gen.palette_for(skin, module)
            skin_dir = os.path.join(gen.SKINS_DIR, skin)
            on_disk = {f[:-4] for f in os.listdir(skin_dir) if f.endswith(".png")}
            self.assertEqual(on_disk, set(frames),
                             "%s: run python3 art/generate_sprites.py" % skin)
            for name, sprite in frames.items():
                w, h, rgba = read_png_rgba(os.path.join(skin_dir, name + ".png"))
                self.assertEqual((w, h), (16, 16), name)
                self.assertEqual(rgba, sprite.to_rgba(palette),
                                 "%s/%s is stale: regenerate" % (skin, name))

    def test_skins_stand_on_the_ground(self):
        # walkers' feet (or a hovering bot's flame) reach the bottom rows
        for skin in ("cat", "shiba", "ultron"):
            _module, frames = gen.frame_set(skin)
            for name in ("sit_0", "walk_0", "walk_1", "run_0"):
                box = frames[name].box()
                self.assertGreaterEqual(box[3], 14, "%s/%s floats" % (skin, name))


if __name__ == "__main__":
    unittest.main()
