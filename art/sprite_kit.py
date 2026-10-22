"""sprite_kit.py - shared helpers for the 16x16 companion sprites.

Every companion is built the same way: a handful of hand-drawn part grids
(head, body, tail, legs...) are composited back to front, and each part gets
its own 1px ink outline before it is pasted. Per-part outlining is what puts a
dark separator between a near paw and the belly behind it, which is most of
what makes a 16px sprite readable at all.

Conventions
-----------
* 16x16 canvas, facing right; the app mirrors for facing left.
* Bottom-anchored: the lowest ink row is row 15, which is the ground line.
* Grids use palette keys, one char per pixel, '.' for transparent.
"""

from pixelart import Sprite

SIZE = 16
INK = "#"


def grid(rows, label="grid"):
    """Validate a hand-drawn grid: a ragged row is a broken sprite."""
    rows = tuple(rows)
    width = len(rows[0]) if rows else 0
    bad = ["%d %r" % (len(r), r) for r in rows if len(r) != width]
    if bad:
        raise ValueError("%s wants width %d: %s" % (label, width, "; ".join(bad)))
    return rows


def part(rows, x, y, ink=INK, outline=True):
    """One finished part on a full canvas: stamped, then outlined."""
    s = Sprite(SIZE, SIZE)
    s.stamp(rows, x, y)
    if outline:
        s.outline(ink)
    return s


def compose(*parts):
    """Paste parts back to front onto a fresh canvas."""
    out = Sprite(SIZE, SIZE)
    for p in parts:
        if p is None:
            continue
        out.paste(p)
    return out


def overlay(sprite, rows, x, y):
    """Stamp un-outlined detail (eyes, mouths, stripes) on top of a sprite."""
    sprite.stamp(rows, x, y)
    return sprite


def ground(sprite):
    """Shift a sprite down so its lowest pixel sits on row 15."""
    box = sprite.box()
    if box is None:
        return sprite
    return sprite.shift(0, (SIZE - 1) - box[3])


def recolor(sprite, mapping):
    out = sprite.clone()
    out.px = [mapping.get(k, k) for k in out.px]
    return out
