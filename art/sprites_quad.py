"""sprites_quad.py - the four-legged rig shared by the cat and the shiba.

A species is a `Species` record: palette, a head grid with known face anchor
points, tail grids, back markings and a couple of colour keys. Every pose
below (sit, walk, run, stalk, sleep, groom, ...) is built from those parts, so
the cat and the shiba move identically but read as different animals: the
silhouette differences live in the head, ears, tail and markings.

Head grids are 9 wide by 8 tall, front-on, with the face laid out on a fixed
grid so expressions can be stamped on:

    eyes   3x2 stamps at (1, 4) and (5, 4)
    nose   (4, 6)
    mouth  row 7, columns 3-5
"""

from pixelart import Sprite
from sprite_kit import SIZE, INK, part

KEEP = "."     # a stamp pixel that leaves whatever is underneath


class Species:
    def __init__(self, name, palette, heads, tails, body_marks, fur="o",
                 light="O", shade="d", belly="w", belly_lo="W", paw="w",
                 paw_far="W", tongue="P", cheek="b", eye="e", back_head=None,
                 sit_tail=None, sleep_tail=None, nose="p", tail_dx=0,
                 tail_drop=0):
        self.name = name
        self.palette = palette
        self.heads = heads              # {"up": grid, "flat": grid, "perk": grid}
        self.tails = tails              # list of 2-wide grids, used as a cycle
        self.body_marks = body_marks    # list of (x, y, key) on the walking body
        self.fur, self.light, self.shade = fur, light, shade
        self.belly, self.belly_lo = belly, belly_lo
        self.paw, self.paw_far = paw, paw_far
        self.tongue, self.cheek, self.eye, self.nose = tongue, cheek, eye, nose
        self.back_head = back_head
        self.sit_tail = sit_tail
        self.sleep_tail = sleep_tail
        self.tail_dx, self.tail_drop = tail_dx, tail_drop


# =====================================================================
# faces
# =====================================================================

# Left eye stamp; the right eye is the mirror image. 'E' = eye ink.
EYES = {
    "open":   (".E.", ".E."),
    "wide":   ("EE.", "EE."),
    "blink":  ("...", "EE."),
    "shut":   ("...", "EEE"),
    "happy":  (".E.", "E.E"),
    "dizzy":  ("E.E", ".E."),
    "half":   ("...", ".E."),
    "look":   ("..E", "..E"),
    "angry":  ("E..", ".EE"),
}


def _mirror(rows):
    return tuple(r[::-1] for r in rows)


def face(sp, s, hx, hy, eyes="open", mouth="calm", blush=False):
    """Stamp eyes, nose and mouth onto a head already pasted at (hx, hy)."""
    left = EYES[eyes]
    right = _mirror(left)
    if eyes == "look":            # both eyes glance the same way (forward)
        right = left
    for rows, ex in ((left, 1), (right, 5)):
        for dy, row in enumerate(rows):
            for dx, key in enumerate(row):
                if key == "E":
                    s.put(hx + ex + dx, hy + 4 + dy, sp.eye)
    s.put(hx + 4, hy + 6, sp.nose)
    if mouth == "open":
        s.put(hx + 4, hy + 7, INK)
    elif mouth == "tongue":
        s.put(hx + 4, hy + 7, sp.tongue)
    elif mouth == "yawn":
        s.rect(hx + 3, hy + 6, hx + 5, hy + 7, INK)
        s.put(hx + 4, hy + 7, sp.tongue)
    elif mouth == "chomp":
        s.px_at([(hx + 3, hy + 7), (hx + 5, hy + 7)], INK)
    if blush:
        s.px_at([(hx + 1, hy + 6), (hx + 7, hy + 6)], sp.cheek)


def head(sp, hx, hy, eyes="open", mouth="calm", ears="up", blush=False):
    """Finished, outlined head part."""
    rows = sp.heads.get(ears) or sp.heads["up"]
    s = part(rows, hx, hy)
    face(sp, s, hx, hy, eyes, mouth, blush)
    return s


def back_of_head(sp, hx, hy):
    return part(sp.back_head, hx, hy)


# =====================================================================
# legs and bodies
# =====================================================================

def _leg(s, x, top, dx, key, foot, bottom=14):
    """A 1px leg from (x, top) to a foot at (x+dx, bottom)."""
    if top > bottom:
        return
    if dx == 0 or bottom - top < 2:
        s.vline(x, top, bottom - 1, key)
    else:
        # straight down first, then angle out: keeps the hip on the body
        s.put(x, top, key)
        s.line(x, top + 1, x + dx, bottom - 1, key)
    s.put(x + dx, bottom, foot)


