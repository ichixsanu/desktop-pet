"""
16x16 Pixel Art Sprite Generator — ALL COMPANIONS.
Shiba Inu, Ghost, Jarvis (AI orb), Ultron (menacing bot).
Every pixel hand-placed. Pure retro pixel art.
"""

import os
import struct
import zlib


# =====================================================================
# PNG WRITER
# =====================================================================

def save_png(filepath, width, height, rgba_bytes):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba_bytes[y * width * 4:(y + 1) * width * 4])
    compressed = zlib.compress(bytes(raw), 9)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc
    with open(filepath, "wb") as f:
        f.write(sig + ihdr + idat + iend)


def grid_to_rgba(lines, palette, size=16):
    raw = bytearray()
    for y in range(size):
        row = lines[y] if y < len(lines) else "." * size
        for x in range(size):
            ch = row[x] if x < len(row) else "."
            r, g, b, a = palette.get(ch, (0, 0, 0, 0))
            raw.extend((r, g, b, a))
    return bytes(raw)


def validate_and_save(name, grid, palette, filepath, size=16):
    errors = []
    if len(grid) != size:
        errors.append(f"expected {size} rows, got {len(grid)}")
    for i, row in enumerate(grid):
        if len(row) != size:
            errors.append(f"row {i}: expected {size} cols, got {len(row)} -> '{row}'")
        for j, ch in enumerate(row):
            if ch not in palette:
                errors.append(f"row {i} col {j}: unknown char '{ch}'")
    if errors:
        print(f"  ✗ {name}: ERRORS")
        for e in errors:
            print(f"      {e}")
        return False
    rgba = grid_to_rgba(grid, palette, size)
    save_png(filepath, size, size, rgba)
    print(f"  ✓ {name}")
    return True


# =====================================================================
# SHIBA INU — Golden tan doge, cream markings, curled tail, derpy face
# =====================================================================

SHIBA_PALETTE = {
    ".": (0, 0, 0, 0),
    "#": (35, 25, 15, 255),       # warm dark outline
    "t": (215, 160, 60, 255),     # golden tan fur
    "T": (240, 195, 105, 255),    # light tan highlight
    "d": (175, 120, 35, 255),     # dark tan shade
    "c": (255, 245, 225, 255),    # cream markings (cheeks, brows)
    "C": (235, 215, 180, 255),    # cream shade
    "w": (255, 250, 245, 255),    # white (chest, paws)
    "n": (25, 20, 15, 255),       # nose/eye black
    "e": (20, 15, 10, 255),       # eye dark
    "k": (255, 255, 255, 255),    # catchlight
    "p": (255, 130, 150, 255),    # tongue pink
    "z": (140, 160, 225, 255),    # zzz
    "Z": (180, 200, 255, 255),    # Zzz bright
}

SHIBA = {}

# sit_0 — sitting doge, facing right, curled tail, happy face
SHIBA["sit_0"] = [
    "................",  # 0
    "....##....##....",  # 1  pointy ears
    "...#tT#..#Tt#...",  # 2
    "...#tttttttt#...",  # 3  head top
    "..#Tttttttttc#..",  # 4  forehead + cream cheek start
    "..#tke#tt#ekc#..",  # 5  eyes with cream cheeks
    "..#tccwnnwcct#..",  # 6  cream face, n=black nose
    "...#tcwwwwct#...",  # 7  white muzzle
    "...#dtttttd#....",  # 8  neck
    "...#ttttttt##...",  # 9  body + tail curls up
    "...#twwwwttt#t#.",  # 10 white chest + curled tail
    "...#twwwwtttt##.",  # 11
    "...#t##tt##tt#..",  # 12 paws
    "....##..##..##..",  # 13
    "................",  # 14
    "................",  # 15
]

# sit_1 — tail wag + slight head tilt
SHIBA["sit_1"] = [
    "................",  # 0
    "...##....##.....",  # 1  head tilted slightly
    "..#tT#..#Tt#....",  # 2
    "..#tttttttt#....",  # 3
    ".#Tttttttttc#...",  # 4
    ".#tke#tt#ekc#...",  # 5
    ".#tccwnnwcct#...",  # 6
    "..#tcwwwwct#....",  # 7
    "..#dtttttttd#...",  # 8
    "..#tttttttt##...",  # 9
    "..#twwwwttt#t#..",  # 10 tail wagging right
    "..#twwwwtttt.#..",  # 11
    "..#t##tt##t#....",  # 12
    "...##..##.##....",  # 13
    "................",  # 14
    "................",  # 15
]

# blink — happy ^_^ eyes, tongue out
SHIBA["blink"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#tT#..#Tt#...",  # 2
    "...#tttttttt#...",  # 3
    "..#Tttttttttc#..",  # 4
    "..#tc.#tt#.cc#..",  # 5  ^_^ eyes
    "..#tccwnnwcct#..",  # 6
    "...#tcwwpwct#...",  # 7  p = tongue sticking out!
    "...#dtttttd#....",  # 8
    "...#ttttttt##...",  # 9
    "...#twwwwttt#t#.",  # 10
    "...#twwwwtttt##.",  # 11
    "...#t##tt##tt#..",  # 12
    "....##..##..##..",  # 13
    "................",  # 14
    "................",  # 15
]

# groom_0 — scratching ear with hind leg
SHIBA["groom_0"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#tT#..#Tt#...",  # 2
    "...#tttttttt#...",  # 3
    "..#Tttttttttc#..",  # 4
    "..#tc.#tt#ekc#..",  # 5  left eye shut (scratching bliss)
    "..#tccwnnwcct#..",  # 6
    "...#tcwwwwct#...",  # 7
    "...#dtttttd##...",  # 8
    "...#ttttttt#t#..",  # 9  hind leg reaching up to ear
    "...#twwwwttt##..",  # 10
    "...#twwwtttt#...",  # 11
    "...#t##tt.#t#...",  # 12 missing a rear paw (it's up)
    "....##..#..##...",  # 13
    "................",  # 14
    "................",  # 15
]

