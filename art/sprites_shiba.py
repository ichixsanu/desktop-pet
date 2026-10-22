"""sprites_shiba.py - the shiba inu, 16x16.

Same four-legged rig as the cat (sprites_quad.py); what makes it a shiba is
here: tall pointed ears, the white urajiro mask with eyebrow dots, a black
nose, a lolling tongue and the tail curled up over its back.
"""

from pixelart import hexc
from sprite_kit import grid
import sprites_quad as quad

PALETTE = {
    ".": (0, 0, 0, 0),
    "#": hexc("#2b1a14"),   # ink
    "o": hexc("#e08d45"),   # fur
    "O": hexc("#f7b46e"),   # fur, lit
    "d": hexc("#b4632b"),   # fur, shade
    "s": hexc("#9c5222"),   # sesame
    "w": hexc("#fff6ea"),   # urajiro cream
    "W": hexc("#e8d2b4"),   # cream, shade
    "p": hexc("#2b1a14"),   # nose (black on a shiba)
    "i": hexc("#ffb0a0"),   # inner ear
    "P": hexc("#ef5a6f"),   # tongue
    "b": hexc("#ffad9e"),   # blush
    "e": hexc("#1d1410"),   # eyes
    "B": hexc("#d94a4a"),   # bowl
    "C": hexc("#9e2f36"),   # bowl, shade
    "F": hexc("#b8743e"),   # kibble
}

HEADS = {
    "up": grid((
        "O.......d",
        "Oi.....id",
        "OiO...oid",
        "OOooooood",
        "Owoooowod",
        "wwoooooww",
        "wwwwwwwww",
        ".wwwwwww.",
    ), "shiba/head/up"),
    "perk": grid((
        "Oi.....id",
        "OiO...oid",
        "OOOoooood",
        "Ooooooood",
        "Owoooowod",
        "wwoooooww",
        "wwwwwwwww",
        ".wwwwwww.",
    ), "shiba/head/perk"),
    "flat": grid((
        ".........",
        "Oo.....od",
        "OiOo.ooid",
        "OOooooood",
        "Owoooowod",
        "wwoooooww",
        "wwwwwwwww",
        ".wwwwwww.",
    ), "shiba/head/flat"),
}

BACK_HEAD = grid((
    "O.......d",
    "Oo.....od",
    "OoO...ood",
    "OOooooood",
    "Ooooooood",
    "Ooooooood",
    "doooooood",
    ".ddddddd.",
), "shiba/head/back")

# the famous curl, riding over the back
TAILS = [
    grid((".Oo", "Owo", "oo.", ".o."), "shiba/tail/0"),
    grid(("Oo.", "wo.", "oo.", ".o."), "shiba/tail/1"),
]

SIT_TAIL = [
    grid((".Oo...", "Owo...", "oo...."), "shiba/sit-tail/0"),
    grid(("Oo....", "wo....", "oo...."), "shiba/sit-tail/1"),
    grid((".Oo...", "Owo...", "oo...."), "shiba/sit-tail/2"),
    grid(("..Oo..", ".Owo..", ".oo..."), "shiba/sit-tail/3"),
]

BOWL = grid((
    "FFF",
    "BBB",
    "CCC",
), "shiba/bowl")

SPECIES = quad.Species(
    "shiba", PALETTE, HEADS, TAILS,
    body_marks=[(4, 0, "s"), (5, 0, "s"), (6, 0, "s")],
    back_head=BACK_HEAD, sit_tail=SIT_TAIL,
    sleep_tail=grid(("Oooow",), "shiba/sleep-tail"),
    tongue="P", tail_dx=1, tail_drop=1,
)

SIZE = 16


def frames():
    out = quad.build(SPECIES, BOWL)
    # a shiba's resting face has its tongue out
    for i in range(4):
        out["sit_%d" % i] = quad.pose_sit(SPECIES, i, eyes="open",
                                          mouth="tongue" if i % 2 else "calm")
    return out
