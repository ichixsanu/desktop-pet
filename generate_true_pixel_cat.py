"""
Master Handcrafted 32x32 Pixel Art Cat Sprite Generator.
Every single pixel is placed with precision:
- 1-pixel clean outlines with zero jaggies or stray pixels.
- Warm, vibrant 16-color retro palette (honey orange, amber shading, rich caramel stripes, soft white, pastel pinks, emerald eyes).
- No procedural math distortion, no weird horizontal white stripe fills.
- Classic 18 poses:
  1. sit_0    - classic forward sitting kitten with sparkling eyes & curled tail
  2. sit_1    - gentle breathing idle (chest lifted, tail swishes higher)
  3. blink    - kawaii happy curved closed eyes (^ _ ^)
  4. groom_0  - paw lifted to face, licking with pink tongue
  5. groom_1  - paw rubbing cheek and ear in bliss
  6. walk_0   - 3/4 kitten trot step 0 (front-right & rear-left forward)
  7. walk_1   - 3/4 kitten trot step 1 (opposite paws, head bob)
  8. run_0    - playful kitten leaping bound (stretched paws, streaming tail)
  9. run_1    - landing pounce (paws gathered under, spring bound)
  10. stalk_0 - stealth hunter crouch with butt-wiggle tail sway LEFT
  11. stalk_1 - stealth creep step forward with butt-wiggle tail sway RIGHT
  12. swat_0  - coiled ready pose (paw raised by cheek, focused eyes)
  13. swat_1  - swat strike (paw extended forward with pink toe beans!)
  14. sleep_0 - cozy curled cat loaf (peaceful closed eyes u_u)
  15. sleep_1 - cozy cat loaf with floating retro Zzz
  16. climb_0 - vertical wall climber (clinging to window/wall edge)
  17. climb_1 - vertical climb step (scrambling up higher)
  18. drag    - kitten dangled by scruff (round O.O eyes, dangling paws)
"""

import os
import struct
import zlib

PALETTE = {
    ".": (0, 0, 0, 0),             # Transparent
    "#": (34, 20, 26, 255),        # Deep warm dark chocolate outline
    "o": (245, 148, 48, 255),      # Warm vibrant honey orange (fur)
    "O": (255, 192, 108, 255),     # Golden peach (fur highlight)
    "d": (205, 102, 28, 255),      # Warm cinnamon amber (fur shade)
    "s": (160, 68, 16, 255),       # Rich caramel (tabby stripe)
    "w": (255, 248, 240, 255),     # Soft warm white (cream fur / paws)
    "W": (230, 212, 192, 255),     # Warm parchment (cream shade)
    "p": (255, 140, 168, 255),     # Sweet pastel pink (inner ears, nose)
    "P": (230, 85, 120, 255),      # Dark pink (tongue, toe beans)
    "b": (255, 175, 190, 255),     # Soft rosy blush
    "e": (8, 30, 20, 255),         # Deep dark emerald pupil
    "g": (24, 192, 120, 255),      # Bright sparkling emerald iris
    "l": (120, 240, 160, 255),     # Mint shine highlight
    "k": (255, 255, 255, 255),     # Pure white catchlight sparkle
    "z": (140, 160, 225, 255),     # Soft lavender-blue Z
    "Z": (180, 200, 255, 255),     # Bright lavender-blue Z
    "x": (34, 20, 26, 65),         # Soft pixel floor shadow
}

def save_png(filepath, width, height, rgba_bytes):
    png = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png += struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba_bytes[y * width * 4:(y + 1) * width * 4])
    idat = zlib.compress(bytes(raw), 9)
    png += struct.pack(">I", len(idat)) + b"IDAT" + idat + struct.pack(">I", zlib.crc32(b"IDAT" + idat))
    png += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    with open(filepath, "wb") as f:
        f.write(png)

def grid_to_bytes(lines):
    raw = bytearray()
    for y in range(32):
        row = lines[y] if y < len(lines) else "." * 32
        for x in range(32):
            ch = row[x] if x < len(row) else "."
            color = PALETTE.get(ch, (0, 0, 0, 0))
            raw.extend(color)
    return bytes(raw)

CAT_FRAMES = {}