# groom_1 — licking paw
SHIBA["groom_1"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#tT#..#Tt#...",  # 2
    "...#tttttttt#...",  # 3
    "..#Tttttttttc#..",  # 4
    "..#tc.#tt#.cc#..",  # 5  both eyes shut
    ".##ccwnnwcct#...",  # 6  paw to mouth
    ".#w#cwwpwct#....",  # 7  licking paw (p=tongue)
    "..##dtttttd#....",  # 8
    "...#ttttttt##...",  # 9
    "...#twwwwttt#t#.",  # 10
    "...#twwwttttt##.",  # 11
    "....##.tt##tt#..",  # 12
    ".....#.##..##...",  # 13
    "................",  # 14
    "................",  # 15
]

# walk_0 — trotting right, front-R + rear-L forward
SHIBA["walk_0"] = [
    "................",  # 0
    ".....##...##....",  # 1  head forward
    "....#tT#.#Tt#...",  # 2
    "....#tttttttt#..",  # 3
    "...#Ttttttttc#..",  # 4
    "...#tke#t#ekc#..",  # 5
    "...#tccwnwcct#..",  # 6
    "....#cwwwwc#....",  # 7
    "...#dttttttd##..",  # 8  horizontal body + tail
    "...#tttttttt#t#.",  # 9  curled tail up
    "...#twwttttt.##.",  # 10
    "..##.#t#..#t#...",  # 11 legs: alternating gait
    "..#..##...##.#..",  # 12
    "...##.......##..",  # 13
    "................",  # 14
    "................",  # 15
]

# walk_1 — trotting right, opposite legs
SHIBA["walk_1"] = [
    "................",  # 0
    ".....##...##....",  # 1
    "....#tT#.#Tt#...",  # 2
    "....#tttttttt#..",  # 3
    "...#Ttttttttc#..",  # 4
    "...#tke#t#ekc#..",  # 5
    "...#tccwnwcct#..",  # 6
    "....#cwwwwc#....",  # 7
    "...#dttttttd##..",  # 8
    "...#tttttttt#t#.",  # 9
    "...#twwttttt.##.",  # 10
    "...#t#..#t#.##..",  # 11 legs swapped
    "...##.#.##.#.#..",  # 12
    "......##....##..",  # 13
    "................",  # 14
    "................",  # 15
]

