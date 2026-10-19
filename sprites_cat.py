"""sprites_cat.py - hand-drawn 24x24 pixel art for the cat companion.

The cat is drawn the way a pixel artist draws: the shapes that carry the
character - head, tail, body masses - are hand-placed grids of palette keys, so
the silhouette is a decision instead of whatever an ellipse happened to round
to. Only the legs, the eye stamps and the per-frame offsets are computed, and
those are integer-only.

Conventions
-----------
* Facing right. The app mirrors for facing left; the head is drawn front-on so
  mirroring never flips the face.
* Bottom-anchored: the paws fill row 22 and the automatic 1px outline lands on
  row 23. That ink line is the ground contact.
* Each part is finished on its own (rim light, rim shade, 1px ink outline) and
  composited back to front. Per-part outlining is what gives a paw an ink
  separator against a belly and the tail one against the rump.
* Near-side limbs use "o" (fur); far-side limbs use "d" (fur in shade).
"""

from pixelart import Sprite, hexc

PALETTE = {
    ".": (0, 0, 0, 0),
    "#": hexc("#2a171d"),   # outline, warm near-black
    "o": hexc("#ee8e3a"),   # fur
    "O": hexc("#ffbe71"),   # fur in light
    "d": hexc("#c66221"),   # fur in shade
    "s": hexc("#9a4212"),   # tabby stripe
    "w": hexc("#fff6e8"),   # cream
    "W": hexc("#e0c8a8"),   # cream in shade
    "p": hexc("#ff9aae"),   # pink: inner ear, nose
    "P": hexc("#d9536f"),   # deep pink: tongue, toe beans
    "g": hexc("#6ad466"),   # iris
    "e": hexc("#1b3223"),   # pupil
    "k": hexc("#ffffff"),   # catchlight
    "b": hexc("#ff9daf"),   # blush
    "z": hexc("#8d9fd6"),   # zzz, dim
    "Z": hexc("#c2d1ff"),   # zzz, bright
}

SIZE = 24
PAW_ROW = 22            # paws fill this row; the outline takes row 23

FUR, HI, LO, STRIPE = "o", "O", "d", "s"
CREAM, CREAM_LO, PINK, DEEP_PINK = "w", "W", "p", "P"
INK = "#"


def _grid(rows, width, label):
    """Hand-drawn grids fail loudly: a miscounted row is a broken sprite."""
    bad = ["%d %r" % (len(r), r) for r in rows if len(r) != width]
    if bad:
        raise ValueError("%s wants width %d: %s" % (label, width, "; ".join(bad)))
    return tuple(rows)


# =====================================================================
# the head - 13 wide x 14 tall, skull centre at local (6, 8)
# =====================================================================

# Ear zone (local rows 0-3). "up" leaves the top row empty so "perked" can be a
# nose taller and "back"/"flat" read as shorter and more swept.
EARS = {
    "up": _grid((
        ".............",
        "..o......o...",
        "..Oo....oo...",
        ".Ooop..pood..",
    ), 13, "ears/up"),
    "perked": _grid((
        "..o......o...",
        "..Oo....oo...",
        ".Ooo....ooo..",
        ".Ooop..pood..",
    ), 13, "ears/perked"),
    "back": _grid((
        ".............",
        ".............",
        ".o........o..",
        ".Ooop..pood..",
    ), 13, "ears/back"),
    "flat": _grid((
        ".............",
        ".............",
        "o..........o.",
        "oOoop..poodo.",
    ), 13, "ears/flat"),
}

# Skull (local rows 4-13): wide cheeks, tapering chin, forehead stripes.
SKULL = _grid((
    ".Ooooooooood.",
    "Ooooososooood",
    "Oooooosoooood",
    "Ooooooooooood",
    "Ooooooooooood",
    ".Ooooooooood.",
    ".Ooooooooood.",
    "..Ooooooood..",
    "...Ooooood...",
    "....WwwwW....",
), 13, "skull")

EYES = {
    "open": ("ggg", "geg", "geg"),
    "wide": ("ggg", "eee", "eee"),
    "half": ("eee", "ggg", "geg"),
    "shut": ("...", "###", "..."),
    "happy": (".#.", "#.#", "..."),
    "sleep": ("...", "###", "..."),
}


def _face(s, x, y, eyes, mouth, blush):
    """Eyes, muzzle, nose and mouth, in head-local coordinates."""
    for ex in (2, 8):
        s.stamp(EYES[eyes], x + ex, y + 6)
    s.rect(x + 4, y + 11, x + 8, y + 12, CREAM)          # muzzle
    s.put(x + 6, y + 10, DEEP_PINK)                      # nose
    if mouth == "calm":
        s.put(x + 6, y + 11, INK)
        s.px_at([(x + 5, y + 12), (x + 7, y + 12)], INK)
    elif mouth == "grin":
        s.px_at([(x + 5, y + 11), (x + 7, y + 11)], INK)
        s.put(x + 6, y + 12, INK)
    elif mouth == "open":                                # meow
        s.rect(x + 5, y + 11, x + 7, y + 11, INK)
        s.put(x + 6, y + 12, DEEP_PINK)
        s.px_at([(x + 5, y + 12), (x + 7, y + 12)], INK)
    elif mouth == "yawn":
        s.rect(x + 4, y + 11, x + 8, y + 11, INK)
        s.rect(x + 4, y + 12, x + 8, y + 12, INK)
        s.put(x + 6, y + 12, DEEP_PINK)
        s.rect(x + 5, y + 13, x + 7, y + 13, INK)
    elif mouth == "lick":                                # tongue out
        s.rect(x + 5, y + 11, x + 7, y + 11, INK)
        s.put(x + 6, y + 12, DEEP_PINK)
        s.put(x + 6, y + 13, DEEP_PINK)
    if blush:
        s.px_at([(x + 3, y + 11), (x + 9, y + 11)], "b")


def head(x, y, eyes="open", mouth="calm", ears="up", blush=False, dy=0):
    """The head as one finished part; (x, y) is its top-left corner."""
    s = Sprite(SIZE, SIZE)
    rows = EARS[ears] + SKULL
    for dy_, row in enumerate(rows):
        s.stamp((row,), x, y + dy_ + dy)
    _face(s, x, y + dy, eyes, mouth, blush)
    s.outline(INK)
    return s