def legs(sp, top, strides, xs=(3, 5, 9, 11), bottom=14):
    """Four legs, far legs first. strides = (back-far, back-near, front-far,
    front-near) foot offsets."""
    s = Sprite(SIZE, SIZE)
    keys = (sp.shade, sp.fur, sp.shade, sp.fur)
    feet = (sp.paw_far, sp.paw, sp.paw_far, sp.paw)
    for x, dx, key, foot in zip(xs, strides, keys, feet):
        _leg(s, x, top, dx, key, foot, bottom)
    return s


def _body_stand(sp, length=10):
    f, L, d, w = sp.fur, sp.light, sp.shade, sp.belly
    inner = length - 2
    return (
        "." + L * 2 + f * (inner - 2) + "." + "",
        L + f * (length - 2) + d,
        L + f * (length - 2) + d,
        "." + d * 2 + w * (inner - 4) + d * 2 + ".",
    )


def _fix(rows, width):
    return tuple(r.ljust(width, ".")[:width] for r in rows)


def stand_body(sp, s, x, y, length=10):
    rows = _fix(_body_stand(sp, length), length)
    s.stamp(rows, x, y)
    for mx, my, key in sp.body_marks:
        if mx < length - 1:
            s.put(x + mx, y + my, key)


def tail(sp, s, body_y, index, dx=0):
    """Tail rising from the rump of a body whose top row is `body_y`."""
    rows = sp.tails[index % len(sp.tails)]
    s.stamp(rows, sp.tail_dx + dx, body_y - len(rows) + sp.tail_drop)


def finish(silhouette, *overlays):
    """Outline the merged body silhouette, then paste outlined overlays."""
    silhouette.outline(INK)
    for over in overlays:
        if over is not None:
            silhouette.paste(over)
    return silhouette


# =====================================================================
# poses
# =====================================================================

WALK_STRIDES = [(0, 0, 0, 0), (1, -1, -1, 1), (0, 0, 0, 0), (-1, 1, 1, -1)]
RUN_STRIDES = [(2, 1, -1, -2), (1, 0, 0, -1), (-2, -1, 2, 1), (-1, 0, 1, 0)]
RUN_BOB = [1, 0, -1, 0]


