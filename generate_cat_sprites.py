"""
Pixel-perfect generator for the cute cat companion sprites.
All sprites are handcrafted 32x32 pixel art.
"""
import os
import struct
import zlib

PALETTE = {
    ".": (0, 0, 0, 0),           # Transparent
    "#": (44, 24, 16, 255),       # Dark Chocolate Outline
    "o": (252, 163, 56, 255),     # Warm Honey Orange (Fur)
    "O": (255, 196, 107, 255),    # Golden Cream (Fur Highlight)
    "d": (217, 120, 32, 255),     # Warm Amber (Fur Shade)
    "s": (175, 80, 20, 255),      # Caramel Tabby Stripe
    "w": (255, 247, 236, 255),    # Soft Cream / White
    "W": (240, 223, 200, 255),    # Cream Shade
    "p": (255, 143, 163, 255),    # Sweet Pink (Nose & Inner Ear)
    "P": (255, 110, 138, 255),    # Dark Pink (Tongue & Toe Beans)
    "b": (255, 179, 193, 255),    # Rosy Blush
    "e": (9, 34, 24, 255),        # Deep Emerald Pupil
    "g": (32, 191, 107, 255),     # Bright Emerald Iris
    "l": (123, 237, 159, 255),    # Mint Highlight
    "k": (255, 255, 255, 255),    # Pure White Catchlight Sparkle
    "z": (140, 160, 220, 255),    # Sleep Z
    "Z": (180, 200, 250, 255),    # Big Sleep Z
    "x": (30, 20, 35, 75),        # Soft Drop Shadow
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
".##..##bbb#lel#w##w#lel#bbb##..#", # 14
".......###wwwwwwwwwwww###.......", # 15
"....#ooooowwwwwwwwwwwwww#ooo#...", # 16
".....#ooooddddddddddddddooo#....", # 17
"......#oooooowwwwwwwwooooo#.....", # 18
".......#oooowwwwwwwwwwooo#...##.", # 19
".......#sssoowwwwwwwwooss#..#ww#", # 20
"......#ooossoowwwwwwoossoo##woo#", # 21
"......#oooooooowwwwooooooo#ooo#.", # 22
".....#oooooooooodddddooooo#ooo#.", # 23
".....#oodddddddddddddddddo#oo#..", # 24
".....#oowww#dddddddd#www#ooo#...", # 25
"......#owww#dddddddd#www#oo#....", # 26
"......#wwww#dddddddd#wwww##.....", # 27
".......####.########.####.......", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 2. sit_1 (gentle breathing bob, tail swishes up, ears tilt)
CAT_FRAMES["sit_1"] = [
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
".##..##bbb#lel#w##w#lel#bbb##..#", # 13
".......###wwwwwwwwwwww###....##.", # 14
"....#ooooowwwwwwwwwwwwww#ooo#ww#", # 15
".....#ooooddddddddddddddooo#woo#", # 16
"......#oooooowwwwwwwwooooo#ooo#.", # 17
".......#oooowwwwwwwwwwooo#oooo#.", # 18
".......#sssoowwwwwwwwooss##ooo#.", # 19
"......#ooossoowwwwwwoossoo##oo#.", # 20
"......#oooooooowwwwooooooo#oo#..", # 21
".....#oooooooooodddddooooo#o#...", # 22
".....#oodddddddddddddddddo##....", # 23
".....#oowww#dddddddd#www#oo#....", # 24
"......#owww#dddddddd#www#oo#....", # 25
"......#owww#dddddddd#www#oo#....", # 26
"......#wwww#dddddddd#wwww##.....", # 27
".......####.########.####.......", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 3. blink (cute happy curved closed eyes ^_^)
CAT_FRAMES["blink"] = [
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
".##..##bbb#e##e#ww#e##e#bbb##..#", # 14
".......###wwwwwwwwwwww###.......", # 15
"....#ooooowwwwwwwwwwwwww#ooo#...", # 16
".....#ooooddddddddddddddooo#....", # 17
"......#oooooowwwwwwwwooooo#.....", # 18
".......#oooowwwwwwwwwwooo#...##.", # 19
".......#sssoowwwwwwwwooss#..#ww#", # 20
"......#ooossoowwwwwwoossoo##woo#", # 21
"......#oooooooowwwwooooooo#ooo#.", # 22
".....#oooooooooodddddooooo#ooo#.", # 23
".....#oodddddddddddddddddo#oo#..", # 24
".....#oowww#dddddddd#www#ooo#...", # 25
"......#owww#dddddddd#www#oo#....", # 26
"......#wwww#dddddddd#wwww##.....", # 27
".......####.########.####.......", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 4. groom_0 (paw lifted to mouth, licking paw with pink tongue)
CAT_FRAMES["groom_0"] = [
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
".##..##bbb#e##e#PP#e##e#bbb##..#", # 14
".......###wwww##ww#www###.......", # 15
"....#ooooowww#wwww#wwwww#ooo#...", # 16
".....#ooooddd#wwww#dddddooo#....", # 17
"......#oooooo#wwww#ooooooo#.....", # 18
".......#ooooo.####.oooooo#...##.", # 19
".......#sssooowwwwwoossso#..#ww#", # 20
"......#ooossoowwwwwoossoo##woo#.", # 21
"......#oooooooowwwoooooooo#ooo#.", # 22
".....#oooooooooodddddooooo#ooo#.", # 23
".....#oodddddddddddddddddo#oo#..", # 24
".....#oooddddddddddd#www#ooo#...", # 25
"......#ooddddddddddd#www#oo#....", # 26
".......#dddddddddddd#wwww##.....", # 27
"........############.####.......", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 5. groom_1 (paw rubbing cheek/ear, blissful face)
CAT_FRAMES["groom_1"] = [
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
".##..##bbb#e##e#ww#e##e#bbb##..#", # 14
".......###wwwwwwwwwwww###.......", # 15
"....#ooooowwwwwwwwwwwwww#ooo#...", # 16
".....#ooooddddddddddddddooo#....", # 17
"......#oooooowwwwwwwwooooo#.....", # 18
".......#oooowwwwwwwwwwooo#...##.", # 19
".......#sssoowwwwwwwwooss#..#ww#", # 20
"......#ooossoowwwwwwoossoo##woo#", # 21
"......#oooooooowwwwooooooo#ooo#.", # 22
".....#oooooooooodddddooooo#ooo#.", # 23
".....#oodddddddddddddddddo#oo#..", # 24
".....#oooddddddddddd#www#ooo#...", # 25
"......#ooddddddddddd#www#oo#....", # 26
".......#dddddddddddd#wwww##.....", # 27
"........############.####.......", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 6. walk_0 (trot frame 0: 4 legs walking, front-right & rear-left forward)
CAT_FRAMES["walk_0"] = [
"................................", # 0
"................................", # 1
"................................", # 2
"...................##......##...", # 3
"..................#oo#....#oo#..", # 4
".................#opoo#..#oopo#.", # 5
".................#oppo#..#oppo#.", # 6
"..##............#ooppo####oppoo#", # 7
".#ww#..........#ooooooooooooooo#", # 8
".#woo#.........#ooooossssoooooo#", # 9
"..#oo#........#ooooossssossssoo#", # 10
"..#ooo#.......#oooo#kk#s#kk#ooo#", # 11
"...#ooo#......#oooo#eee##eee#oo#", # 12
"...#oooo#....#ooooo#geg##geg#oo#", # 13
"....#oooo####bbbbbb#lelpplel#bb#", # 14
"....#oooooooowwwwww##ww##ww####.", # 15
".....#ooooooooddddddddddddd#....", # 16
"......#sssoooowwwwwwwwwwww#.....", # 17
".....#ooossoooddddddddddd#......", # 18
".....#oooooooowwwwwwwwwww#......", # 19
"....#oooooooooodddddddddd#......", # 20
"....#oooddddddd#oo#dd#oo#.......", # 21
"....#ooww#dddd#ooo#dd#ooo#......", # 22
".....#oww#ddd#oooo#dd#oooo#.....", # 23
"......#ww#ddd#oww#ddd#oww#......", # 24
".......##dddd#www#ddd#www#......", # 25
".............#www#...#www#......", # 26
"..............###.....###.......", # 27
"................................", # 28
"....xxxxxxxxxxxxxxxxxxxxxxxx....", # 29
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 30
"................................", # 31
]

# 7. walk_1 (trot frame 1: opposite legs, bouncy step, bob)
CAT_FRAMES["walk_1"] = [
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
"....#ooo####bbbbbb#lelpplel#bb#.", # 14
"....#ooooooowwwwww##ww##ww####..", # 15
".....#oooooooddddddddddddd#.....", # 16
"......#sssooowwwwwwwwwwww#......", # 17
".....#ooosooddddddddddddd#......", # 18
".....#ooooooowwwwwwwwwwww#......", # 19
"....#oooooooooodddddddddd#......", # 20
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

# 8. run_0 (playful pounce/gallop: stretched leap)
CAT_FRAMES["run_0"] = [
"................................", # 0
"................................", # 1
"................................", # 2
"................................", # 3
"................................", # 4
"................................", # 5
"................................", # 6
"........................##...##.", # 7
".......................#oo#.#oo#", # 8
"......................#opoo#opo#", # 9
"..##.................#oppo#oppo#", # 10
".#ww##..............#oppoo#oppo#", # 11
"#woo#oo#...........#ooooooooooo#", # 12
".#oooo#oo#########ooooooooooooo#", # 13
"..#oooo#oooooooooo#kk#s#kk#oooo#", # 14
"...#oooooooooooooo#eee##eee#ooo#", # 15
"....#sssoooooooooo#geg##geg#oo#.", # 16
".....#ooossooooooobbb#lel#bbb#..", # 17
".....#ooooooowwwwwwppw##w#####..", # 18
"....#ooooooooowwwwwwwwwwwwww#...", # 19
"...#oooddddddddddddddddddddd#...", # 20
"..#ooww#dddddddd#www#dd#www#....", # 21
".#wwww#dddddddd#wwww#dd#wwww#...", # 22
".####.#########.####...####.....", # 23
"................................", # 24
"................................", # 25
"................................", # 26
"................................", # 27
"................................", # 28
"..xxxxxxxxxxxxxxxxxxxxxxxxxxxx..", # 29
"...xxxxxxxxxxxxxxxxxxxxxxxxxx...", # 30
"................................", # 31
]

# 9. run_1 (tucked mid-leap bound)
CAT_FRAMES["run_1"] = [
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
"....#ooossoooooooobbb#lel#bbb#..", # 15
"....#oooooooowwwwwwppw##w#####..", # 16
".....#oooooooowwwwwwwwwwwwww#...", # 17
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

# 10. stalk_0 (low stealth hunter crouch, big curious eyes, butt wiggling)
CAT_FRAMES["stalk_0"] = [
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
"..##...................##...##..", # 10
".#ww#.................#oo#.#oo#.", # 11
".#woo#...............#opoo#opo#.", # 12
"..#oo#..............#oppo#oppo#.", # 13
"..#ooo##############oppoo#oppo#.", # 14
"...#oooooooooooooooooooooooooo#.", # 15
"...#sssoooooooooooooosssssssoo#.", # 16
"...#ooossooooooooooo#kk#ss#kk#o#", # 17
"..#oooooooowwwwwwwww#eee##eee##.", # 18
".#oooooooooowwwwwwww#eee##eee##.", # 19
"#oooddddddddddddddddbbb#pp#bbb#.", # 20
"#ooww#dddddddd#www#wwwwwwww###..", # 21
".#wwww#dddddd#wwww#ddddddddd#...", # 22
"..####.######.####.#########....", # 23
"................................", # 24
"................................", # 25
"................................", # 26
"................................", # 27
"................................", # 28
".xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.", # 29
"..xxxxxxxxxxxxxxxxxxxxxxxxxxxx..", # 30
"................................", # 31
]

# 11. stalk_1 (stealth creep step forward)
CAT_FRAMES["stalk_1"] = [
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
".......................##...##..", # 10
"......................#oo#.#oo#.", # 11
".....##..............#opoo#opo#.", # 12
"....#ww#............#oppo#oppo#.", # 13
"...#woo#############oppoo#oppo#.", # 14
"...#oooooooooooooooooooooooooo#.", # 15
"...#sssoooooooooooooosssssssoo#.", # 16
"...#ooossooooooooooo#kk#ss#kk#o#", # 17
"..#oooooooowwwwwwwww#eee##eee##.", # 18
".#oooooooooowwwwwwww#eee##eee##.", # 19
"#oooddddddddddddddddbbb#pp#bbb#.", # 20
"#ooww#dddddddddddd#wwwwwwww###..", # 21
".#wwww#dddddddddd#wwww#ddddd#...", # 22
"..####.##########.####.#####....", # 23
"................................", # 24
"................................", # 25
"................................", # 26
"................................", # 27
"................................", # 28
".xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.", # 29
"..xxxxxxxxxxxxxxxxxxxxxxxxxxxx..", # 30
"................................", # 31
]

# 12. swat_0 (sitting back, paw raised coiled ready to swat)
CAT_FRAMES["swat_0"] = [
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
".##..##bbb#lel#w##w#lel#bbb##..#", # 14
".......###wwwwwwwwwwww###.......", # 15
"....#ooooowwwwwwwwwwwwww#ooo#...", # 16
".....#ooooddddddddddddddooo#....", # 17
"......#oooooowwwwwwwwooooo#.....", # 18
".......#oooowwwwwwwwwwooo#...##.", # 19
".......#sssoowwwwwwwwooss#..#ww#", # 20
"......#ooossoowwwwwwoossoo##woo#", # 21
".....#wwww#oooowwwwooooooo#ooo#.", # 22
"....#wwwwww#oooodddddooooo#ooo#.", # 23
"....#wwPPww#ddddddddddddddo#oo#.", # 24
".....#wwww#ddddddddd#www#ooo#...", # 25
"......####dddddddddd#www#oo#....", # 26
"......#ddddddddddddd#wwww##.....", # 27
".......#############.####.......", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 13. swat_1 (playful swat swipe, paw extended with pink toe beans)
CAT_FRAMES["swat_1"] = [
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
".##..##bbb#lel#w##w#lel#bbb##..#", # 14
".......###wwwwwwwwwwww###.......", # 15
"....#ooooowwwwwwwwwwwwww#ooo#...", # 16
".....#ooooddddddddddddddooo#....", # 17
"...######oooowwwwwwwwooooo#.....", # 18
"..#wwwwww#ooowwwwwwwwwwooo#...##", # 19
".#wwPPPPww#oowwwwwwwwooss#...#ww", # 20
".#wwPPPPww#oowwwwwwwoossoo##woo#", # 21
"..#wwwwww#ooooowwwwooooooo#ooo#.", # 22
"...######ooooooodddddooooo#ooo#.", # 23
".....#oodddddddddddddddddo#oo#..", # 24
".....#oooddddddddddd#www#ooo#...", # 25
"......#ooddddddddddd#www#oo#....", # 26
".......#dddddddddddd#wwww##.....", # 27
"........############.####.......", # 28
".....xxxxxxxxxxxxxxxxxxxxxx.....", # 29
"......xxxxxxxxxxxxxxxxxxxx......", # 30
"................................", # 31
]

# 14. sleep_0 (curled cozy loaf, peaceful closed eyes)
CAT_FRAMES["sleep_0"] = [
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
"................................", # 12
"................................", # 13
".............##...........##....", # 14
"............#oo#.........#oo#...", # 15
"...........#opoo#.......#oopo#..", # 16
"....#####..#oppo#.......#oppo#..", # 17
"..##ooooo##ooppo#..#s#..#oppoo#.", # 18
".#ooossssooooooo###sss###oooooo#", # 19
"#ooosoooossssssssssssssssssoooo#", # 20
"#ooosooooosssosssossssoooooo#oo#", # 21
"#ooosooooo#ss#ssss#ss#ooooo#e##e", # 22
"#ooosoooo#e##e#oo#e##e#ooo##..##", # 23
".#oosoooo##..##pp##..##bb##e##e#", # 24
"..#osssso#e##e#ww#e##e#wwww###..", # 25
"...#oooowwwwwwwwwwwwwwwww#......", # 26
"....#oooddddddddddddddddd#......", # 27
".....#wwwwwwwwwwwwwwwwww#.......", # 28
"......##################........", # 29
"..xxxxxxxxxxxxxxxxxxxxxxxxxxxx..", # 30
"...xxxxxxxxxxxxxxxxxxxxxxxxxx...", # 31
]

# 15. sleep_1 (cozy loaf with floating Zzz)
CAT_FRAMES["sleep_1"] = [
"................................", # 0
".......................ZZZZ.....", # 1
"..........................Z.....", # 2
".........................Z......", # 3
"........................ZZZZ....", # 4
"................................", # 5
"..................zzz...........", # 6
"....................z...........", # 7
"...................z............", # 8
"..................zzz...........", # 9
"................................", # 10
"................................", # 11
"................................", # 12
"................................", # 13
".............##...........##....", # 14
"............#oo#.........#oo#...", # 15
"...........#opoo#.......#oopo#..", # 16
"....#####..#oppo#.......#oppo#..", # 17
"..##ooooo##ooppo#..#s#..#oppoo#.", # 18
".#ooossssooooooo###sss###oooooo#", # 19
"#ooosoooossssssssssssssssssoooo#", # 20
"#ooosooooosssosssossssoooooo#oo#", # 21
"#ooosooooo#ss#ssss#ss#ooooo#e##e", # 22
"#ooosoooo#e##e#oo#e##e#ooo##..##", # 23
".#oosoooo##..##pp##..##bb##e##e#", # 24
"..#osssso#e##e#ww#e##e#wwww###..", # 25
"...#oooowwwwwwwwwwwwwwwww#......", # 26
"....#oooddddddddddddddddd#......", # 27
".....#wwwwwwwwwwwwwwwwww#.......", # 28
"......##################........", # 29
"..xxxxxxxxxxxxxxxxxxxxxxxxxxxx..", # 30
"...xxxxxxxxxxxxxxxxxxxxxxxxxx...", # 31
]

# 16. climb_0 (climbing vertical wall, gripping with paws)
CAT_FRAMES["climb_0"] = [
"##..............................", # 0
"#w##............................", # 1
"#ww#............................", # 2
"##w##..............##......##...", # 3
".##oo#............#oo#....#oo#..", # 4
"..#ooo#..........#opoo#..#oopo#.", # 5
"..#oooo#.........#oppo#..#oppo#.", # 6
"...#oooo#.......#ooppo####oppoo#", # 7
"...#ooooo#.....#ooooooooooooooo#", # 8
"....#ooooo#####ooooossssooooooo#", # 9
"....#oooooooooooooossssossssooo#", # 10
"....#sssooooooooooo#kk#s#kk#ooo#", # 11
"...#ooossoooooooooo#eee##eee#oo#", # 12
"..#oooooooowwwwwwww#geg##geg#oo#", # 13
".#oooooooooowwwwwwwbb#lel#w#bbb#", # 14
"##ww##ddddddddddddwwwwppww######", # 15
"#wwww#dddddddddddddddddddd#.....", # 16
"##ww##dddddddddddddddddddd#.....", # 17
".####oooooooooowwwwwwwwwww#.....", # 18
"....#sssoooooooodddddddddd#.....", # 19
"...#ooossooooooo#oo#dd#oo#......", # 20
"..#oooooooooooo#ooo#dd#ooo#.....", # 21
"..#ooww#dddddd#oooo#dd#oooo#....", # 22
"..#oww#ddddddd#oww#ddd#oww#.....", # 23
"..#ww#dddddddd#www#ddd#www#.....", # 24
"..##dddddddddd#www#...#www#.....", # 25
"...#ooo#.......###.....###......", # 26
"....#woo#.......................", # 27
".....#ww#.......................", # 28
"......##........................", # 29
"................................", # 30
"................................", # 31
]

# 17. climb_1 (scramble step climbing higher)
CAT_FRAMES["climb_1"] = [
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
".#ooooooooowwwwwwww#geg##geg#oo#", # 13
"##ww##oooooowwwwwwwbb#lel#w#bbb#", # 14
"#wwww#ddddddddddddwwwwppww######", # 15
"##ww##dddddddddddddddddddd#.....", # 16
".####oooooooooowwwwwwwwwww#.....", # 17
"....#sssoooooooodddddddddd#.....", # 18
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

# 18. drag (kitten dangled by scruff! Round surprised eyes O.O, cute dangling paws)
CAT_FRAMES["drag"] = [
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
".##..##bbb#lel#w##w#lel#bbb##..#", # 14
".......###wwwwwwwwwwww###.......", # 15
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

def generate_cat_skins(target_dir):
    os.makedirs(target_dir, exist_ok=True)
    count = 0
    for name, grid in CAT_FRAMES.items():
        raw = grid_to_bytes(grid)
        out_path = os.path.join(target_dir, f"{name}.png")
        save_png(out_path, 32, 32, raw)
        count += 1
    print(f"Generated {count} cat sprites into {target_dir}")

if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    generate_cat_skins(os.path.join(base, "skins", "cat"))
