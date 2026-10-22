"""sprites_bots.py - the two robots, 16x16.

    jarvis   a round hover-bot: white shell, visor screen face, antenna,
             and a thruster flame instead of legs.
    ultron   a lanky walker: angular crested head, red slit eyes, a glowing
             chest core, arms and legs.

Both have screen faces, so expressions are drawn as glowing pixels on a dark
panel -- which means they can show things a fur face can't: heart eyes, a
loading bar when they yawn, a battery filling up when they "eat".
"""

from pixelart import Sprite, hexc
from sprite_kit import SIZE, INK

JARVIS = {
    ".": (0, 0, 0, 0),
    "#": hexc("#1b2233"),   # ink
    "m": hexc("#dfe7f3"),   # shell
    "M": hexc("#ffffff"),   # shell, lit
    "n": hexc("#93a6c2"),   # shell, shade
    "N": hexc("#62748f"),   # metal, dark
    "B": hexc("#3f86ea"),   # accent blue
    "D": hexc("#2a5bb0"),   # accent, shade
    "k": hexc("#0f1626"),   # screen
    "c": hexc("#67f3ff"),   # screen glow
    "C": hexc("#2f8fa8"),   # screen glow, dim
    "h": hexc("#ff6fa8"),   # heart
    "a": hexc("#ffd34d"),   # antenna light
    "A": hexc("#b98a1c"),   # antenna light, off
    "y": hexc("#fff1a1"),   # flame core
    "r": hexc("#ffa53d"),   # flame
    "q": hexc("#69c8ff"),   # flame, blue tip
    "g": hexc("#6cf08a"),   # battery
}

ULTRON = {
    ".": (0, 0, 0, 0),
    "#": hexc("#14141a"),   # ink
    "m": hexc("#8c919c"),   # metal
    "M": hexc("#c6cbd4"),   # metal, lit
    "n": hexc("#5b5f6a"),   # metal, shade
    "N": hexc("#3d4049"),   # metal, dark
    "B": hexc("#b3262b"),   # accent red
    "D": hexc("#7a171c"),   # accent, shade
    "k": hexc("#0e0e13"),   # face plate
    "c": hexc("#ff3b3b"),   # eye glow
    "C": hexc("#8f1f24"),   # eye glow, dim
    "h": hexc("#ff3b3b"),   # "heart" (still red. still menacing.)
    "a": hexc("#ff7a5c"),   # crest light
    "A": hexc("#7a2a22"),   # crest light, off
    "y": hexc("#ffd0c4"),   # core, hot
    "r": hexc("#ff4a3a"),   # core
    "q": hexc("#ff8a6a"),   # spark
    "g": hexc("#ff3b3b"),   # battery (red, obviously)
}

PALETTE = JARVIS
PALETTES = {"jarvis": JARVIS, "ultron": ULTRON}


def palette(kind="jarvis"):
    return PALETTES.get(kind, JARVIS)


# =====================================================================
# screen faces: drawn in screen-local coords, (0, 0) = panel top-left
# =====================================================================

def _glyph(s, ox, oy, rows, key):
    for dy, row in enumerate(rows):
        for dx, ch in enumerate(row):
            if ch == "x":
                s.put(ox + dx, oy + dy, key)


EYE_GLYPHS = {
    "open":  ("x", "x"),
    "wide":  ("xx", "xx"),
    "blink": ("..", "xx"),
    "happy": (".x.", "x.x"),
    "heart": ("x.x", "xxx", ".x."),
    "dizzy": ("x.x", ".x.", "x.x"),
    "angry": ("x..", ".xx"),
    "sleep": ("...", "xxx"),
    "look":  (".x", ".x"),
    "slit":  ("xx",),
}