def pose_walk(sp, f, eyes="open", mouth="calm"):
    bob = 1 if f in (0, 2) else 0
    s = Sprite(SIZE, SIZE)
    s.paste(legs(sp, 11 + bob, WALK_STRIDES[f]))
    tail(sp, s, 8 + bob, f // 2)
    stand_body(sp, s, 2, 8 + bob)
    return finish(s, head(sp, 6, 1 + bob, eyes, mouth))


def pose_run(sp, f, eyes="open", mouth="tongue"):
    bob = RUN_BOB[f]
    s = Sprite(SIZE, SIZE)
    s.paste(legs(sp, 11 + bob, RUN_STRIDES[f], xs=(3, 4, 9, 10)))
    tail(sp, s, 8 + bob, len(sp.tails) - 1)
    stand_body(sp, s, 2, 8 + bob, length=10)
    return finish(s, head(sp, 7, 2 + bob, eyes, mouth, ears="flat"))


def pose_stalk(sp, f):
    strides = [(0, 0, 0, 0), (0, -1, 1, 0), (0, 0, 0, 0), (-1, 0, 0, 1)][f]
    s = Sprite(SIZE, SIZE)
    s.paste(legs(sp, 12, strides))
    # tail held low and straight, tip twitching
    s.hline(10, 0, 2, sp.fur)
    s.put(0, 9 if f % 2 else 10, sp.light)
    stand_body(sp, s, 2, 10)
    eyes = "wide" if f in (1, 2) else "open"
    return finish(s, head(sp, 7, 4, eyes, "calm", ears="flat"))


def _sit_body(sp, wide=False):
    f, L, d, w, W = sp.fur, sp.light, sp.shade, sp.belly, sp.belly_lo
    return (
        "...%s%s%s%s%s." % (L, f, f, f, f),
        "..%s%s%s%s%s%s." % (L, f, f, f, w, w),
        ".%s%s%s%s%s%s%s." % (L, f, f, f, f, w, w),
        "%s%s%s%s%s%s%s%s." % (L, f, f, f, f, f, w, w),
        "%s%s%s%s%s%s%s%s." % (f, f, f, f, d, f, f, w),
        "%s%s%s%s%s%s%s%s." % (d, d, d, d, d, sp.paw, d, sp.paw),
    )


def sit_layers(sp, tail_index=0, dy=0, paws=True):
    """The seated silhouette (without head) as one un-outlined sprite."""
    s = Sprite(SIZE, SIZE)
    rows = _sit_body(sp)
    if not paws:
        rows = rows[:-1] + (rows[-1][:5] + sp.shade * 3 + ".",)
    s.stamp(rows, 3, 9 + dy)
    tails = sp.sit_tail or [("....oo", "ooooo.")]
    rows = tails[tail_index % len(tails)]
    s.stamp(rows, 0, 15 - len(rows) + dy)
    return s


def pose_sit(sp, f=0, eyes="open", mouth="calm", ears="up", blush=False,
             tail_index=None, head_dx=0, head_dy=0, dy=0):
    s = sit_layers(sp, f if tail_index is None else tail_index, dy)
    return finish(s, head(sp, 5 + head_dx, 2 + head_dy + dy, eyes, mouth, ears,
                          blush))


def pose_groom(sp, f):
    """Seated, licking a raised front paw."""
    s = sit_layers(sp, 0)
    lift = [2, 3, 2, 3][f]
    out = finish(s, head(sp, 5, 3 if f % 2 else 2, "shut",
                         "tongue" if f % 2 else "calm"))
    paw = Sprite(SIZE, SIZE)
    paw.vline(12, 13 - lift, 13, sp.fur)
    paw.put(12, 12 - lift, sp.paw)
    paw.put(11, 12 - lift, sp.paw)
    paw.outline(INK)
    out.paste(paw)
    return out


def pose_swat(sp, f):
    """Seated, the near front paw lashing out in front."""
    s = sit_layers(sp, 1, paws=f in (0, 3))
    eyes = "wide" if f in (1, 2) else "open"
    out = finish(s, head(sp, 5, 2, eyes, "open" if f == 2 else "calm",
                         ears="flat" if f == 2 else "up"))
    arm = Sprite(SIZE, SIZE)
    if f == 1:      # wind-up: paw raised by the cheek
        arm.vline(12, 10, 12, sp.fur)
        arm.put(12, 9, sp.paw)
    elif f == 2:    # strike: paw thrown forward
        arm.hline(11, 11, 14, sp.fur)
        arm.put(14, 10, sp.paw)
        arm.put(15, 11, sp.paw)
    if f in (1, 2):
        arm.outline(INK)
        out.paste(arm)
    return out


def pose_sleep(sp, frame):
    """Curled up loaf, head down on the paws, breathing."""
    f, L, d = sp.fur, sp.light, sp.shade
    s = Sprite(SIZE, SIZE)
    top = 10
    up = [0, 1, 1, 0][frame % 4]
    body = (
        "..%s%s%s%s%s%s.." % (L, L, f, f, f, f),
        ".%s%s%s%s%s%s%s%s." % (L, f, f, f, f, f, f, d),
        "%s%s%s%s%s%s%s%s%s%s" % (L, f, f, f, f, f, f, f, f, d),
        "%s%s%s%s%s%s%s%s%s%s" % (f, f, f, f, f, f, f, f, d, d),
        "%s%s%s%s%s%s%s%s%s." % (d, d, d, d, d, d, d, d, d),
    )
    if up:
        body = ("...%s%s%s%s.." % (L, f, f, f),) + body
    s.stamp(body, 1, top - up)
    for mx, my, key in sp.body_marks[:3]:
        s.put(1 + mx, top - up + 1 + my, key)
    st = sp.sleep_tail or ("oooooo",)
    s.stamp(st, 3, 14)
    hd = head(sp, 7, 7, "shut", "calm", ears="flat")
    return finish(s, hd)


def pose_climb(sp, f):
    """Back view, hugging the wall; paws reach alternately."""
    s = Sprite(SIZE, SIZE)
    reach = [0, 1, 0, -1][f]
    fur, L, d = sp.fur, sp.light, sp.shade
    body = (
        ".%s%s%s%s%s." % (L, fur, fur, fur, d),
        "%s%s%s%s%s%s%s" % (L, fur, fur, fur, fur, fur, d),
        "%s%s%s%s%s%s%s" % (L, fur, fur, fur, fur, fur, d),
        "%s%s%s%s%s%s%s" % (L, fur, fur, fur, fur, fur, d),
        ".%s%s%s%s%s." % (fur, fur, fur, fur, d),
    )
    s.stamp(body, 4, 7)
    # arms up, legs down, alternating
    s.vline(1, 5 - reach, 8, fur)
    s.vline(13, 5 + reach, 8, d)
    s.hline(8, 1, 4, fur)
    s.hline(8, 10, 13, d)
    s.put(1, 4 - reach, sp.paw)
    s.put(13, 4 + reach, sp.paw_far)
    s.vline(5, 12, 13 + reach, fur)
    s.vline(9, 12, 13 - reach, d)
    s.put(5, 14 + reach, sp.paw)
    s.put(9, 14 - reach, sp.paw_far)
    s.stamp(sp.tails[f % len(sp.tails)], 7, 11)
    for mx, my, key in sp.body_marks[:4]:
        s.put(5 + (mx % 5), 8 + (my % 3), key)
    return finish(s, back_of_head(sp, 3, 1 if f % 2 else 0))


def pose_drag(sp, f):
    """Held up by the scruff: dangling body, kicking legs."""
    s = Sprite(SIZE, SIZE)
    fur, L, d, w = sp.fur, sp.light, sp.shade, sp.belly
    body = (
        ".%s%s%s%s." % (L, fur, fur, d),
        "%s%s%s%s%s%s" % (L, fur, w, w, fur, d),
        "%s%s%s%s%s%s" % (L, fur, w, w, fur, d),
        "%s%s%s%s%s%s" % (L, fur, fur, fur, fur, d),
        ".%s%s%s%s." % (fur, fur, fur, d),
    )
    s.stamp(body, 5, 8)
    kick = [0, 1, 0, -1][f]
    # front legs out to the sides, back legs dangling
    s.put(4, 9, fur)
    s.put(3, 10 + (1 if kick > 0 else 0), sp.paw)
    s.put(11, 9, d)
    s.put(12, 10 + (1 if kick < 0 else 0), sp.paw_far)
    s.vline(6, 13, 13 + (1 if kick >= 0 else 0), fur)
    s.vline(9, 13, 13 + (1 if kick <= 0 else 0), d)
    s.put(6, 14 + (1 if kick >= 0 else 0), sp.paw)
    s.put(9, 14 + (1 if kick <= 0 else 0), sp.paw_far)
    sway = [0, 1, 0, 1][f]
    s.stamp(sp.tails[0], 11 + sway, 11)
    return finish(s, head(sp, 3, 1, "wide" if f % 2 else "open",
                          "open", ears="flat"))


def pose_jump(sp, f):
    """0: coiled crouch, 1: stretched launch."""
    s = Sprite(SIZE, SIZE)
    if f == 0:
        s.paste(legs(sp, 12, (0, 0, 0, 0)))
        tail(sp, s, 10, 0)
        stand_body(sp, s, 2, 10)
        return finish(s, head(sp, 6, 4, "wide", "calm", ears="flat"))
    # launch: back legs trailing, front legs reaching forward
    s.paste(legs(sp, 10, (-2, -2, 2, 3), bottom=12))
    tail(sp, s, 7, 1)
    stand_body(sp, s, 2, 7)
    return finish(s, head(sp, 7, 0, "open", "open"))


def pose_fall(sp, f):
    """Spread-eagle, all four legs out, eyes like saucers."""
    s = Sprite(SIZE, SIZE)
    spread = f % 2
    stand_body(sp, s, 3, 7)
    fur, d = sp.fur, sp.shade
    for x0, x1, key, foot in ((4, 2 - spread, d, sp.paw_far),
                              (5, 4 - spread, fur, sp.paw),
                              (10, 12 + spread, d, sp.paw_far),
                              (11, 13 + spread, fur, sp.paw)):
        s.line(x0, 11, x1, 12, key)
        s.put(x1, 13, foot)
    tail(sp, s, 7 - spread, 0, dx=1)
    return finish(s, head(sp, 6, 1, "wide", "open", ears="flat"))


def pose_eat(sp, f, bowl):
    """Crouched at a bowl, head dipping and chomping."""
    s = Sprite(SIZE, SIZE)
    s.paste(legs(sp, 12, (0, 0, 0, 0), xs=(2, 4, 7, 9)))
    tail(sp, s, 10, f // 2)
    stand_body(sp, s, 1, 10, length=9)
    dip = [0, 1, 0, 1][f]
    out = finish(s, head(sp, 6, 5 + dip, "shut" if dip else "happy",
                         "chomp" if dip else "calm"))
    out.paste(part(bowl, 12, 12))
    return out


def pose_dance(sp, f):
    """Seated, waving one paw then the other, bopping to a beat."""
    s = sit_layers(sp, f, paws=True)
    tilt = [-1, 0, 1, 0][f]
    out = finish(s, head(sp, 5 + tilt, 2 + (f % 2), "happy", "open",
                         blush=True))
    arm = Sprite(SIZE, SIZE)
    if f == 0:
        arm.vline(13, 9, 11, sp.fur)
        arm.put(13, 8, sp.paw)
    elif f == 2:
        arm.vline(3, 9, 11, sp.shade)
        arm.put(3, 8, sp.paw_far)
    if f in (0, 2):
        arm.outline(INK)
        out.paste(arm)
    return out.shift(tilt, 0)


def shifted(sprite, dy):
    return sprite.shift(0, dy) if dy else sprite


def build(sp, bowl):
    """Every frame for one quadruped species."""
    F = {}
    for i in range(4):
        F["sit_%d" % i] = pose_sit(sp, i, eyes="open")
    F["idle_0"] = pose_sit(sp, 0, eyes="look")
    F["idle_1"] = pose_sit(sp, 1, eyes="look", head_dx=1)
    F["blink_0"] = pose_sit(sp, 0, eyes="blink")
    for i in range(4):
        F["walk_%d" % i] = pose_walk(sp, i)
        F["run_%d" % i] = pose_run(sp, i)
        F["stalk_%d" % i] = pose_stalk(sp, i)
        F["groom_%d" % i] = pose_groom(sp, i)
        F["swat_%d" % i] = pose_swat(sp, i)
        F["sleep_%d" % i] = pose_sleep(sp, i)
        F["climb_%d" % i] = pose_climb(sp, i)
        F["drag_%d" % i] = pose_drag(sp, i)
        F["eat_%d" % i] = pose_eat(sp, i, bowl)
        F["dance_%d" % i] = pose_dance(sp, i)
    for i in range(2):
        F["jump_%d" % i] = pose_jump(sp, i)
        F["fall_%d" % i] = pose_fall(sp, i)
    # happy hop: squash, launch, peak, settle
    F["happy_0"] = pose_sit(sp, 0, "happy", "open", blush=True, dy=1, head_dy=0)
    F["happy_1"] = shifted(pose_sit(sp, 1, "happy", "open", blush=True), -2)
    F["happy_2"] = shifted(pose_sit(sp, 2, "happy", "open", ears="perk",
                                    blush=True), -3)
    F["happy_3"] = shifted(pose_sit(sp, 3, "happy", "open", blush=True), -1)
    # petted: eyes closed in bliss, head leaning into the hand
    F["pet_0"] = pose_sit(sp, 0, "happy", "calm", ears="flat", blush=True)
    F["pet_1"] = pose_sit(sp, 0, "happy", "calm", ears="flat", blush=True,
                          head_dx=1, head_dy=1)
    # dizzy: swirly eyes, head wobbling
    for i, dx in enumerate((-1, 0, 1, 0)):
        F["dizzy_%d" % i] = pose_sit(sp, i, "dizzy", "open", ears="flat",
                                     head_dx=dx)
    # yawn: build-up, wide open, stretch, settle
    F["yawn_0"] = pose_sit(sp, 0, "half", "calm")
    F["yawn_1"] = pose_sit(sp, 0, "shut", "yawn", ears="flat", head_dy=-1)
    F["yawn_2"] = pose_sit(sp, 0, "shut", "yawn", ears="flat", head_dy=-1)
    F["yawn_3"] = pose_sit(sp, 0, "blink", "calm")
    # alert: ears up, eyes wide, a hop in the head
    F["alert_0"] = pose_sit(sp, 0, "wide", "calm", ears="perk")
    F["alert_1"] = pose_sit(sp, 1, "wide", "open", ears="perk", head_dy=-1)
    # sulking / annoyed
    F["sulk_0"] = pose_sit(sp, 0, "angry", "calm", ears="flat")
    F["sulk_1"] = pose_sit(sp, 1, "angry", "calm", ears="flat")
    return F
