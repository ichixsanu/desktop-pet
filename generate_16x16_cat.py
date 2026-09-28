"""
16x16 Pixel Art Cat Sprite Generator — FINAL VERSION.
Every single pixel hand-placed. Pure retro pixel art.

Design principles:
  - 1px dark outline, zero orphan pixels, clean diagonals
  - Chibi proportions: big round head (~7px), compact body (~5px)
  - Warm orange tabby: cream chest/muzzle, green eyes, pink nose
  - EVERY frame has a DISTINCT silhouette — walk ≠ sit ≠ run ≠ sleep
  - Consistent head design across all poses (same eyes, ears, features)

Palette (10 colors + transparent):
  . = transparent
  # = outline (30, 20, 15)      — warm dark brown-black
  o = orange fur (240, 148, 48) — main body color
  O = highlight (255, 198, 108) — forehead, ear tips
  d = shade (195, 100, 30)      — under chin, belly shade
  s = stripe (155, 72, 20)      — tabby back stripes
  w = white (255, 248, 240)     — muzzle, chest, paws
  p = pink (255, 140, 168)      — nose, inner ears
  g = green eye (35, 195, 120)
  e = dark eye (15, 12, 10)
  k = catchlight (255, 255, 255)
  z = zzz blue (140, 160, 225)
  Z = zzz bright (180, 200, 255)
"""

import os
import struct
import zlib

PALETTE = {
    ".": (0, 0, 0, 0),
    "#": (30, 20, 15, 255),
    "o": (240, 148, 48, 255),
    "O": (255, 198, 108, 255),
    "d": (195, 100, 30, 255),
    "s": (155, 72, 20, 255),
    "w": (255, 248, 240, 255),
    "p": (255, 140, 168, 255),
    "g": (35, 195, 120, 255),
    "e": (15, 12, 10, 255),
    "k": (255, 255, 255, 255),
    "z": (140, 160, 225, 255),
    "Z": (180, 200, 255, 255),
}


def save_png(filepath, width, height, rgba_bytes):
    """Write a minimal valid PNG from raw RGBA bytes."""
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


def grid_to_rgba(lines, size=16):
    """Convert list of pixel-art row strings to RGBA bytes."""
    raw = bytearray()
    for y in range(size):
        row = lines[y] if y < len(lines) else "." * size
        for x in range(size):
            ch = row[x] if x < len(row) else "."
            r, g, b, a = PALETTE.get(ch, (0, 0, 0, 0))
            raw.extend((r, g, b, a))
    return bytes(raw)


def save_sprite(filepath, lines, size=16):
    rgba = grid_to_rgba(lines, size)
    save_png(filepath, size, size, rgba)
    print(f"  ✓ {os.path.basename(filepath)}")


# =====================================================================
# 16x16 CAT SPRITE FRAMES — every pixel counts
# =====================================================================
# Grid: 16 cols (0-15) × 16 rows (0-15).
# Cat centered roughly cols 2-13, rows 1-13.
# Head: ~8px wide, ears add 2px height. Body: ~6px wide.

FRAMES = {}

