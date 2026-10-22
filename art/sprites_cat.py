"""sprites_cat.py - the orange tabby, 16x16.

Built on the shared four-legged rig in sprites_quad.py; this file only holds
what makes it a cat: the palette, the head and ear shapes, tabby stripes and a
long, expressive tail.
"""

from pixelart import hexc
from sprite_kit import grid
import sprites_quad as quad

PALETTE = {
    ".": (0, 0, 0, 0),
    "#": hexc("#2a171d"),   # ink
    "o": hexc("#f0913c"),   # fur
    "O": hexc("#ffbb6b"),   # fur, lit
    "d": hexc("#c25e20"),   # fur, shade
    "s": hexc("#a24914"),   # tabby stripe
    "w": hexc("#fff3e0"),   # cream
    "W": hexc("#e2c49e"),   # cream, shade
    "p": hexc("#ff8fa6"),   # nose / inner ear
    "P": hexc("#e2486a"),   # tongue
    "b": hexc("#ffa3b4"),   # blush
    "e": hexc("#1d1420"),   # eyes
    "B": hexc("#4a7bd1"),   # bowl
    "C": hexc("#2f5299"),   # bowl, shade
    "F": hexc("#a8663a"),   # kibble
}

HEADS = {
    "up": grid((
        "Oo.....od",
        "OpO...opd",
        "OOOsoSood",
        "Ooooooood",
        "Ooooooood",
        "Ooooooood",
        "dowwwwwod",
        ".dwwwwwd.",
    ), "cat/head/up"),
    "perk": grid((
        "O.......d",
        "Oo.....od",
        "OpOsoSopd",
        "Ooooooood",
        "Ooooooood",
        "Ooooooood",
        "dowwwwwod",
        ".dwwwwwd.",
    ), "cat/head/perk"),
    "flat": grid((
        ".........",
        "oo.....oo",
        "OpOsoSopd",
        "Ooooooood",
        "Ooooooood",
        "Ooooooood",
        "dowwwwwod",
        ".dwwwwwd.",
    ), "cat/head/flat"),
}
# the "S" above is a stripe that also has to read on the lit side
for _k, _rows in list(HEADS.items()):
    HEADS[_k] = tuple(r.replace("S", "s") for r in _rows)

BACK_HEAD = grid((
    "Oo.....od",
    "OoO...ood",
    "OOOsosood",
    "Ooosooood",
    "Ooooooood",
    "Ooooooood",
    "doooooood",
    ".ddddddd.",
), "cat/head/back")

TAILS = [
    grid((".O", "O.", "o.", "o.", "od"), "cat/tail/0"),
    grid(("O.", "o.", "o.", "o.", "od"), "cat/tail/1"),
    grid(("..", "O.", "o.", "od", "od"), "cat/tail/2"),
]

SIT_TAIL = [
    grid((".....o", "ooooo."), "cat/sit-tail/0"),
    grid(("o.....", ".ooooo"), "cat/sit-tail/1"),
    grid(("O.....", "o.....", ".ooooo"), "cat/sit-tail/2"),
    grid(("o.....", ".ooooo"), "cat/sit-tail/3"),
]

BOWL = grid((
    "FFF",
    "BBB",
    "CCC",
), "cat/bowl")

SPECIES = quad.Species(
    "cat", PALETTE, HEADS, TAILS,
    body_marks=[(3, 0, "s"), (5, 0, "s"), (7, 0, "s"), (4, 1, "s"), (6, 1, "s")],
    back_head=BACK_HEAD, sit_tail=SIT_TAIL,
    sleep_tail=grid(("oooooo",), "cat/sleep-tail"),
)

SIZE = 16


def frames():
    return quad.build(SPECIES, BOWL)