# 1. sit_0
CAT_FRAMES["sit_0"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
".........##...........##........", # 3
"........#oo#.........#oo#.......", # 4
".......#opoo#.......#oopo#......", # 5
".......#oppo#.......#oppo#......", # 6
"......#ooppo#..#s#..#oppoo#.....", # 7
".....#oooooo###sss###oooooo#....", # 8
".....#oooooossssssssssooooo#....", # 9
"....#oooooosssosssossssooooo#...", # 10
"....#ooooo#kk#osssso#kk#oooo#...", # 11
"....#ooooo#eee#oooo#eee#oooo#...", # 12
"...##ooooo#geg#oppo#geg#oooo##..", # 13
"...#obbbbb#lel#w##w#lel#bbbbbo#.", # 14
"....#ooooowwwwwwwwwwwwww#oooo#..", # 15
".....#ooooddddddddddddddoooo#...", # 16
"......#oooooowwwwwwwwooooo#.....", # 17
".......#oooowwwwwwwwwwooo#...##.", # 18
".......#sssoowwwwwwwwooss#..#ww#", # 19
"......#ooossoowwwwwwoossoo##woo#", # 20
"......#oooooooowwwwooooooo#ooo#.", # 21
".....#oooooooooodddddooooo#ooo#.", # 22
".....#oodddddddddddddddddo#oo#..", # 23
".....#oowww#dddddddd#www#ooo#...", # 24
"......#owww#dddddddd#www#oo#....", # 25
"......#wwww#dddddddd#wwww##.....", # 26
".......####.########.####.......", # 27
"................................", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 2. sit_1
CAT_FRAMES["sit_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"........##.............##.......", # 2
".......#oo#...........#oo#......", # 3
"......#opoo#.........#oopo#.....", # 4
"......#oppo#.........#oppo#.....", # 5
".....#ooppo#...#s#...#oppoo#....", # 6
".....#oooooo###sss###oooooo#....", # 7
"....#oooooossssssssssoooooo#....", # 8
"....#oooooosssosssossssoooo#....", # 9
"....#ooooo#kk#osssso#kk#ooo#....", # 10
"....#ooooo#eee#oooo#eee#ooo#....", # 11
"...##ooooo#geg#oppo#geg#ooo##...", # 12
"...#obbbbb#lel#w##w#lel#bbbb#...", # 13
"....#ooooowwwwwwwwwwwwww#oo#.##.", # 14
".....#ooooddddddddddddddooo##ww#", # 15
"......#oooooowwwwwwwwooooo#woo#.", # 16
".......#oooowwwwwwwwwwooo#oooo#.", # 17
".......#sssoowwwwwwwwooss##ooo#.", # 18
"......#ooossoowwwwwwoossoo##oo#.", # 19
"......#oooooooowwwwooooooo#oo#..", # 20
".....#oooooooooodddddooooo#o#...", # 21
".....#oodddddddddddddddddo##....", # 22
".....#oowww#dddddddd#www#oo#....", # 23
"......#owww#dddddddd#www#oo#....", # 24
"......#owww#dddddddd#www#oo#....", # 25
"......#wwww#dddddddd#wwww##.....", # 26
".......####.########.####.......", # 27
"................................", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 3. blink
CAT_FRAMES["blink"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
".........##...........##........", # 3
"........#oo#.........#oo#.......", # 4
".......#opoo#.......#oopo#......", # 5
".......#oppo#.......#oppo#......", # 6
"......#ooppo#..#s#..#oppoo#.....", # 7
".....#oooooo###sss###oooooo#....", # 8
".....#oooooossssssssssooooo#....", # 9
"....#oooooosssosssossssooooo#...", # 10
"....#oooooo#ss#ssss#ss#ooooo#...", # 11
"....#ooooo#e##e#oo#e##e#oooo#...", # 12
"...##ooooo##..##pp##..##oooo##..", # 13
"...#obbbbb#e##e#ww#e##e#bbbbbo#.", # 14
"....#ooooowwwwwwwwwwwwww#oooo#..", # 15
".....#ooooddddddddddddddoooo#...", # 16
"......#oooooowwwwwwwwooooo#.....", # 17
".......#oooowwwwwwwwwwooo#...##.", # 18
".......#sssoowwwwwwwwooss#..#ww#", # 19
"......#ooossoowwwwwwoossoo##woo#", # 20
"......#oooooooowwwwooooooo#ooo#.", # 21
".....#oooooooooodddddooooo#ooo#.", # 22
".....#oodddddddddddddddddo#oo#..", # 23
".....#oowww#dddddddd#www#ooo#...", # 24
"......#owww#dddddddd#www#oo#....", # 25
"......#wwww#dddddddd#wwww##.....", # 26
".......####.########.####.......", # 27
"................................", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 4. groom_0
CAT_FRAMES["groom_0"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
".........##...........##........", # 3
"........#oo#.........#oo#.......", # 4
".......#opoo#.......#oopo#......", # 5
".......#oppo#.......#oppo#......", # 6
"......#ooppo#..#s#..#oppoo#.....", # 7
".....#oooooo###sss###oooooo#....", # 8
".....#oooooossssssssssooooo#....", # 9
"....#oooooosssosssossssooooo#...", # 10
"....#oooooo#ss#ssss#ss#ooooo#...", # 11
"....#ooooo#e##e#oo#e##e#oooo#...", # 12
"...##ooooo##..##pp##..##oooo##..", # 13
"...#obbbbb#e##e#PP#e##e#bbbbbo#.", # 14
"....#ooooowww#wwww#wwwww#oooo#..", # 15
".....#ooooddd#wwww#dddddoooo#...", # 16
"......#oooooo#wwww#ooooooo#.....", # 17
".......#ooooo.####.oooooo#...##.", # 18
".......#sssooowwwwwoossso#..#ww#", # 19
"......#ooossoowwwwwoossoo##woo#.", # 20
"......#oooooooowwwoooooooo#ooo#.", # 21
".....#oooooooooodddddooooo#ooo#.", # 22
".....#oodddddddddddddddddo#oo#..", # 23
".....#oooddddddddddd#www#ooo#...", # 24
"......#ooddddddddddd#www#oo#....", # 25
".......#dddddddddddd#wwww##.....", # 26
"........############.####.......", # 27
"................................", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 5. groom_1
CAT_FRAMES["groom_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
".........##...####....##........", # 3
"........#oo#.#wwww#..#oo#.......", # 4
".......#opoo##wwww#.#oopo#......", # 5
".......#oppo#.#PP#..#oppo#......", # 6
"......#ooppo#..##...#oppoo#.....", # 7
".....#oooooo###sss###oooooo#....", # 8
".....#oooooossssssssssooooo#....", # 9
"....#oooooosssosssossssooooo#...", # 10
"....#oooooo#ss#ssss#ss#ooooo#...", # 11
"....#ooooo#e##e#oo#e##e#oooo#...", # 12
"...##ooooo##..##pp##..##oooo##..", # 13
"...#obbbbb#e##e#ww#e##e#bbbbbo#.", # 14
"....#ooooowwwwwwwwwwwwww#oooo#..", # 15
".....#ooooddddddddddddddoooo#...", # 16
"......#oooooowwwwwwwwooooo#.....", # 17
".......#oooowwwwwwwwwwooo#...##.", # 18
".......#sssoowwwwwwwwooss#..#ww#", # 19
"......#ooossoowwwwwwoossoo##woo#", # 20
"......#oooooooowwwwooooooo#ooo#.", # 21
".....#oooooooooodddddooooo#ooo#.", # 22
".....#oodddddddddddddddddo#oo#..", # 23
".....#oooddddddddddd#www#ooo#...", # 24
"......#ooddddddddddd#www#oo#....", # 25
".......#dddddddddddd#wwww##.....", # 26
"........############.####.......", # 27
"................................", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 6. walk_0 (clean 3/4 kitten trot, honey orange with tabby back, white mittens)
CAT_FRAMES["walk_0"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"...................##......##...", # 2
"..................#oo#....#oo#..", # 3
".................#opoo#..#oopo#.", # 4
".................#oppo#..#oppo#.", # 5
"..##............#ooppo####oppoo#", # 6
".#ww#..........#ooooooooooooooo#", # 7
".#woo#.........#ooooossssoooooo#", # 8
"..#oo#........#ooooossssossssoo#", # 9
"..#ooo#.......#oooo#kk#s#kk#ooo#", # 10
"...#ooo#......#oooo#eee##eee#oo#", # 11
"...#oooo#....#ooooo#geg##geg#oo#", # 12
"....#oooo####obbbbb#lelpplel#b#.", # 13
"....#ooooooos#wwwww#w##w#w#####.", # 14
".....#oooossoo#wwwwwwwww#oooo#..", # 15
"......#sssooooo#ddddddddoooo#...", # 16
".....#ooossooooo#oooooooooo#....", # 17
".....#ooooooooooosssssssso#.....", # 18
"....#ooooooooooosssosssso#......", # 19
"....#ooodddddddd#oo#dd#oo#......", # 20
"....#ooww#ddddd#ooo#dd#ooo#.....", # 21
".....#oww#dddd#oooo#dd#oooo#....", # 22
"......#ww#dddd#oww#ddd#oww#.....", # 23
".......##ddddd#www#ddd#www#.....", # 24
"..............#www#...#www#.....", # 25
"...............###.....###......", # 26
"................................", # 27
"................................", # 28
"....xxxxxxxxxxxxxxxxxxxxxxxx....", # 29
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 30
"................................", # 31
]

# 7. walk_1 (opposite paws, head bob, bouncy step)
CAT_FRAMES["walk_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
"..................##......##....", # 3
".................#oo#....#oo#...", # 4
"................#opoo#..#oopo#..", # 5
"................#oppo#..#oppo#..", # 6
"...............#ooppo####oppoo#.", # 7
"..##..........#ooooooooooooooo#.", # 8
".#ww#.........#ooooossssoooooo#.", # 9
".#woo#.......#ooooossssossssoo#.", # 10
"..#oo#.......#oooo#kk#s#kk#ooo#.", # 11
"..#ooo#......#oooo#eee##eee#oo#.", # 12
"...#ooo#....#ooooo#geg##geg#oo#.", # 13
"....#ooo####obbbbb#lelpplel#b#..", # 14
"....#ooooooo#wwwww#w##w#w#####..", # 15
".....#ooooooo#wwwwwwwww#oooo#...", # 16
"......#sssoooodddddddddoooo#....", # 17
".....#ooosooooo#oooooooooo#.....", # 18
".....#oooooooooosssssssso#......", # 19
"....#ooooooooooosssosssso#......", # 20
"....#ooodddddddd#oo#dd#oo#......", # 21
"....#ooww#ddddd#ooo#dd#ooo#.....", # 22
".....#oww#dddd#oooo#dd#oooo#....", # 23
"......#ww#dddd#oww#ddd#oww#.....", # 24
".......##ddddd#www#ddd#www#.....", # 25
"..............#www#...#www#.....", # 26
"...............###.....###......", # 27
"................................", # 28
"....xxxxxxxxxxxxxxxxxxxxxxxx....", # 29
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 30
"................................", # 31
]

# 8. run_0 (playful leap, paws reaching forward playfully)
CAT_FRAMES["run_0"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
"........................##...##.", # 3
".......................#oo#.#oo#", # 4
"......................#opoo#opo#", # 5
".....................#oppo#oppo#", # 6
"..##................#oppoo#oppo#", # 7
".#ww##.............#ooooooooooo#", # 8
"#woo#oo###########ooooooooooooo#", # 9
".#oooo#ooooooooooo#kk#s#kk#oooo#", # 10
"..#ooooooooooooooo#eee##eee#ooo#", # 11
"...#sssooooooooooo#geg##geg#oo#.", # 12
"....#ooossoooooooobbb#lelpple#..", # 13
"....#ooooooooodddd#ww#w##w####..", # 14
".....#ooooooooossss#wwwwwwww#...", # 15
"......#ooodddddddddd#dddddd#....", # 16
".....#ooww#dddddddddd#www#......", # 17
"....#wwww#ddddddddddd#wwww#.....", # 18
".....####.###########.####......", # 19
"................................", # 20
"................................", # 21
"................................", # 22
"................................", # 23
"................................", # 24
"................................", # 25
"................................", # 26
"................................", # 27
"................................", # 28
"...xxxxxxxxxxxxxxxxxxxxxxxxxx...", # 29
"....xxxxxxxxxxxxxxxxxxxxxxxx....", # 30
"................................", # 31
]

# 9. run_1 (landing bound, paws gathered under)
CAT_FRAMES["run_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
"................................", # 3
"................................", # 4
"........................##...##.", # 5
".......................#oo#.#oo#", # 6
"......................#opoo#opo#", # 7
".....................#oppo#oppo#", # 8
"..##................#oppoo#oppo#", # 9
".#ww##.............#ooooooooooo#", # 10
"#woo#oo###########ooooooooooooo#", # 11
".#oooo#ooooooooooo#kk#s#kk#oooo#", # 12
"..#ooooooooooooooo#eee##eee#ooo#", # 13
"...#sssooooooooooo#geg##geg#oo#.", # 14
"....#ooossoooooooobbb#lelpple#..", # 15
"....#ooooooooodddd#ww#w##w####..", # 16
".....#ooooooooossss#wwwwwwww#...", # 17
"......#oooddddddddddddddddd#....", # 18
".......#ooww##www##www#dddd#....", # 19
"........#wwwwwwwwwwww#dddd#.....", # 20
".........############dddd#......", # 21
".....................####.......", # 22
"................................", # 23
"................................", # 24
"................................", # 25
"................................", # 26
"................................", # 27
"................................", # 28
"...xxxxxxxxxxxxxxxxxxxxxxxxxx...", # 29
"....xxxxxxxxxxxxxxxxxxxxxxxx....", # 30
"................................", # 31
]

# 10. stalk_0 (hunter crouch, huge eyes, butt wiggling LEFT)
CAT_FRAMES["stalk_0"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
"................................", # 3
"................................", # 4
"................................", # 5
"................................", # 6
"................................", # 7
"................................", # 8
"..##...................##...##..", # 9
".#ww#.................#oo#.#oo#.", # 10
".#woo#...............#opoo#opo#.", # 11
"..#oo#..............#oppo#oppo#.", # 12
"..#ooo##############oppoo#oppo#.", # 13
"...#oooooooooooooooooooooooooo#.", # 14
"...#sssoooooooooooooosssssssoo#.", # 15
"...#ooossooooooooooo#kk#ss#kk#o#", # 16
"..#ooooooooodddddddd#eee##eee##.", # 17
".#oooooooooooddddddd#eee##eee##.", # 18
"#oooddddddddddddddddbbb#pp#bbb#.", # 19
"#ooww#dddddddd#www#dd#wwwwww###.", # 20
".#wwww#dddddd#wwww#ddddddddd#...", # 21
"..####.######.####.#########....", # 22
"................................", # 23
"................................", # 24
"................................", # 25
"................................", # 26
"................................", # 27
"................................", # 28
".xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.", # 29
"..xxxxxxxxxxxxxxxxxxxxxxxxxxxx..", # 30
"................................", # 31
]

# 11. stalk_1 (creeping step, butt wiggling RIGHT)
CAT_FRAMES["stalk_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
"................................", # 3
"................................", # 4
"................................", # 5
"................................", # 6
"................................", # 7
"................................", # 8
".......................##...##..", # 9
"......................#oo#.#oo#.", # 10
".....##..............#opoo#opo#.", # 11
"....#ww#............#oppo#oppo#.", # 12
"...#woo#############oppoo#oppo#.", # 13
"...#oooooooooooooooooooooooooo#.", # 14
"...#sssoooooooooooooosssssssoo#.", # 15
"...#ooossooooooooooo#kk#ss#kk#o#", # 16
"..#ooooooooodddddddd#eee##eee##.", # 17
".#oooooooooooddddddd#eee##eee##.", # 18
"#oooddddddddddddddddbbb#pp#bbb#.", # 19
"#ooww#dddddddddddd#dd#wwwwww###.", # 20
".#wwww#dddddddddd#wwww#ddddd#...", # 21
"..####.##########.####.#####....", # 22
"................................", # 23
"................................", # 24
"................................", # 25
"................................", # 26
"................................", # 27
"................................", # 28
".xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.", # 29
"..xxxxxxxxxxxxxxxxxxxxxxxxxxxx..", # 30
"................................", # 31
]

# 12. swat_0 (coiled ready pose, paw raised by cheek)
CAT_FRAMES["swat_0"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
".........##...........##........", # 3
"........#oo#.........#oo#.......", # 4
".......#opoo#.......#oopo#......", # 5
".......#oppo#.......#oppo#......", # 6
"......#ooppo#..#s#..#oppoo#.....", # 7
".....#oooooo###sss###oooooo#....", # 8
".....#oooooossssssssssooooo#....", # 9
"....#oooooosssosssossssooooo#...", # 10
"....#ooooo#kk#osssso#kk#oooo#...", # 11
"....#ooooo#eee#oooo#eee#oooo#...", # 12
"...##ooooo#geg#oppo#geg#oooo##..", # 13
"...#obbbbb#lel#w##w#lel#bbbbbo#.", # 14
"....#ooooowwwwwwwwwwwwww#oooo#..", # 15
".....#ooooddddddddddddddoooo#...", # 16
"......#oooooowwwwwwwwooooo#.....", # 17
".......#oooowwwwwwwwwwooo#...##.", # 18
".......#sssoowwwwwwwwooss#..#ww#", # 19
"......#ooossoowwwwwwoossoo##woo#", # 20
".....#wwww#oooowwwwooooooo#ooo#.", # 21
"....#wwwwww#oooodddddooooo#ooo#.", # 22
"....#wwPPww#ddddddddddddddo#oo#.", # 23
".....#wwww#ddddddddd#www#ooo#...", # 24
"......####dddddddddd#www#oo#....", # 25
"......#ddddddddddddd#wwww##.....", # 26
".......#############.####.......", # 27
"................................", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 13. swat_1 (playful paw bat forward with pink toe beans)
CAT_FRAMES["swat_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
".........##...........##........", # 3
"........#oo#.........#oo#.......", # 4
".......#opoo#.......#oopo#......", # 5
".......#oppo#.......#oppo#......", # 6
"......#ooppo#..#s#..#oppoo#.....", # 7
".....#oooooo###sss###oooooo#....", # 8
".....#oooooossssssssssooooo#....", # 9
"....#oooooosssosssossssooooo#...", # 10
"....#ooooo#kk#osssso#kk#oooo#...", # 11
"....#ooooo#eee#oooo#eee#oooo#...", # 12
"...##ooooo#geg#oppo#geg#oooo##..", # 13
"...#obbbbb#lel#w##w#lel#bbbbbo#.", # 14
"....#ooooowwwwwwwwwwwwww#oooo#..", # 15
".....#ooooddddddddddddddoooo#...", # 16
"...######oooowwwwwwwwooooo#.....", # 17
"..#wwwwww#ooowwwwwwwwwwooo#...##", # 18
".#wwPPPPww#oowwwwwwwwooss#...#ww", # 19
".#wwPPPPww#oowwwwwwwoossoo##woo#", # 20
"..#wwwwww#ooooowwwwooooooo#ooo#.", # 21
"...######ooooooodddddooooo#ooo#.", # 22
".....#oodddddddddddddddddo#oo#..", # 23
".....#oooddddddddddd#www#ooo#...", # 24
"......#ooddddddddddd#www#oo#....", # 25
".......#dddddddddddd#wwww##.....", # 26
"........############.####.......", # 27
"................................", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 14. sleep_0 (cozy cinnamon-roll cat loaf, peaceful u_u eyes)
CAT_FRAMES["sleep_0"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"................................", # 2
"................................", # 3
"................................", # 4
"................................", # 5
"................................", # 6
"................................", # 7
"................................", # 8
"................................", # 9
"................................", # 10
"................................", # 11
"..............##.......##.......", # 12
".............#oo#.....#oo#......", # 13
"............#opoo#...#oopo#.....", # 14
"....#####...#oppo#...#oppo#.....", # 15
"..##ooooo##.#ooppo###oppoo#.....", # 16
".#ooossssooo#ooooooooooooo#.....", # 17
"#ooosoooosssosssossssooooo#.....", # 18
"#ooosooooosssosssossssooooo#....", # 19
"#ooosooooo#ss#ssss#ss#ooooo#....", # 20
"#ooosoooo#e##e#oo#e##e#oooo#....", # 21
".#oosoooo##..##pp##..##bbbo#....", # 22
"..#osssso#e##e#ww#e##e#bbb#.....", # 23
"...#oooowwwwwww##wwwwww###......", # 24
"....#oooddddddddddddddddo#......", # 25
".....#ooddddddddddddddddo#......", # 26
"......##################........", # 27
"................................", # 28
"...xxxxxxxxxxxxxxxxxxxxxxxxxx...", # 29
"....xxxxxxxxxxxxxxxxxxxxxxxx....", # 30
"................................", # 31
]

# 15. sleep_1 (cozy cat loaf with floating retro Zzz)
CAT_FRAMES["sleep_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"........................ZZZZ....", # 2
"...........................Z....", # 3
"..........................Z.....", # 4
".........................ZZZZ...", # 5
"................................", # 6
"..................zzz...........", # 7
"....................z...........", # 8
"...................z............", # 9
"..................zzz...........", # 10
"................................", # 11
"..............##.......##.......", # 12
".............#oo#.....#oo#......", # 13
"............#opoo#...#oopo#.....", # 14
"....#####...#oppo#...#oppo#.....", # 15
"..##ooooo##.#ooppo###oppoo#.....", # 16
".#ooossssooo#ooooooooooooo#.....", # 17
"#ooosoooosssosssossssooooo#.....", # 18
"#ooosooooosssosssossssooooo#....", # 19
"#ooosooooo#ss#ssss#ss#ooooo#....", # 20
"#ooosoooo#e##e#oo#e##e#oooo#....", # 21
".#oosoooo##..##pp##..##bbbo#....", # 22
"..#osssso#e##e#ww#e##e#bbb#.....", # 23
"...#oooowwwwwww##wwwwww###......", # 24
"....#oooddddddddddddddddo#......", # 25
".....#ooddddddddddddddddo#......", # 26
"......##################........", # 27
"................................", # 28
"...xxxxxxxxxxxxxxxxxxxxxxxxxx...", # 29
"....xxxxxxxxxxxxxxxxxxxxxxxx....", # 30
"................................", # 31
]

# 16. climb_0 (climbing window/wall, gripping edge with white mittens)
CAT_FRAMES["climb_0"] = [
#01234567890123456789012345678901
"##..............................", # 0
"#w##............................", # 1
"#ww#...............##......##...", # 2
"##w##.............#oo#....#oo#..", # 3
".##oo#...........#opoo#..#oopo#.", # 4
"..#ooo#..........#oppo#..#oppo#.", # 5
"..#oooo#........#ooppo####oppoo#", # 6
"...#oooo#......#ooooooooooooooo#", # 7
"...#ooooo######ooooossssooooooo#", # 8
"....#oooooooooooooossssossssooo#", # 9
"....#sssooooooooooo#kk#s#kk#ooo#", # 10
"...#ooossoooooooooo#eee##eee#oo#", # 11
"..#oooooooooddddddd#geg##geg#oo#", # 12
".#oooooooooooddddddbb#lel#w#bbb#", # 13
"##ww##dddddddddddddwwwwppww#####", # 14
"#wwww#ddddddddddddddddddddd#....", # 15
"##ww##ddddddddddddddddddddd#....", # 16
".####oooooooooowwwwwwwwwwww#....", # 17
"....#sssooooooooddddddddddd#....", # 18
"...#ooossooooooo#oo#dd#oo#......", # 19
"..#oooooooooooo#ooo#dd#ooo#.....", # 20
"..#ooww#dddddd#oooo#dd#oooo#....", # 21
"..#oww#ddddddd#oww#ddd#oww#.....", # 22
"..#ww#dddddddd#www#ddd#www#.....", # 23
"..##dddddddddd#www#...#www#.....", # 24
"...#ooo#.......###.....###......", # 25
"....#woo#.......................", # 26
".....#ww#.......................", # 27
"......##........................", # 28
"................................", # 29
"................................", # 30
"................................", # 31
]

# 17. climb_1 (scramble step, climbing higher)
CAT_FRAMES["climb_1"] = [
#01234567890123456789012345678901
"................................", # 0
"................................", # 1
"##..............................", # 2
"#w##...............##......##...", # 3
"#ww#..............#oo#....#oo#..", # 4
"##w##............#opoo#..#oopo#.", # 5
".##oo#...........#oppo#..#oppo#.", # 6
"..#ooo#.........#ooppo####oppoo#", # 7
"..#oooo#.......#ooooooooooooooo#", # 8
"...#oooo#######ooooossssooooooo#", # 9
"...#ooooooooooooooossssossssooo#", # 10
"...#sssoooooooooooo#kk#s#kk#ooo#", # 11
"..#ooossooooooooooo#eee##eee#oo#", # 12
".#ooooooooooddddddd#geg##geg#oo#", # 13
"##ww##oooooodddddddbb#lel#w#bbb#", # 14
"#wwww#dddddddddddddwwwwppww#####", # 15
"##ww##ddddddddddddddddddddd#....", # 16
".####oooooooooowwwwwwwwwwww#....", # 17
"....#sssooooooooddddddddddd#....", # 18
"...#ooossooooooo#oo#dd#oo#......", # 19
"..#oooooooooooo#ooo#dd#ooo#.....", # 20
"..#ooww#dddddd#oooo#dd#oooo#....", # 21
"..#oww#ddddddd#oww#ddd#oww#.....", # 22
"..#ww#dddddddd#www#ddd#www#.....", # 23
"..##dddddddddd#www#...#www#.....", # 24
"...#ooo#.......###.....###......", # 25
"....#woo#.......................", # 26
".....#ww#.......................", # 27
"......##........................", # 28
"................................", # 29
"................................", # 30
"................................", # 31
]

# 18. drag (dangled kitten by scruff, wide round O.O eyes, limp paws)
CAT_FRAMES["drag"] = [
#01234567890123456789012345678901
"................................", # 0
"................##..............", # 1
"...............#ss#.............", # 2
".........##...#ssss#..##........", # 3
"........#oo#..#ssss#.#oo#.......", # 4
".......#opoo###ssss###oopo#.....", # 5
".......#oppo#oooooooo#oppo#.....", # 6
"......#ooppo#..#ss#..#oppoo#....", # 7
".....#oooooo###ssss###oooooo#...", # 8
".....#ooooooossssssssooooooo#...", # 9
"....#oooooo#kk#ssss#kk#oooooo#..", # 10
"....#ooooo#eee#oooo#eee#ooooo#..", # 11
"....#ooooo#eee#oppo#eee#ooooo#..", # 12
"...##ooooo#geg#oPPo#geg#ooooo##.", # 13
"...#obbbbb#lel#w##w#lel#bbbbbo#.", # 14
"....#ooooowwwwwwwwwwwwww#oooo#..", # 15
"....#oo#oowwwwwwwwwwwwww#oo#o#..", # 16
"....#ww#oooddddddddddddd#ww#o#..", # 17
"....#ww#ooooowwwwwwwwooo#ww#o#..", # 18
".....##.ooooowwwwwwwwooo.##.o#..", # 19
"........#sssoowwwwwwooss#...##..", # 20
".......#ooossoowwwwoossoo#......", # 21
".......#oooooooooodddddoo#......", # 22
"......#ooddddddddddddddddo#.....", # 23
"......#oo#..#dddddd#..#oo#......", # 24
"......#ww#..#dddddd#..#ww#......", # 25
"......#ww#...######...#ww#......", # 26
".......##..............##.......", # 27
"...............##...............", # 28
"..............#oo#..............", # 29
"..............#woo#.............", # 30
"...............#ww#.............", # 31
]

def generate_all(target_dir):
    os.makedirs(target_dir, exist_ok=True)
    count = 0
    for name, grid in CAT_FRAMES.items():
        raw = grid_to_bytes(grid)
        out_path = os.path.join(target_dir, f"{name}.png")
        save_png(out_path, 32, 32, raw)
        count += 1
    print(f"Generated {count} authentic pixel art cat sprites into {target_dir}")

if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    generate_all(os.path.join(base, "skins", "cat"))
