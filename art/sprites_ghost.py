"""sprites_ghost.py - the little sheet ghost, 16x16.

The body is drawn from code rather than a fixed grid because its hem is the
animation: a wave that scrolls one step per frame, so every pose gets a
living, rippling bottom edge for free. The sheet is slightly translucent.
"""

from pixelart import Sprite, hexc
from sprite_kit import SIZE, INK

PALETTE = {
    ".": (0, 0, 0, 0),
    "#": hexc("#2d2240"),           # ink
    "w": hexc("#f2efff", 236),      # sheet
    "k": hexc("#ffffff", 245),      # sheet, lit
    "v": hexc("#c9c2ef", 236),      # sheet, shade
    "V": hexc("#a99fe0", 236),      # sheet, deep shade (hem)
    "e": hexc("#2a1f3d"),           # eyes
    "b": hexc("#ffa6c9"),           # blush
    "m": hexc("#5a2a4a"),           # mouth
    "P": hexc("#ff6f91"),           # tongue
    "c": hexc("#c98a4b"),           # cookie
    "C": hexc("#6b3f22"),           # choc chips
}

BODY_X = 2          # left column of the sheet
WIDTH = 12
WAVE = (2, 1, 0, 1)   # hem depth by column, scrolled per frame


def sheet(frame=0, top=1, hem=11, lean=0, squash=0, wisp=0):
    """The sheet silhouette, un-outlined.

    top: row of the dome's crown. hem: row where the wave starts.
    lean: crown offset in px (flying). wisp: extra trailing hem on the left.
    """
    s = Sprite(SIZE, SIZE)
    dome = [4, 8, 10, 10, 12]          # row widths for the crown
    top += squash
    for r, width in enumerate(dome):
        y = top + r
        x0 = BODY_X + (WIDTH - width) // 2 + (lean if r < 2 else 0)
        s.hline(y, x0, x0 + width - 1, "w")
    for y in range(top + len(dome), hem):
        s.hline(y, BODY_X, BODY_X + WIDTH - 1, "w")
    for i in range(WIDTH):
        depth = WAVE[(i + frame) % len(WAVE)]
        for d in range(depth + 1):
            s.put(BODY_X + i, hem + d, "w")
    for i in range(wisp):
        s.put(BODY_X - 1 - i, hem - 1 + (i % 2), "w")
    s.edge_light("w", "k")
    s.edge_shadow("wk", "v")
    # a lavender band where the sheet folds into the hem
    for x in range(SIZE):
        for y in range(hem, SIZE):
            if s.get(x, y) == "w":
                s.put(x, y, "v")
    for i in range(WIDTH):
        x = BODY_X + i
        depth = WAVE[(i + frame) % len(WAVE)]
        if s.get(x, hem + depth) != ".":
            s.put(x, hem + depth, "V")
    return s


EYES = {
    "open":  ((0, 0), (0, 1)),
    "wide":  ((0, 0), (0, 1), (1, 0), (1, 1)),
    "blink": ((0, 1), (1, 1)),
    "shut":  ((-1, 1), (0, 1), (1, 1)),
    "happy": ((0, 0), (-1, 1), (1, 1)),
    "dizzy": ((-1, 0), (1, 0), (0, 1)),
    "angry": ((-1, 0), (0, 1), (1, 1)),
    "look":  ((1, 0), (1, 1)),
}


def face(s, eyes="open", mouth="calm", blush=True, dx=0, dy=0, top=1):
    cy = top + 5 + dy
    lx, rx = 5 + dx, 10 + dx
    pts = EYES[eyes]
    for px, py in pts:
        s.put(lx + px, cy + py, "e")
        # mirror for the right eye (happy/angry are symmetric shapes)
        mx = -px if eyes in ("angry",) else px
        s.put(rx + mx, cy + py, "e")
    if blush:
        s.px_at([(lx - 1, cy + 2), (rx + 1, cy + 2)], "b")
    mx = 7 + dx
    my = cy + 2
    if mouth == "calm":
        s.put(mx, my, "m")
        s.put(mx + 1, my, "m")
    elif mouth == "smile":
        s.px_at([(mx - 1, my), (mx, my + 1), (mx + 1, my + 1), (mx + 2, my)],
                "m")
    elif mouth == "open":
        s.rect(mx, my, mx + 1, my + 1, "m")
    elif mouth == "boo":
        s.rect(mx - 1, my, mx + 2, my + 2, "m")
        s.hline(my + 2, mx, mx + 1, "P")
    elif mouth == "chomp":
        s.px_at([(mx, my), (mx + 1, my + 1)], "m")
    elif mouth == "tongue":
        s.hline(my, mx, mx + 1, "m")
        s.put(mx + 1, my + 1, "P")