def screen_face(s, x, y, w, h, expr, frame=0, kind="jarvis"):
    """Draw an expression onto the dark panel at (x, y, w, h)."""
    glow, dim = "c", "C"
    if expr == "loading":
        # a yawn, robot style: a progress bar crawling across
        s.hline(y + h // 2, x + 1, x + w - 2, dim)
        s.hline(y + h // 2, x + 1, x + 1 + min(w - 3, frame * 2 + 1), glow)
        return
    if expr == "battery":
        # "eating" = charging: a battery that fills per frame
        bx, by = x + w // 2 - 3, y + h // 2 - 1
        s.rect(bx, by, bx + 5, by + 2, dim)
        s.put(bx + 6, by + 1, dim)
        for i in range(min(5, frame + 2)):
            s.vline(bx + i, by, by + 2, "g")
        return
    if expr == "alert":
        s.vline(x + w // 2, y, y + h - 3, glow)
        s.put(x + w // 2, y + h - 1, glow)
        return
    if expr == "scan":
        col = x + (frame * 3) % w
        s.vline(col, y, y + h - 1, dim)
        _glyph(s, x + 2, y + 1, EYE_GLYPHS["open"], glow)
        _glyph(s, x + w - 3, y + 1, EYE_GLYPHS["open"], glow)
        return
    rows = EYE_GLYPHS.get(expr, EYE_GLYPHS["open"])
    gw = len(rows[0])
    key = "h" if expr == "heart" else (dim if expr == "sleep" else glow)
    if kind == "ultron":
        left = x if gw > 1 else x + 1
        right = x + w - gw if gw > 1 else x + w - 2
        top = y + max(0, (h - len(rows)) // 2)
    else:
        left = x + {1: 2, 2: 1}.get(gw, 0)
        right = x + w - {1: 3, 2: 3}.get(gw, 3)
        top = y + max(0, (h - len(rows)) // 2)
    if expr == "angry":
        _glyph(s, left, top, rows, key)
        _glyph(s, right, top, tuple(r[::-1] for r in rows), key)
    else:
        _glyph(s, left, top, rows, key)
        _glyph(s, right, top, rows, key)


# =====================================================================
# JARVIS
# =====================================================================

def jarvis_shell(lean=0, squash=0):
    s = Sprite(SIZE, SIZE)
    top = 3 + squash
    rows = [6, 10, 12, 12, 12, 12, 12, 12, 10 if not squash else 12, 6]
    rows = rows[:10 - squash]
    for i, w in enumerate(rows):
        x0 = 2 + (12 - w) // 2 + (lean if i < 3 else 0)
        s.hline(top + i, x0, x0 + w - 1, "m")
    s.edge_light("m", "M")
    s.edge_shadow("mM", "n")
    # accent belt
    belt = top + len(rows) - 3
    for x in range(SIZE):
        if s.get(x, belt) in "mMn":
            s.put(x, belt, "B" if s.get(x, belt) != "n" else "D")
    return s, top


def jarvis(frame=0, expr="open", flame=1, lean=0, squash=0, arm="rest",
           antenna_on=True, dy=0, antenna_bend=0):
    s, top = jarvis_shell(lean, squash)
    # antenna
    ax = 8 + lean
    s.put(ax + antenna_bend, top - 2, "a" if antenna_on else "A")
    s.put(ax, top - 1, "N")
    # thruster
    base = top + 10 - squash
    s.hline(base, 6, 9, "N")
    flames = {
        0: [],
        1: [("ry", 7, 8)],
        2: [("ry", 7, 8), ("q", 7, 8)],
        3: [("ry", 6, 9), ("ry", 7, 8), ("q", 7, 8)],
    }
    out = Sprite(SIZE, SIZE)
    # side fins / arms
    arm_y = top + 5
    if arm == "rest":
        s.px_at([(1, arm_y), (14, arm_y)], "B")
    elif arm == "up":
        s.px_at([(1, arm_y - 1), (1, arm_y - 2), (14, arm_y - 1),
                 (14, arm_y - 2)], "B")
    elif arm == "wave":
        s.px_at([(1, arm_y), (14, arm_y - 1), (15, arm_y - 2)], "B")
    elif arm == "punch":
        s.px_at([(1, arm_y), (14, arm_y), (15, arm_y)], "B")
    s.outline(INK)
    out.paste(s)
    # screen (drawn after outline so it stays crisp)
    sx, sy, sw, sh = 4 + lean, top + 2, 8, 5
    out.rect(sx, sy, sx + sw - 1, sy + sh - 1, "k")
    out.put(sx, sy, "n")
    out.put(sx + sw - 1, sy, "n")
    out.put(sx, sy + sh - 1, "n")
    out.put(sx + sw - 1, sy + sh - 1, "n")
    screen_face(out, sx, sy, sw, sh, expr, frame, "jarvis")
    # flame after everything: it is light, it gets no ink
    level = flames.get(flame, [])
    flicker = frame % 2
    for i, (keys, x0, x1) in enumerate(level):
        y = base + 1 + i
        if y >= SIZE:
            break
        for x in range(x0, x1 + 1):
            out.put(x, y, keys[(x + flicker) % len(keys)])
    return out.shift(0, dy) if dy else out


def jarvis_frames():
    F = {}
    hover = [0, 0, 1, 1]
    for i in range(4):
        fl = 1 + (i % 2)
        F["sit_%d" % i] = jarvis(i, "open", flame=fl, dy=hover[i],
                                 antenna_on=i < 2)
        F["idle_%d" % i] = jarvis(i, "look" if i < 2 else "open", flame=fl,
                                  dy=hover[i])
        F["walk_%d" % i] = jarvis(i, "open", flame=2 + (i % 2), lean=1,
                                  antenna_bend=-1)
        F["run_%d" % i] = jarvis(i, "wide", flame=3, lean=1, antenna_bend=-1,
                                 arm="up" if i % 2 else "rest")
        F["stalk_%d" % i] = jarvis(i, "scan", flame=1, squash=1)
        F["groom_%d" % i] = jarvis(i, "scan", flame=1 + (i % 2),
                                   arm="wave" if i % 2 else "rest")
        F["swat_%d" % i] = jarvis(i, "angry" if i in (1, 2) else "open",
                                  flame=2, arm="punch" if i in (1, 2) else "rest")
        F["sleep_%d" % i] = jarvis(i, "sleep", flame=0, squash=1,
                                   antenna_on=False, dy=2 - hover[i])
        F["climb_%d" % i] = jarvis(i, "open", flame=3, arm="up")
        F["drag_%d" % i] = jarvis(i, "wide" if i % 2 else "dizzy", flame=0,
                                  arm="up", antenna_bend=(-1, 0, 1, 0)[i])
        F["eat_%d" % i] = jarvis(i, "battery", flame=1, squash=1, dy=1)
        F["dance_%d" % i] = jarvis(i, "happy", flame=2, dy=(0, -1, 0, -1)[i],
                                   arm="wave" if i < 2 else "up",
                                   antenna_bend=(-1, 0, 1, 0)[i])
        F["dizzy_%d" % i] = jarvis(i, "dizzy", flame=1,
                                   antenna_bend=(-1, 0, 1, 0)[i])
        F["yawn_%d" % i] = jarvis(i, "loading", flame=1, antenna_on=i % 2 == 0)
    F["blink_0"] = jarvis(0, "blink", flame=1)
    F["happy_0"] = jarvis(0, "happy", flame=1, squash=1, dy=1)
    F["happy_1"] = jarvis(1, "happy", flame=3, arm="up", dy=-1)
    F["happy_2"] = jarvis(2, "happy", flame=3, arm="up", dy=-2)
    F["happy_3"] = jarvis(3, "happy", flame=2, dy=-1)
    F["pet_0"] = jarvis(0, "heart", flame=1)
    F["pet_1"] = jarvis(1, "heart", flame=2, dy=1)
    F["alert_0"] = jarvis(0, "alert", flame=2, arm="up")
    F["alert_1"] = jarvis(1, "wide", flame=2, arm="up", dy=-1)
    F["sulk_0"] = jarvis(0, "angry", flame=1, antenna_on=False)
    F["sulk_1"] = jarvis(1, "angry", flame=1, antenna_on=False)
    F["jump_0"] = jarvis(0, "happy", flame=1, squash=1)
    F["jump_1"] = jarvis(1, "wide", flame=3, arm="up")
    F["fall_0"] = jarvis(0, "wide", flame=0, arm="up")
    F["fall_1"] = jarvis(1, "dizzy", flame=0, arm="up")
    return F


# =====================================================================
# ULTRON
# =====================================================================

U_HEAD = (
    "..a.MM.a..",
    ".MMMmmmnn.",
    "MMkkkkkknn",
    "Mmkkkkkknn",
    "Mmkkkkkkmn",
    ".mmnnnnmn.",
)


def ultron(frame=0, expr="slit", stride=0, arm_l=0, arm_r=0, crouch=0,
           dy=0, crest_on=True, core=1, head_dx=0, arms_up=False):
    s = Sprite(SIZE, SIZE)
    hy = 1 + crouch
    # torso
    ty = 7 + crouch
    torso = (
        "MMMmmmmmnn",
        ".MmmBBmmn.",
        "..mmmmmn..",
        "...mNNn...",
    )
    s.stamp(torso, 3, ty)
    # legs
    leg_top = ty + 4
    for x, off, key in ((6, stride, "m"), (9, -stride, "n")):
        for y in range(leg_top, 14):
            s.put(x + (off if y == 13 else 0), y, key)
        s.put(x + off, 14, "N")
        s.put(x + off + 1, 14, "N")
    # arms
    for x, swing, key in ((2, arm_l, "m"), (13, arm_r, "n")):
        if arms_up:
            s.vline(x, ty - 3, ty, key)
            s.put(x, ty - 4, "N")
        else:
            s.vline(x, ty, ty + 3, key)
            s.put(x + swing, ty + 4, "N")
    s.outline(INK)
    head = Sprite(SIZE, SIZE)
    head.stamp(U_HEAD, 3 + head_dx, hy)
    if not crest_on:
        head.remap("a", "A")
    head.outline(INK)
    s.paste(head)
    # face plate glyphs (plate is 6x3 at (5, hy+2))
    screen_face(s, 5 + head_dx, hy + 2, 6, 3, expr, frame, "ultron")
    # glowing core
    cx = 7
    s.put(cx, ty + 1, "r" if core else "D")
    s.put(cx + 1, ty + 1, "y" if core > 1 else ("r" if core else "D"))
    return s.shift(0, dy) if dy else s


def ultron_frames():
    F = {}
    for i in range(4):
        core = 2 if i % 2 else 1
        F["sit_%d" % i] = ultron(i, "slit", core=core, crest_on=i < 3)
        F["idle_%d" % i] = ultron(i, "look" if i < 2 else "slit", core=core)
        stride = (0, 1, 0, -1)[i]
        F["walk_%d" % i] = ultron(i, "slit", stride=stride, arm_l=-stride,
                                  arm_r=stride)
        F["run_%d" % i] = ultron(i, "angry", stride=stride, arm_l=-stride,
                                 arm_r=stride, head_dx=1, core=2)
        F["stalk_%d" % i] = ultron(i, "angry", stride=stride, crouch=1,
                                   head_dx=1)
        F["groom_%d" % i] = ultron(i, "scan", core=core)
        F["swat_%d" % i] = ultron(i, "angry", arm_r=1 if i in (1, 2) else 0,
                                  core=2 if i in (1, 2) else 1,
                                  arms_up=i == 1)
        F["sleep_%d" % i] = ultron(i, "sleep", crouch=1, crest_on=False,
                                   core=0 if i < 2 else 1)
        F["climb_%d" % i] = ultron(i, "slit", arms_up=True,
                                   stride=(0, 1, 0, -1)[i])
        F["drag_%d" % i] = ultron(i, "wide" if i % 2 else "angry",
                                  arms_up=True, stride=(1, -1, 1, -1)[i])
        F["eat_%d" % i] = ultron(i, "battery", crouch=1, core=2)
        F["dance_%d" % i] = ultron(i, "happy", stride=(1, 0, -1, 0)[i],
                                   arms_up=i % 2 == 0, dy=(0, -1, 0, -1)[i],
                                   core=2)
        F["dizzy_%d" % i] = ultron(i, "dizzy", arm_l=(0, 1, 0, -1)[i],
                                   arm_r=(0, -1, 0, 1)[i])
        F["yawn_%d" % i] = ultron(i, "loading", crest_on=i % 2 == 0)
    F["blink_0"] = ultron(0, "blink")
    F["happy_0"] = ultron(0, "happy", crouch=1)
    F["happy_1"] = ultron(1, "happy", arms_up=True, dy=-1, core=2)
    F["happy_2"] = ultron(2, "happy", arms_up=True, dy=-2, core=2)
    F["happy_3"] = ultron(3, "happy", dy=-1)
    F["pet_0"] = ultron(0, "heart", core=2)
    F["pet_1"] = ultron(1, "heart", core=2, crouch=1)
    F["alert_0"] = ultron(0, "alert", core=2)
    F["alert_1"] = ultron(1, "wide", arms_up=True, core=2, dy=-1)
    F["sulk_0"] = ultron(0, "angry", crest_on=False)
    F["sulk_1"] = ultron(1, "angry", crest_on=False, crouch=1)
    F["jump_0"] = ultron(0, "angry", crouch=1)
    F["jump_1"] = ultron(1, "wide", arms_up=True, stride=1, dy=-1)
    F["fall_0"] = ultron(0, "wide", arms_up=True, stride=1)
    F["fall_1"] = ultron(1, "dizzy", arms_up=True, stride=-1)
    return F


def frames(kind="jarvis"):
    return ultron_frames() if kind == "ultron" else jarvis_frames()