# -----------------------------------------------------------------
# sit_0 — Classic sitting kitten, 3/4 view facing right.
#   Pointy ears, round head, green eyes with catchlight,
#   white muzzle + pink nose, orange body, white chest, curled tail.
# -----------------------------------------------------------------
FRAMES["sit_0"] = [
    "................",  # 0
    "....##....##....",  # 1  ear tips (outline)
    "...#oO#..#Op#...",  # 2  ears: left has highlight, right has pink inner
    "...#oooooooo#...",  # 3  top of head
    "..#Oooooooooo#..",  # 4  forehead with highlight
    "..#okg#oo#gko#..",  # 5  eyes: k=catchlight, g=green iris
    "..#ooowppwooo#..",  # 6  white muzzle, pp=pink nose
    "...#oowwwwoo#...",  # 7  lower muzzle white
    "...#sdoooosd#...",  # 8  neck: s=stripe, d=shade
    "...#oooooooo##..",  # 9  body + tail start
    "...#owwwwooo#o#.",  # 10 white chest + tail mid
    "...#owwwwoooo##.",  # 11 chest continues + tail end
    "...#o##oo##oo#..",  # 12 front paws (outlined)
    "....##..##.##...",  # 13 feet on ground
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# sit_1 — Breathing idle: chest puffs slightly, tail swishes other way.
# -----------------------------------------------------------------
FRAMES["sit_1"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#oO#..#Op#...",  # 2
    "...#oooooooo#...",  # 3
    "..#Oooooooooo#..",  # 4
    "..#okg#oo#gko#..",  # 5
    "..#ooowppwooo#..",  # 6
    "...#oowwwwoo#...",  # 7
    "...#sdoooosd#...",  # 8
    "..##oooooooo#...",  # 9  tail on left now
    ".#o#owwwwooo#...",  # 10 tail extends left + wider chest
    ".##oowwwwooo#...",  # 11
    "...#oo##oo##o#..",  # 12
    "....##..##..##..",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# blink — Kawaii ^_^ happy squint. Same body as sit_0.
# -----------------------------------------------------------------
FRAMES["blink"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#oO#..#Op#...",  # 2
    "...#oooooooo#...",  # 3
    "..#Oooooooooo#..",  # 4
    "..#oo.#oo#.oo#..",  # 5  ^_^ closed eyes (. = transparent gaps)
    "..#ooowppwooo#..",  # 6
    "...#oowwwwoo#...",  # 7
    "...#sdoooosd#...",  # 8
    "...#oooooooo##..",  # 9
    "...#owwwwooo#o#.",  # 10
    "...#owwwwoooo##.",  # 11
    "...#o##oo##oo#..",  # 12
    "....##..##.##...",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# groom_0 — Left paw raised to face, licking. Right eye open, left shut.
# -----------------------------------------------------------------
FRAMES["groom_0"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#oO#..#Op#...",  # 2
    "...#oooooooo#...",  # 3
    "..#Oooooooooo#..",  # 4
    "..#oo.#oo#gko#..",  # 5  left eye shut, right open
    ".##woowppwooo#..",  # 6  paw reaching face
    ".#w#owwwwwoo#...",  # 7  white paw visible
    "..##sdoooosd#...",  # 8
    "...#oooooooo##..",  # 9
    "...#oowwwooo#o#.",  # 10
    "...#oowwwoooo##.",  # 11
    "....##.oo##oo#..",  # 12 left paw missing (it's up)
    ".....#.##.##....",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# groom_1 — Paw rubbing cheek, eyes closed in bliss.
# -----------------------------------------------------------------
FRAMES["groom_1"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#oO#..#Op#...",  # 2
    "...#oooooooo#...",  # 3
    "..#Oooooooooo#..",  # 4
    "..#oo.#oo#.oo#..",  # 5  both eyes shut (bliss)
    "##wooowppwooo#..",  # 6  paw on cheek further out
    "#w#oowwwwwoo#...",  # 7
    ".##sdoooosd#....",  # 8
    "...#oooooooo##..",  # 9
    "...#oowwwooo#o#.",  # 10
    "...#oowwwoooo##.",  # 11
    "....##.oo##oo#..",  # 12
    ".....#.##.##....",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# walk_0 — Trotting right. Front-right + rear-left legs forward.
#   Body is more horizontal than sitting. Head slightly forward.
# -----------------------------------------------------------------
FRAMES["walk_0"] = [
    "................",  # 0
    ".....##...##....",  # 1  ears (shifted right = head forward)
    "....#oO#.#Op#...",  # 2
    "....#oooooooo#..",  # 3
    "...#Ooooooooo#..",  # 4
    "...#okg#o#gko#..",  # 5
    "...#ooowpwooo#..",  # 6
    "....#owwwwoo#...",  # 7
    "...#sdooooood#..",  # 8  horizontal body
    "...#ooooooooo##.",  # 9  + tail up
    "...#owwoooooo#..",  # 10 smaller chest (walking)
    "..##.#o#..#o##..",  # 11 legs: FL back, FR fwd, RL fwd, RR back
    "..#..##...##.#..",  # 12
    "...##.......##..",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# walk_1 — Trotting right, opposite legs.
# -----------------------------------------------------------------
FRAMES["walk_1"] = [
    "................",  # 0
    ".....##...##....",  # 1
    "....#oO#.#Op#...",  # 2
    "....#oooooooo#..",  # 3
    "...#Ooooooooo#..",  # 4
    "...#okg#o#gko#..",  # 5
    "...#ooowpwooo#..",  # 6
    "....#owwwwoo#...",  # 7
    "...#sdooooood#..",  # 8
    "...#ooooooooo##.",  # 9
    "...#owwoooooo#..",  # 10
    "...#o#..#o#.##..",  # 11 legs swapped
    "...##.#.##.#.#..",  # 12
    "......##....##..",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# run_0 — Playful leap! Body stretched horizontal, paws extended,
#   airborne with gap below. Tail streaming behind.
# -----------------------------------------------------------------
FRAMES["run_0"] = [
    "................",  # 0
    "................",  # 1
    "......##..##....",  # 2  ears
    ".....#oO#.#o#...",  # 3
    "....#ooooooo#...",  # 4
    "...#okg#o#gko#..",  # 5
    "...#ooowpwooo#..",  # 6
    "....#owwwwo#....",  # 7
    "..##sooooood##..",  # 8  stretched body + tail
    ".#oowwwoooooo#..",  # 9  white chest
    ".#ow#ooooooo#...",  # 10
    "..##.#.....##...",  # 11 legs stretched out = airborne
    "................",  # 12 nothing here = in the air!
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# run_1 — Landing pounce, legs gathered under body, compact.
# -----------------------------------------------------------------
FRAMES["run_1"] = [
    "................",  # 0
    "................",  # 1
    ".....##...##....",  # 2
    "....#oO#.#Op#...",  # 3
    "....#oooooooo#..",  # 4
    "...#okg#o#gko#..",  # 5
    "...#ooowpwooo#..",  # 6
    "....#owwwwo#....",  # 7
    "##..#sooood#....",  # 8  tail extends back left
    "#oo#owwwoooo#...",  # 9
    ".##oowwoooo#....",  # 10
    "...#o##o##o#....",  # 11 legs gathered under
    "....##.##.##....",  # 12 all feet touching
    "................",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# stalk_0 — Hunter crouch. Body LOW and flat, butt up, tail left.
#   Head close to ground, intense stare. Very different from sit.
# -----------------------------------------------------------------
FRAMES["stalk_0"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "................",  # 3
    "....##...##.....",  # 4  ears low (crouching!)
    "...#oO#.#Op#....",  # 5
    "...#ooooooo#....",  # 6
    "..#okg#o#gko#...",  # 7  intense eyes, head low
    "..#ooowpwooo#...",  # 8
    "...#wwwwwoo#....",  # 9  muzzle near ground
    ".##sdooooooo#...",  # 10 flat body + tail left
    "#oo#owwwoooo#...",  # 11 tail extends far left
    ".##.#o##o##o#...",  # 12 crouched short legs
    "....##..##.##...",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# stalk_1 — Creep step forward, tail sways right. Butt wiggle.
# -----------------------------------------------------------------
FRAMES["stalk_1"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "................",  # 3
    "....##...##.....",  # 4
    "...#oO#.#Op#....",  # 5
    "...#ooooooo#....",  # 6
    "..#okg#o#gko#...",  # 7
    "..#ooowpwooo#...",  # 8
    "...#wwwwwoo#....",  # 9
    "...#sdoooooo##..",  # 10 body + tail right
    "...#owwwooooo#o#",  # 11 tail extends far right
    "..##.#o#o##..##.",  # 12 legs mid-step
    "..#..##..##.....",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# swat_0 — Coiled ready pose. Body sitting up, left paw raised
#   near face, eyes locked on target. Spring-loaded.
# -----------------------------------------------------------------
FRAMES["swat_0"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#oO#..#Op#...",  # 2
    "...#oooooooo#...",  # 3
    "..#Oooooooooo#..",  # 4
    "..#okg#oo#gko#..",  # 5  focused stare
    "..#ooowppwooo#..",  # 6
    ".##wowwwwwoo#...",  # 7  left paw raised
    ".#w##sdoosd#....",  # 8
    "..##oooooooo##..",  # 9
    "...#owwwwooo#o#.",  # 10
    "...#owwoooooo##.",  # 11
    "....##.oo##oo#..",  # 12 left paw missing (it's raised)
    ".....#.##.##....",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# swat_1 — STRIKE! Left paw extended waaay forward. Toe beans!
# -----------------------------------------------------------------
FRAMES["swat_1"] = [
    "................",  # 0
    "....##....##....",  # 1
    "...#oO#..#Op#...",  # 2
    "...#oooooooo#...",  # 3
    "..#Oooooooooo#..",  # 4
    "..#okg#oo#gko#..",  # 5
    "..#ooowppwooo#..",  # 6
    "...#oowwwwoo#...",  # 7
    "##w#sdoooosd#...",  # 8  paw EXTENDED far left + toe beans
    ".##oooooooo##...",  # 9
    "...#owwwwooo#o#.",  # 10
    "...#owwoooooo##.",  # 11
    "....##.oo##oo#..",  # 12
    ".....#.##.##....",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# sleep_0 — Curled cat loaf! Completely different silhouette.
#   Round compact shape, tucked paws, closed eyes, nose on paws.
# -----------------------------------------------------------------
FRAMES["sleep_0"] = [
    "................",  # 0
    "................",  # 1
    "................",  # 2
    "................",  # 3
    "................",  # 4
    "................",  # 5
    "...###....###...",  # 6  ear tips peek from loaf
    "..#oOo#..#oOo#..",  # 7  ears
    "..#ooooooooooo#.",  # 8  round loaf top
    "..#oo.#ooo.#oo#.",  # 9  closed eyes (.)
    "..#ooowwpwwooo#.",  # 10 muzzle
    "..#wwwwwwwwwooo#",  # 11 tucked white paws + tail wrapping
    "..#oooooooooooo#",  # 12 loaf body
    "...############.",  # 13 loaf bottom outline
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# sleep_1 — Same loaf + floating Zzz above.
# -----------------------------------------------------------------
FRAMES["sleep_1"] = [
    "................",  # 0
    ".........zzz....",  # 1  small z
    "........z.......",  # 2
    ".......ZZZ......",  # 3  big Z
    "......Z.........",  # 4
    "................",  # 5
    "...###....###...",  # 6
    "..#oOo#..#oOo#..",  # 7
    "..#ooooooooooo#.",  # 8
    "..#oo.#ooo.#oo#.",  # 9
    "..#ooowwpwwooo#.",  # 10
    "..#wwwwwwwwwooo#",  # 11
    "..#oooooooooooo#",  # 12
    "...############.",  # 13
    "................",  # 14
    "................",  # 15
]

# -----------------------------------------------------------------
# climb_0 — Cat clinging to a wall on the left side, seen from side.
#   Body VERTICAL. Head at top looking up-right, paws gripping left.
#   Tail hangs down. Completely different silhouette from any other pose.
# -----------------------------------------------------------------
FRAMES["climb_0"] = [
    "................",  # 0
    "..##............",  # 1  left ear
    ".#oO##..........",  # 2  head top
    ".#oooo#.........",  # 3
    "#wokg#o#........",  # 4  eyes (sideways head), left paw grips wall
    "#wowpoo#........",  # 5  muzzle
    ".#owwo#.........",  # 6
    ".#osoo#.........",  # 7  body with stripe
    "#woodo#.........",  # 8  paw grips wall
    "#woooo#.........",  # 9
    ".#osoo#.........",  # 10 stripe
    ".#oooo#.........",  # 11
    "#wodo#..........",  # 12 rear paw grips
    "#wooo#..........",  # 13
    ".###.#..........",  # 14 tail hangs down
    ".....#..........",  # 15
]

# -----------------------------------------------------------------
# climb_1 — Climbing higher, opposite paws shifted. Slight upward motion.
# -----------------------------------------------------------------
FRAMES["climb_1"] = [
    "..##............",  # 0  ear (higher = progressing up)
    ".#oO##..........",  # 1
    ".#oooo#.........",  # 2
    "#wokg#o#........",  # 3
    "#wowpoo#........",  # 4
    ".#owwo#.........",  # 5
    "#wosoo#.........",  # 6  paw shifted (opposite grip)
    ".#odo#..........",  # 7
    ".#oooo#.........",  # 8
    "#wosooo#........",  # 9  wider body = stretching
    ".#odoo#.........",  # 10
    ".#oooo#.........",  # 11
    "#wooo#..........",  # 12
    ".###..#.........",  # 13 tail
    "......#.........",  # 14
    "......#.........",  # 15
]

# -----------------------------------------------------------------
# drag — Kitten dangled by scruff! Round O.O worried eyes,
#   body hanging straight down, paws dangling limp, tail drooping.
# -----------------------------------------------------------------
FRAMES["drag"] = [
    ".....##.........",  # 0  scruff point (held here)
    "....#oo##.......",  # 1  head top
    "...#ooooop#.....",  # 2  ear with pink inner
    "...#ooooooo#....",  # 3
    "..#oooooooo#....",  # 4  wide head (worried)
    "..#okg#o#gko#...",  # 5  big round O.O eyes
    "..#ooowppwoo#...",  # 6  open mouth (surprised)
    "...#oowwwoo#....",  # 7  chin
    "...#sdooosd#....",  # 8  neck
    "...#oooooooo#...",  # 9  body hanging straight
    "...#owwwwwoo#...",  # 10 white belly
    "...#owwwwwoo#...",  # 11
    "...#w#.w.#w#....",  # 12 dangling paws (limp)
    "...##..#..##....",  # 13 paw tips
    "......#.........",  # 14 tail hanging straight down
    "......#.........",  # 15
]


# =====================================================================
# VALIDATE AND GENERATE
# =====================================================================
def validate_frame(name, grid):
    """Strict validation: exact dimensions, valid palette chars."""
    errors = []
    if len(grid) != 16:
        errors.append(f"expected 16 rows, got {len(grid)}")
    for i, row in enumerate(grid):
        if len(row) != 16:
            errors.append(f"row {i}: expected 16 cols, got {len(row)} -> '{row}'")
        for j, ch in enumerate(row):
            if ch not in PALETTE:
                errors.append(f"row {i} col {j}: unknown char '{ch}'")
    if errors:
        print(f"\n*** ERRORS in {name}:")
        for e in errors:
            print(f"    {e}")
        return False
    return True


def main():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skins", "cat")
    os.makedirs(out_dir, exist_ok=True)

    print("Generating 16x16 cat pixel art sprites...\n")

    all_ok = True
    for name, grid in FRAMES.items():
        if not validate_frame(name, grid):
            all_ok = False

    if not all_ok:
        print("\n!!! Validation failed. Fix errors above before generating.")
        return

    for name, grid in FRAMES.items():
        filepath = os.path.join(out_dir, f"{name}.png")
        save_sprite(filepath, grid, 16)

    print(f"\n✅ Done! {len(FRAMES)} sprites saved to {out_dir}")
    print(f"Frames: {', '.join(sorted(FRAMES.keys()))}")


if __name__ == "__main__":
    main()