def arms(s, kind, top=1, dx=0):
    """Little nub arms. Drawn as sheet so the outline wraps them."""
    y = top + 7
    left, right = BODY_X - 1 + dx, BODY_X + WIDTH + dx
    if kind == "rest":
        s.px_at([(left, y), (right, y)], "v")
    elif kind == "up":
        s.px_at([(left, y - 3), (left, y - 4), (right, y - 3), (right, y - 4)],
                "w")
    elif kind == "wave_l":
        s.px_at([(left, y - 3), (left - 1, y - 4), (right, y)], "w")
    elif kind == "wave_r":
        s.px_at([(left, y), (right, y - 3), (right + 1, y - 4)], "w")
    elif kind == "front":
        pass


def finish(s):
    s.outline(INK)
    return s


def pose(frame=0, eyes="open", mouth="calm", arm="rest", top=1, hem=11,
         lean=0, squash=0, wisp=0, blush=True, fdx=0, fdy=0, dy=0):
    s = sheet(frame, top, hem, lean, squash, wisp)
    arms(s, arm, top)
    s = finish(s)
    face(s, eyes, mouth, blush, dx=fdx, dy=fdy + squash,
         top=top)
    return s.shift(0, dy) if dy else s


def cookie(s, x, y, bitten=False):
    c = Sprite(SIZE, SIZE)
    c.rect(x, y, x + 2, y + 1, "c")
    c.put(x + 1, y, "C")
    if bitten:
        c.put(x + 2, y, ".")
        c.px[c.index(x + 2, y)] = "."
    c.outline(INK)
    s.paste(c)


def frames():
    F = {}
    bob = [0, 0, 1, 1]
    for i in range(4):
        F["idle_%d" % i] = pose(i, dy=bob[i])
        F["sit_%d" % i] = pose(i, eyes="look" if i in (1, 2) else "open",
                               dy=bob[i])
        F["fly_%d" % i] = pose(i, lean=1, wisp=1 + (i % 2), fdx=1,
                               arm="rest", hem=11)
        F["walk_%d" % i] = F["fly_%d" % i]
        F["run_%d" % i] = pose(i, lean=1, wisp=2 + (i % 2), fdx=1,
                               eyes="wide", mouth="open")
        F["spook_%d" % i] = pose(i, eyes="angry", mouth="boo", arm="up",
                                 top=0 if i in (1, 2) else 1)
        F["pat_%d" % i] = pose(i, eyes="happy", mouth="smile",
                               arm="wave_l" if i % 2 == 0 else "wave_r")
        F["sleep_%d" % i] = pose(i, eyes="shut", mouth="calm",
                                 squash=1 if i in (1, 2) else 0, dy=1)
        F["dance_%d" % i] = pose(i, eyes="happy", mouth="smile",
                                 arm="wave_l" if i < 2 else "wave_r",
                                 dy=(0, -1, 0, -1)[i])
        F["dizzy_%d" % i] = pose(i, eyes="dizzy", mouth="tongue",
                                 fdx=(-1, 0, 1, 0)[i])
        eat = pose(i, eyes="happy" if i % 2 else "open",
                   mouth="chomp" if i % 2 else "open")
        cookie(eat, 7, 10, bitten=i >= 2)
        F["eat_%d" % i] = eat
        F["drag_%d" % i] = pose(i, eyes="wide", mouth="open", arm="up",
                                top=1, hem=12 if i % 2 else 11)
    F["blink_0"] = pose(0, eyes="blink")
    F["happy_0"] = pose(0, eyes="happy", mouth="smile", squash=1)
    F["happy_1"] = pose(1, eyes="happy", mouth="smile", arm="up", dy=-1)
    F["happy_2"] = pose(2, eyes="happy", mouth="open", arm="up", dy=-2)
    F["happy_3"] = pose(3, eyes="happy", mouth="smile", dy=-1)
    F["pet_0"] = pose(0, eyes="happy", mouth="smile", squash=1)
    F["pet_1"] = pose(1, eyes="happy", mouth="smile", squash=1, fdx=1)
    F["yawn_0"] = pose(0, eyes="blink")
    F["yawn_1"] = pose(1, eyes="shut", mouth="boo", top=0)
    F["yawn_2"] = pose(2, eyes="shut", mouth="boo", top=0)
    F["yawn_3"] = pose(3, eyes="blink", squash=1)
    F["alert_0"] = pose(0, eyes="wide", mouth="open", top=0)
    F["alert_1"] = pose(1, eyes="wide", mouth="open", arm="up", top=0)
    F["sulk_0"] = pose(0, eyes="angry", mouth="calm", blush=False)
    F["sulk_1"] = pose(1, eyes="angry", mouth="calm", blush=False)
    F["fall_0"] = pose(0, eyes="wide", mouth="boo", arm="up")
    F["fall_1"] = pose(2, eyes="wide", mouth="boo", arm="up")
    F["jump_0"] = pose(0, eyes="happy", mouth="smile", squash=1)
    F["jump_1"] = pose(1, eyes="open", mouth="open", arm="up", top=0)
    return F