# run_0 — ZOOMIES! stretched, airborne, ears back
SHIBA["run_0"] = [
    "................",  # 0
    "................",  # 1
    "......##..##....",  # 2
    ".....#tT#.#t#...",  # 3
    "....#ttttttt#...",  # 4
    "...#tke#t#ekc#..",  # 5
    "...#tccwnwcc#...",  # 6
    "....#cwwwc#.....",  # 7
    "..##dtttttd##...",  # 8  stretched body + tail streaming
    ".#ttwwwtttttt#..",  # 9
    ".#tw#ttttttt#...",  # 10
    "..##.#.....##...",  # 11 legs out = airborne
    "................",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# run_1 — landing, legs gathered
SHIBA["run_1"] = [
    "................",  # 0
    "................",  # 1
    ".....##...##....",  # 2
    "....#tT#.#Tt#...",  # 3
    "....#tttttttt#..",  # 4
    "...#tke#t#ekc#..",  # 5
    "...#tccwnwcct#..",  # 6
    "....#cwwwwc#....",  # 7
    "##..#dttttd#....",  # 8  tail back
    "#tt#twwwtttt#...",  # 9
    ".##twwtttttt#...",  # 10
    "...#t##t##t#....",  # 11 legs gathered
    "....##.##.##....",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# stalk_0 — play bow! front down, butt up, tail wagging left
SHIBA["stalk_0"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "................",  # 3
    "....##...##.....",  # 4
    "...#tT#.#Tt#....",  # 5
    "...#ttttttt#....",  # 6
    "..#tke#t#ekc#...",  # 7  excited eyes
    "..#tccwnwcc#....",  # 8
    "..#wcwwwct#.....",  # 9  front down low
    ".##dtttttttt##..",  # 10 body angled up + tail
    "#tt#wwwttttt#t#.",  # 11 tail wagging
    ".##.#t##t##t.##.",  # 12
    "....##..##.##...",  # 13
    "................",  # 14
    "................",  # 15
]

# stalk_1 — play bow hop, tail right
SHIBA["stalk_1"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "................",  # 3
    "....##...##.....",  # 4
    "...#tT#.#Tt#....",  # 5
    "...#ttttttt#....",  # 6
    "..#tke#t#ekc#...",  # 7
    "..#tccwnwcc#....",  # 8
    "..#wcwwwct#.....",  # 9
    "...#dtttttttt##.",  # 10 tail sways right
    "...#wwwttttt#t#.",  # 11
    "..##.#t#t##..##.",  # 12
    "..#..##..##.....",  # 13
    "................",  # 14
    "................",  # 15
]

# swat_0 — paw raised playfully
SHIBA["swat_0"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#tT#..#Tt#...",  # 2
    "...#tttttttt#...",  # 3
    "..#Tttttttttc#..",  # 4
    "..#tke#tt#ekc#..",  # 5
    "..#tccwnnwcct#..",  # 6
    ".##wcwwwwct#....",  # 7  paw up
    ".#w##dtttd#.....",  # 8
    "..##ttttttt##...",  # 9
    "...#twwwwttt#t#.",  # 10
    "...#twwttttt.##.",  # 11
    "....##.tt##tt#..",  # 12
    ".....#.##..##...",  # 13
    "................",  # 14
    "................",  # 15
]

# swat_1 — boop! paw forward
SHIBA["swat_1"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#tT#..#Tt#...",  # 2
    "...#tttttttt#...",  # 3
    "..#Tttttttttc#..",  # 4
    "..#tke#tt#ekc#..",  # 5
    "..#tccwnnwcct#..",  # 6
    "...#tcwwwwct#...",  # 7
    "##w#dtttttd#....",  # 8  paw EXTENDED far
    ".##ttttttt##....",  # 9
    "...#twwwwttt#t#.",  # 10
    "...#twwttttt.##.",  # 11
    "....##.tt##tt#..",  # 12
    ".....#.##..##...",  # 13
    "................",  # 14
    "................",  # 15
]

# sleep_0 — curled donut, nose tucked into tail
SHIBA["sleep_0"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "................",  # 3
    "................",  # 4
    "................",  # 5
    "..###.....###...",  # 6  ear tips
    ".#tTt#...#tTt#..",  # 7
    ".#tttttttttttt#.",  # 8  round donut
    ".#t.c#ttt#c.tt#.",  # 9  closed eyes
    ".#tccwwnwwcctt#.",  # 10 muzzle + nose
    ".#wwwwwwwwwtttt#",  # 11 white belly + tail wrapping
    ".#ttttttttttttt#",  # 12
    "..##############",  # 13
    "................",  # 14
    "................",  # 15
]

# sleep_1 — same donut + Zzz
SHIBA["sleep_1"] = [
    "................",  # 0
    ".........zzz....",  # 1
    "........z.......",  # 2
    ".......ZZZ......",  # 3
    "......Z.........",  # 4
    "................",  # 5
    "..###.....###...",  # 6
    ".#tTt#...#tTt#..",  # 7
    ".#tttttttttttt#.",  # 8
    ".#t.c#ttt#c.tt#.",  # 9
    ".#tccwwnwwcctt#.",  # 10
    ".#wwwwwwwwwtttt#",  # 11
    ".#ttttttttttttt#",  # 12
    "..##############",  # 13
    "................",  # 14
    "................",  # 15
]

# climb_0 — clinging to wall on left
SHIBA["climb_0"] = [
    "................",  # 0
    "..##............",  # 1
    ".#tT##..........",  # 2
    ".#tttt#.........",  # 3
    "#wtke#c#........",  # 4
    "#wtcncc#........",  # 5
    ".#cwwc#.........",  # 6
    ".#tdtt#.........",  # 7
    "#wtdtt#.........",  # 8
    "#wtttt#.........",  # 9
    ".#tdtt#.........",  # 10
    ".#tttt#.........",  # 11
    "#wtdt#..........",  # 12
    "#wttt#..........",  # 13
    ".###.#..........",  # 14
    ".....#..........",  # 15
]

# climb_1 — opposite grip
SHIBA["climb_1"] = [
    "..##............",  # 0
    ".#tT##..........",  # 1
    ".#tttt#.........",  # 2
    "#wtke#c#........",  # 3
    "#wtcncc#........",  # 4
    ".#cwwc#.........",  # 5
    "#wtdtt#.........",  # 6
    ".#tdt#..........",  # 7
    ".#tttt#.........",  # 8
    "#wtdttt#........",  # 9
    ".#tdtt#.........",  # 10
    ".#tttt#.........",  # 11
    "#wttt#..........",  # 12
    ".###..#.........",  # 13
    "......#.........",  # 14
    "......#.........",  # 15
]

# drag — held by scruff, surprised, legs dangling
SHIBA["drag"] = [
    ".....##.........",  # 0
    "....#tt##.......",  # 1
    "...#tttTt#......",  # 2
    "...#ttttttt#....",  # 3
    "..#Ttttttttc#...",  # 4
    "..#tke#t#ekc#...",  # 5  surprised O.O eyes
    "..#tccwnnwcc#...",  # 6
    "...#tcwwwct#....",  # 7
    "...#dttttttd#...",  # 8
    "...#tttttttt#...",  # 9
    "...#twwwwwtt#...",  # 10
    "...#twwwwwtt#...",  # 11
    "...#w#.w.#w#....",  # 12 dangling paws
    "...##..#..##....",  # 13
    "......#.........",  # 14
    "......#.........",  # 15
]


# =====================================================================
# GHOST — Cute rounded white ghost, wavy hem, dot eyes, O mouth
# =====================================================================

GHOST_PALETTE = {
    ".": (0, 0, 0, 0),
    "#": (30, 30, 60, 255),       # dark navy outline
    "w": (245, 245, 255, 255),    # white body
    "W": (215, 215, 240, 255),    # blue-white shadow
    "e": (30, 30, 70, 255),       # eye dark
    "k": (255, 255, 255, 255),    # catchlight
    "b": (255, 180, 200, 255),    # blush
    "o": (40, 35, 70, 255),       # mouth
    "z": (140, 160, 225, 255),
    "Z": (180, 200, 255, 255),
}

GHOST = {}

# idle_0 — floating, wavy bottom hem
GHOST["idle_0"] = [
    "................",  # 0
    "......####......",  # 1  round top
    "....##wwww##....",  # 2
    "...#wwwwwwww#...",  # 3
    "..#wwwwwwwwww#..",  # 4
    "..#wke#ww#ekw#..",  # 5  dot eyes
    "..#wwwwwwwwww#..",  # 6
    "..#wwwbwwbwww#..",  # 7  blush marks
    "..#wwwwwowwww#..",  # 8  small o mouth
    "..#wwwwwwwwww#..",  # 9
    "..#WWwwwwwwWW#..",  # 10 shadow on sides
    "..#WwwwwwwwwW#..",  # 11
    "..#WwWwwwwWwW#..",  # 12 wavy hem
    "...#.##.##.#....",  # 13 wavy bottom
    "................",  # 14
    "................",  # 15
]

# idle_1 — floating bob (shifted up 1px, hem variation)
GHOST["idle_1"] = [
    "......####......",  # 0
    "....##wwww##....",  # 1
    "...#wwwwwwww#...",  # 2
    "..#wwwwwwwwww#..",  # 3
    "..#wke#ww#ekw#..",  # 4
    "..#wwwwwwwwww#..",  # 5
    "..#wwwbwwbwww#..",  # 6
    "..#wwwwwowwww#..",  # 7
    "..#wwwwwwwwww#..",  # 8
    "..#WWwwwwwwWW#..",  # 9
    "..#WwwwwwwwwW#..",  # 10
    "..#wWwwwwwWww#..",  # 11 different wavy pattern
    "...##.#.#.##....",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# blink — ^_^ eyes
GHOST["blink"] = [
    "................",  # 0
    "......####......",  # 1
    "....##wwww##....",  # 2
    "...#wwwwwwww#...",  # 3
    "..#wwwwwwwwww#..",  # 4
    "..#ww.#ww#.ww#..",  # 5  happy closed ^_^
    "..#wwwwwwwwww#..",  # 6
    "..#wwwbwwbwww#..",  # 7
    "..#wwwwwwwwww#..",  # 8
    "..#wwwwwwwwww#..",  # 9
    "..#WWwwwwwwWW#..",  # 10
    "..#WwwwwwwwwW#..",  # 11
    "..#WwWwwwwWwW#..",  # 12
    "...#.##.##.#....",  # 13
    "................",  # 14
    "................",  # 15
]

# fly_0 — whooshing right, stretched shape
GHOST["fly_0"] = [
    "................",  # 0
    "................",  # 1
    ".......####.....",  # 2  shifted right (moving)
    ".....##wwww##...",  # 3
    "....#wwwwwwww#..",  # 4
    "...#wke#ww#ekw#.",  # 5  wide eyes
    "..#wwwwwwwwwww#.",  # 6
    "..#wwwbwwbwwww#.",  # 7
    "..#Wwwwwowwwww#.",  # 8
    "...#Wwwwwwwww#..",  # 9  trailing shape
    "....#Wwwwwww#...",  # 10
    ".....##www#.....",  # 11
    ".......###......",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# fly_1 — whooshing, other direction of trail
GHOST["fly_1"] = [
    "................",  # 0
    "................",  # 1
    "......####......",  # 2
    "....##wwww##....",  # 3
    "...#wwwwwwww#...",  # 4
    "..#wke#ww#ekw#..",  # 5
    "..#wwwwwwwwww#..",  # 6
    ".#wwwbwwbwwww#..",  # 7
    ".#Wwwwwowwwww#..",  # 8  trailing left
    "..#Wwwwwwwww#...",  # 9
    "...#Wwwwwww#....",  # 10
    "....##www#......",  # 11
    "......###.......",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# spook_0 — BOO! bigger, arms up, mouth wide
GHOST["spook_0"] = [
    "................",  # 0
    ".....####.......",  # 1
    "...##wwww##.....",  # 2
    "..#wwwwwwww#....",  # 3
    ".#wwwwwwwwww#...",  # 4  bigger!
    ".#wke#ww#ekww#..",  # 5
    "#wwwwwwwwwwww#..",  # 6  arms out!
    "#wwwwwwwwwwwww#.",  # 7
    ".#wwww#oo#www#..",  # 8  big O mouth
    "..#wwwwwwwww#...",  # 9
    "..#WWwwwwwWW#...",  # 10
    "..#WwWwwwWwW#...",  # 11
    "...#.##.##.#....",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# pat_0 — being patted, squished, happy
GHOST["pat_0"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "....########....",  # 3  squished flat on top
    "...#wwwwwwww#...",  # 4
    "..#wwwwwwwwww#..",  # 5
    "..#ww.#ww#.ww#..",  # 6  happy closed eyes
    "..#wwwbwwbwww#..",  # 7  extra blush
    "..#wwwwwwwwww#..",  # 8
    "..#wwwwwwwwww#..",  # 9
    "..#WWwwwwwwWW#..",  # 10
    "..#WwWwwwwWwW#..",  # 11
    "...#.##.##.#....",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# pat_1 — patted more, even happier
GHOST["pat_1"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "...##########...",  # 3  very squished
    "..#wwwwwwwwww#..",  # 4
    "..#ww.#ww#.ww#..",  # 5  happy
    "..#wwwbwwbwww#..",  # 6  blushing lots
    "..#wwwwwwwwww#..",  # 7
    "..#wwwwwwwwww#..",  # 8
    "..#WWwwwwwwWW#..",  # 9
    "..#WwWwwwwWwW#..",  # 10
    "...#.##.##.#....",  # 11
    "................",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# sleep_0 — peaceful, closed eyes, no mouth
GHOST["sleep_0"] = [
    "................",  # 0
    "......####......",  # 1
    "....##wwww##....",  # 2
    "...#wwwwwwww#...",  # 3
    "..#wwwwwwwwww#..",  # 4
    "..#ww.#ww#.ww#..",  # 5  closed eyes
    "..#wwwwwwwwww#..",  # 6
    "..#wwwwwwwwww#..",  # 7  no mouth
    "..#wwwwwwwwww#..",  # 8
    "..#wwwwwwwwww#..",  # 9
    "..#WWwwwwwwWW#..",  # 10
    "..#WwwwwwwwwW#..",  # 11
    "..#WwWwwwwWwW#..",  # 12
    "...#.##.##.#....",  # 13
    "................",  # 14
    "................",  # 15
]

# sleep_1 — sleeping with Zzz
GHOST["sleep_1"] = [
    ".........zzz....",  # 0
    "........z.......",  # 1
    ".......ZZZ......",  # 2
    "....##wwww##....",  # 3
    "...#wwwwwwww#...",  # 4
    "..#wwwwwwwwww#..",  # 5
    "..#ww.#ww#.ww#..",  # 6
    "..#wwwwwwwwww#..",  # 7
    "..#wwwwwwwwww#..",  # 8
    "..#wwwwwwwwww#..",  # 9
    "..#WWwwwwwwWW#..",  # 10
    "..#WwwwwwwwwW#..",  # 11
    "..#WwWwwwwWwW#..",  # 12
    "...#.##.##.#....",  # 13
    "................",  # 14
    "................",  # 15
]

# drag — stretched vertically, worried eyes
GHOST["drag"] = [
    "......####......",  # 0
    "....##wwww##....",  # 1
    "...#wwwwwwww#...",  # 2
    "..#wke#ww#ekw#..",  # 3  worried eyes (higher up)
    "..#wwwwwwwwww#..",  # 4
    "..#wwwbwbwwww#..",  # 5  worried blush
    "..#wwww#owwww#..",  # 6  o mouth = worried
    "..#wwwwwwwwww#..",  # 7
    "...#wwwwwwww#...",  # 8  getting narrower (stretched)
    "...#WWwwwwWW#...",  # 9
    "....#Wwwww#.....",  # 10
    "....#WwwwW#.....",  # 11
    ".....#www#......",  # 12  pointy stretched bottom
    "......#w#.......",  # 13
    ".......#........",  # 14
    "................",  # 15
]


# =====================================================================
# JARVIS — Friendly holographic AI orb, blue glow, visor eye
# =====================================================================

JARVIS_PALETTE = {
    ".": (0, 0, 0, 0),
    "#": (20, 40, 80, 255),       # dark blue outline
    "b": (70, 150, 255, 255),     # body blue
    "B": (140, 200, 255, 255),    # body highlight
    "d": (40, 100, 200, 255),     # body dark
    "w": (230, 245, 255, 255),    # white glow
    "e": (15, 30, 60, 255),       # visor dark
    "k": (200, 240, 255, 255),    # visor highlight
    "g": (100, 220, 255, 255),    # glow accent
    "z": (140, 160, 225, 255),
    "Z": (180, 200, 255, 255),
}

JARVIS = {}

# sit_0 — floating orb, gentle glow
JARVIS["sit_0"] = [
    "................",  # 0
    "......####......",  # 1  top of sphere
    "....##bBBb##....",  # 2
    "...#bBBwwBBb#...",  # 3  highlight at top
    "..#bBBwwwwBBb#..",  # 4
    "..#bbBBbbBBbb#..",  # 5
    "..#b##eeee##b#..",  # 6  visor band
    "..#b#ekkkke#b#..",  # 7  visor with glow
    "..#b##eeee##b#..",  # 8
    "..#bbbbbbbbbbb#.",  # 9
    "..#dbbbbbbbbd#..",  # 10
    "...#ddbbbddd#...",  # 11
    "....##dddd##....",  # 12
    "......####......",  # 13
    ".......gg.......",  # 14 glow underneath
    "................",  # 15
]

# sit_1 — pulse animation (glow brighter)
JARVIS["sit_1"] = [
    "................",  # 0
    "......####......",  # 1
    "....##bBBb##....",  # 2
    "...#bBwwwwBb#...",  # 3  brighter highlight
    "..#bBwwwwwwBb#..",  # 4
    "..#bbBBbbBBbb#..",  # 5
    "..#b##eeee##b#..",  # 6
    "..#b#gkkkg#bb#..",  # 7  visor glowing more (g)
    "..#b##eeee##b#..",  # 8
    "..#bbbbbbbbbbb#.",  # 9
    "..#dbbbbbbbbd#..",  # 10
    "...#ddbbbddd#...",  # 11
    "....##dddd##....",  # 12
    "......####......",  # 13
    "......gggg......",  # 14 bigger glow
    "................",  # 15
]

# blink — visor dims/narrows
JARVIS["blink"] = [
    "................",  # 0
    "......####......",  # 1
    "....##bBBb##....",  # 2
    "...#bBBwwBBb#...",  # 3
    "..#bBBwwwwBBb#..",  # 4
    "..#bbBBbbBBbb#..",  # 5
    "..#bbbbbbbbbbb#.",  # 6  visor shrunk
    "..#bb##ee##bbb#.",  # 7  narrow slit = blink
    "..#bbbbbbbbbbb#.",  # 8
    "..#bbbbbbbbbbb#.",  # 9
    "..#dbbbbbbbbd#..",  # 10
    "...#ddbbbddd#...",  # 11
    "....##dddd##....",  # 12
    "......####......",  # 13
    ".......gg.......",  # 14
    "................",  # 15
]

# walk_0 — gliding right, slight tilt
JARVIS["walk_0"] = [
    "................",  # 0
    ".......####.....",  # 1  shifted right (moving)
    ".....##bBBb##...",  # 2
    "....#bBBwwBBb#..",  # 3
    "...#bBwwwwBBb#..",  # 4
    "...#bbBBbbBBb#..",  # 5
    "...#b##eeee##b#.",  # 6
    "...#b#ekkkke#b#.",  # 7
    "...#b##eeee##b#.",  # 8
    "...#bbbbbbbbbb#.",  # 9
    "....#dbbbbbd#...",  # 10
    ".....##ddd##....",  # 11
    ".......###......",  # 12
    "......gg........",  # 13 glow trail
    "................",  # 14
    "................",  # 15
]

# walk_1 — gliding, slight opposite tilt
JARVIS["walk_1"] = [
    "................",  # 0
    "......####......",  # 1
    "....##bBBb##....",  # 2
    "...#bBBwwBBb#...",  # 3
    "..#bBBwwwwBBb#..",  # 4
    "..#bbBBbbBBbb#..",  # 5
    "..#b##eeee##b#..",  # 6
    "..#b#ekkkke#b#..",  # 7
    "..#b##eeee##b#..",  # 8
    "..#bbbbbbbbbbb#.",  # 9
    "...#dbbbbbd#....",  # 10
    "....##ddd##.....",  # 11
    "......###.......",  # 12
    "........gg......",  # 13
    "................",  # 14
    "................",  # 15
]

# run_0 — fast glide with motion streak
JARVIS["run_0"] = [
    "................",  # 0
    "................",  # 1
    "........####....",  # 2  shifted right (fast)
    "......##bBBb##..",  # 3
    ".....#bBwwBBb#..",  # 4
    "....#bbBbbBbb#..",  # 5
    "...##b#eeee#b#..",  # 6
    "..#gg#ekkkke#b#.",  # 7  motion streak glow
    "...##b#eeee#b#..",  # 8
    "....#bbbbbbbbb#.",  # 9
    ".....#dbbbbd#...",  # 10
    "......##dd##....",  # 11
    "................",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# run_1 — fast glide other phase
JARVIS["run_1"] = [
    "................",  # 0
    "................",  # 1
    ".......####.....",  # 2
    ".....##bBBb##...",  # 3
    "....#bBwwBBb#...",  # 4
    "...#bbBbbBbb#...",  # 5
    "..##b#eeee#b#...",  # 6
    ".#gg#ekkkke#b#..",  # 7  streak
    "..##b#eeee#b#...",  # 8
    "...#bbbbbbbb#...",  # 9
    "....#dbbbd#.....",  # 10
    ".....##dd##.....",  # 11
    "................",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# swat_0 — energy pulse charging
JARVIS["swat_0"] = [
    "................",  # 0
    "......####......",  # 1
    "....##bBBb##....",  # 2
    "...#bBBwwBBb#...",  # 3
    "..#bBBwwwwBBb#..",  # 4
    "..#bbBBbbBBbb#..",  # 5
    "..#b##eeee##b#..",  # 6
    "..#b#gkkkg#bb#..",  # 7  visor glowing
    "..#b##eeee##b#..",  # 8
    "..#bbbbbbbbbbb#.",  # 9
    ".##dbbbbbbbbd#..",  # 10 energy extending
    "#gg#ddbbbddd#...",  # 11 glow pulse left
    ".##.##dddd##....",  # 12
    "......####......",  # 13
    "................",  # 14
    "................",  # 15
]

# swat_1 — energy blast!
JARVIS["swat_1"] = [
    "................",  # 0
    "......####......",  # 1
    "....##bBBb##....",  # 2
    "...#bBBwwBBb#...",  # 3
    "..#bBBwwwwBBb#..",  # 4
    "..#bbBBbbBBbb#..",  # 5
    "..#b##eeee##b#..",  # 6
    "..#b#gkwkg#bb#..",  # 7  visor max glow
    "..#b##eeee##b#..",  # 8
    "..#bbbbbbbbbbb#.",  # 9
    "..#dbbbbbbbbd#..",  # 10
    "...#ddbbbddd#...",  # 11
    "....##dddd##....",  # 12
    "......####......",  # 13
    "#gggggggg.......",  # 14 blast beam!
    "................",  # 15
]

# sleep_0 — powered down, dim
JARVIS["sleep_0"] = [
    "................",  # 0
    "......####......",  # 1
    "....##bddb##....",  # 2  dimmer colors
    "...#bdddddddb#..",  # 3
    "..#bddddddddb#..",  # 4
    "..#bdddddddddb#.",  # 5
    "..#bd##ddd##db#.",  # 6
    "..#bd#eddde#db#.",  # 7  dim visor
    "..#bd##ddd##db#.",  # 8
    "..#bdddddddddb#.",  # 9
    "..#dddddddddd#..",  # 10
    "...#ddddddddd#..",  # 11
    "....##ddddd##...",  # 12
    "......####......",  # 13
    "................",  # 14
    "................",  # 15
]

# sleep_1 — powered down + Zzz
JARVIS["sleep_1"] = [
    ".........zzz....",  # 0
    "........z.......",  # 1
    ".......ZZZ......",  # 2
    "...#bddddddb#...",  # 3
    "..#bdddddddb#...",  # 4
    "..#bdddddddddb#.",  # 5
    "..#bd##ddd##db#.",  # 6
    "..#bd#eddde#db#.",  # 7
    "..#bd##ddd##db#.",  # 8
    "..#bdddddddddb#.",  # 9
    "..#dddddddddd#..",  # 10
    "...#ddddddddd#..",  # 11
    "....##ddddd##...",  # 12
    "......####......",  # 13
    "................",  # 14
    "................",  # 15
]

# drag — glitchy stretched hologram
JARVIS["drag"] = [
    ".....####.......",  # 0  held here
    "....##bBb##.....",  # 1
    "...#bBwwBBb#....",  # 2
    "...#bbBbBBbb#...",  # 3
    "..#b##eeee##b#..",  # 4  visor = worried
    "..#b#ekkkke#b#..",  # 5
    "..#b##eeee##b#..",  # 6
    "...#bbbbbbbbb#..",  # 7
    "...#bbbbbbbb#...",  # 8  getting narrow = stretched
    "....#dbbbd#.....",  # 9
    "....#dbbbd#.....",  # 10
    ".....#dbd#......",  # 11  pointy = glitching
    "......#d#.......",  # 12
    ".......#........",  # 13
    "......g.g.......",  # 14 sparks
    "................",  # 15
]


# =====================================================================
# ULTRON — Menacing little robot, dark metal, angry red eyes
# =====================================================================

ULTRON_PALETTE = {
    ".": (0, 0, 0, 0),
    "#": (15, 12, 18, 255),       # very dark outline
    "m": (120, 125, 135, 255),    # metal gray
    "M": (175, 180, 195, 255),    # metal highlight
    "d": (65, 65, 80, 255),       # dark metal
    "D": (40, 38, 50, 255),       # very dark metal
    "r": (255, 40, 30, 255),      # red eye
    "R": (255, 100, 80, 255),     # red glow
    "k": (220, 225, 235, 255),    # highlight
    "w": (240, 240, 250, 255),    # white accent
    "z": (140, 160, 225, 255),
    "Z": (180, 200, 255, 255),
}

ULTRON = {}

# sit_0 — standing menacingly, red eyes glowing
ULTRON["sit_0"] = [
    "................",  # 0
    ".....######.....",  # 1  angular helmet top
    "....#MMmmMM#....",  # 2  helmet
    "...#MmmmmmmM#...",  # 3
    "..#Mmmmmmmmmm#..",  # 4
    "..#m##rrrr##m#..",  # 5  angry visor slit (red)
    "..#m#Rr##rR#m#..",  # 6  red glow in eyes
    "..#mmm####mmm#..",  # 7  face plate
    "..#mmmm##mmmm#..",  # 8  mouth slit
    "...#dmmmmmmmd#..",  # 9  chin
    "...#ddmmmmddd#..",  # 10 neck/shoulders
    "..#Dddmmmmddd#..",  # 11 body
    "..#Ddd####ddd#..",  # 12 torso detail
    "..#D##d..d##D#..",  # 13 legs
    "...##......##...",  # 14 feet
    "................",  # 15
]

# sit_1 — eyes pulse brighter
ULTRON["sit_1"] = [
    "................",  # 0
    ".....######.....",  # 1
    "....#MMmmMM#....",  # 2
    "...#MmmmmmmM#...",  # 3
    "..#Mmmmmmmmmm#..",  # 4
    "..#m##RRRR##m#..",  # 5  eyes BRIGHTER
    "..#m#RR##RR#m#..",  # 6
    "..#mmm####mmm#..",  # 7
    "..#mmmm##mmmm#..",  # 8
    "...#dmmmmmmmd#..",  # 9
    "...#ddmmmmddd#..",  # 10
    "..#Dddmmmmddd#..",  # 11
    "..#Ddd####ddd#..",  # 12
    "..#D##d..d##D#..",  # 13
    "...##......##...",  # 14
    "................",  # 15
]

# blink — eyes dim briefly
ULTRON["blink"] = [
    "................",  # 0
    ".....######.....",  # 1
    "....#MMmmMM#....",  # 2
    "...#MmmmmmmM#...",  # 3
    "..#Mmmmmmmmmm#..",  # 4
    "..#m##dddd##m#..",  # 5  eyes DARK (blink)
    "..#m#dd##dd#m#..",  # 6
    "..#mmm####mmm#..",  # 7
    "..#mmmm##mmmm#..",  # 8
    "...#dmmmmmmmd#..",  # 9
    "...#ddmmmmddd#..",  # 10
    "..#Dddmmmmddd#..",  # 11
    "..#Ddd####ddd#..",  # 12
    "..#D##d..d##D#..",  # 13
    "...##......##...",  # 14
    "................",  # 15
]

# walk_0 — marching right, left leg forward
ULTRON["walk_0"] = [
    "................",  # 0
    "......######....",  # 1  head forward
    ".....#MMmmMM#...",  # 2
    "....#MmmmmmmM#..",  # 3
    "...#Mmmmmmmmm#..",  # 4
    "...#m##rrrr##m#.",  # 5
    "...#m#Rr##rR#m#.",  # 6
    "...#mmm####mm#..",  # 7
    "...#mmmm##mmm#..",  # 8
    "....#dmmmmmd#...",  # 9
    "...#ddmmmmddd#..",  # 10
    "...#Dddmmmdd#...",  # 11
    "..##.#d##d#.##..",  # 12 marching legs
    "..#..##..##..#..",  # 13
    "...##......##...",  # 14
    "................",  # 15
]

# walk_1 — marching, opposite leg
ULTRON["walk_1"] = [
    "................",  # 0
    ".....######.....",  # 1
    "....#MMmmMM#....",  # 2
    "...#MmmmmmmM#...",  # 3
    "..#Mmmmmmmmmm#..",  # 4
    "..#m##rrrr##m#..",  # 5
    "..#m#Rr##rR#m#..",  # 6
    "..#mmm####mmm#..",  # 7
    "..#mmmm##mmmm#..",  # 8
    "...#dmmmmmmmd#..",  # 9
    "..#ddmmmmddd#...",  # 10
    "..#Dddmmmdd#....",  # 11
    "..#d#.#d#d.##...",  # 12 opposite legs
    "..##..##.##..#..",  # 13
    ".......#..##....",  # 14
    "................",  # 15
]

# run_0 — jet boosted dash!
ULTRON["run_0"] = [
    "................",  # 0
    "................",  # 1
    ".......######...",  # 2  head far forward
    "......#MMmmM#...",  # 3
    ".....#Mmmmmmm#..",  # 4
    "....#m##rrrr#m#.",  # 5
    "...#m#Rr##rR#m#.",  # 6
    "...#mmm####mm#..",  # 7
    "..#dmmmmmmmmm#..",  # 8
    "..#Dddmmmmmmd#..",  # 9
    ".RR#Dddddddd#...",  # 10 jet trail!
    "..RR##d..d##....",  # 11
    "....##...##.....",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# run_1 — dash other phase
ULTRON["run_1"] = [
    "................",  # 0
    "................",  # 1
    "......######....",  # 2
    ".....#MMmmMM#...",  # 3
    "....#Mmmmmmm#...",  # 4
    "...#m##rrrr##m#.",  # 5
    "...#m#Rr##rR#m#.",  # 6
    "..#mmm####mmm#..",  # 7
    "..#dmmmmmmmmd#..",  # 8
    ".#Dddmmmmmmd#...",  # 9
    ".R#Ddddddddd#...",  # 10 jet trail
    "..R##d..d##.....",  # 11
    "...##...##......",  # 12
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# swat_0 — arm raised, preparing to strike
ULTRON["swat_0"] = [
    "................",  # 0
    ".....######.....",  # 1
    "....#MMmmMM#....",  # 2
    "...#MmmmmmmM#...",  # 3
    "..#Mmmmmmmmmm#..",  # 4
    "..#m##rrrr##m#..",  # 5
    "..#m#Rr##rR#m#..",  # 6
    "..#mmm####mmm#..",  # 7
    ".##mmmm##mmm#...",  # 8  arm raised
    "#R##dmmmmmd#....",  # 9  red energy charging
    ".##ddmmmmddd#...",  # 10
    "..#Dddmmmmddd#..",  # 11
    "..#Ddd####ddd#..",  # 12
    "..#D##d..d##D#..",  # 13
    "...##......##...",  # 14
    "................",  # 15
]

# swat_1 — LASER BLAST
ULTRON["swat_1"] = [
    "................",  # 0
    ".....######.....",  # 1
    "....#MMmmMM#....",  # 2
    "...#MmmmmmmM#...",  # 3
    "..#Mmmmmmmmmm#..",  # 4
    "..#m##RRRR##m#..",  # 5  eyes BLAZING
    "..#m#RR##RR#m#..",  # 6
    "..#mmm####mmm#..",  # 7
    "..#mmmm##mmmm#..",  # 8
    "...#dmmmmmmmd#..",  # 9
    "...#ddmmmmddd#..",  # 10
    "..#Dddmmmmddd#..",  # 11
    "..#Ddd####ddd#..",  # 12
    "..#D##d..d##D#..",  # 13
    "RRRR##....##....",  # 14 BEAM!
    "................",  # 15
]

# sleep_0 — powered down
ULTRON["sleep_0"] = [
    "................",  # 0
    "................",  # 1
    ".....######.....",  # 2
    "....#dddDdd#....",  # 3
    "...#DddddddD#...",  # 4
    "..#Dddddddddd#..",  # 5
    "..#dd##dddd##d#.",  # 6
    "..#dd#dddddd#d#.",  # 7  visor completely dark
    "..#dd##dddd##d#.",  # 8
    "..#Dddddddddd#..",  # 9
    "...#DDdddddDD#..",  # 10
    "....#DDdddDD#...",  # 11
    ".....##DDD##....",  # 12
    "......####......",  # 13
    "................",  # 14
    "................",  # 15
]

# sleep_1 — powered down + Zzz
ULTRON["sleep_1"] = [
    ".........zzz....",  # 0
    "........z.......",  # 1
    ".....######.....",  # 2
    "....#dddDdd#....",  # 3
    "...#DddddddD#...",  # 4
    "..#Dddddddddd#..",  # 5
    "..#dd##dddd##d#.",  # 6
    "..#dd#dddddd#d#.",  # 7
    "..#dd##dddd##d#.",  # 8
    "..#Dddddddddd#..",  # 9
    "...#DDdddddDD#..",  # 10
    "....#DDdddDD#...",  # 11
    ".....##DDD##....",  # 12
    "......####......",  # 13
    "................",  # 14
    "................",  # 15
]

# drag — dangling, eyes darting
ULTRON["drag"] = [
    "....######......",  # 0  held here
    "...#MMmmMM#.....",  # 1
    "..#MmmmmmmM#....",  # 2
    "..#Mmmmmmmmm#...",  # 3
    ".#m##rrrr##mm#..",  # 4  eyes wild
    ".#m#rR##Rr#mm#..",  # 5  eyes looking sideways
    ".#mmm####mmm#...",  # 6
    "..#mmmm##mmm#...",  # 7
    "..#dmmmmmmmd#...",  # 8
    "..#ddmmmmddd#...",  # 9
    "..#Dddmmmdddd#..",  # 10
    "..#Ddd####ddd#..",  # 11
    "..#d#d....d#d#..",  # 12 legs dangling
    "..##.#....#.##..",  # 13
    "...##......##...",  # 14
    "................",  # 15
]


# =====================================================================
# GENERATE ALL
# =====================================================================

def generate_companion(name, frames, palette, skin_dir):
    out_dir = os.path.join(skin_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n{'='*40}")
    print(f"  {name.upper()} — {len(frames)} frames")
    print(f"{'='*40}")
    ok = True
    for frame_name, grid in frames.items():
        fp = os.path.join(out_dir, f"{frame_name}.png")
        if not validate_and_save(frame_name, grid, palette, fp):
            ok = False
    return ok


def main():
    skin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skins")

    all_ok = True
    all_ok &= generate_companion("shiba", SHIBA, SHIBA_PALETTE, skin_dir)
    all_ok &= generate_companion("ghost", GHOST, GHOST_PALETTE, skin_dir)
    all_ok &= generate_companion("jarvis", JARVIS, JARVIS_PALETTE, skin_dir)
    all_ok &= generate_companion("ultron", ULTRON, ULTRON_PALETTE, skin_dir)

    total = len(SHIBA) + len(GHOST) + len(GHOST) + len(JARVIS) + len(ULTRON)
    if all_ok:
        print(f"\n✅ ALL DONE! Generated sprites for 4 companions.")
        print(f"   Shiba: {len(SHIBA)}, Ghost: {len(GHOST)}, "
              f"Jarvis: {len(JARVIS)}, Ultron: {len(ULTRON)}")
    else:
        print(f"\n❌ Some frames had errors. Check output above.")


if __name__ == "__main__":
    main()
