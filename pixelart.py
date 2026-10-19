"""pixelart.py - a strict little pixel-art engine.

A sprite is a grid of palette keys (one char per pixel) plus a palette that
maps keys to RGBA. Everything here is integer-snapped on purpose: no
antialiasing, no sub-pixel shapes, no half-lit edge pixels. A 1px outline is
1px, a 5px circle is a 5px circle, and a diagonal is drawn the way a person
with a pencil tool would draw it.

The three-tone look used by every sprite in this project comes from two
automatic passes:

    edge_light(colors, hi)     top/left rim of a shape gets the highlight
    edge_shadow(colors, lo)    bottom/right rim gets the shade

so a body is drawn once in its base colour and the lighting is derived from
its own silhouette. `outline(ink)` then wraps the result in a 1px dark border.

Writing frames this way keeps a whole animation set consistent: every frame is
built from the same handful of shapes with integer offsets, which is what makes
a walk cycle read as one cat moving rather than twelve drawings of a cat.
"""

import math
import os
import struct
import zlib

TRANSPARENT = "."


class Sprite:
    """A char grid. Every drawing call is clipped to the canvas."""

    __slots__ = ("w", "h", "px")

    def __init__(self, w=24, h=24, fill=TRANSPARENT):
        self.w = w
        self.h = h
        self.px = [fill] * (w * h)

    # ---- basics -------------------------------------------------------
    def index(self, x, y):
        return int(y) * self.w + int(x)

    def inside(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, x, y):
        if not self.inside(x, y):
            return TRANSPARENT
        return self.px[self.index(x, y)]

    def put(self, x, y, ch):
        if ch == TRANSPARENT:
            return
        if self.inside(x, y):
            self.px[self.index(x, y)] = ch

    def clone(self):
        copy = Sprite(self.w, self.h)
        copy.px = list(self.px)
        return copy

    def clear(self):
        self.px = [TRANSPARENT] * (self.w * self.h)

    # ---- primitives ---------------------------------------------------
    def hline(self, y, x0, x1, ch):
        if x1 < x0:
            x0, x1 = x1, x0
        for x in range(int(x0), int(x1) + 1):
            self.put(x, int(y), ch)

    def vline(self, x, y0, y1, ch):
        if y1 < y0:
            y0, y1 = y1, y0
        for y in range(int(y0), int(y1) + 1):
            self.put(int(x), y, ch)

    def rect(self, x0, y0, x1, y1, ch):
        for y in range(int(y0), int(y1) + 1):
            self.hline(y, x0, x1, ch)

    def px_at(self, points, ch):
        for x, y in points:
            self.put(x, y, ch)

    def line(self, x0, y0, x1, y1, ch):
        """Bresenham. Include both endpoints."""
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.put(x0, y0, ch)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def ellipse(self, cx, cy, rx, ry, ch):
        """Filled ellipse. cx/cy are pixel-centre coordinates (floats allowed).

        Each row is filled from ceil(cx-dx) to floor(cx+dx), which keeps shapes
        symmetric about their centre and never produces a lone pixel stub.
        """
        if rx <= 0 or ry <= 0:
            return
        for y in range(int(math.floor(cy - ry)), int(math.ceil(cy + ry)) + 1):
            t = (y - cy) / ry
            if abs(t) > 1.0:
                continue
            dx = rx * math.sqrt(max(0.0, 1.0 - t * t))
            self.hline(y, math.ceil(cx - dx - 1e-9), math.floor(cx + dx + 1e-9), ch)

    def disc(self, cx, cy, r, ch):
        self.ellipse(cx, cy, r, r, ch)

    def polygon(self, points, ch):
        """Filled convex polygon (triangle in practice) via edge half-spaces."""
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0, x1 = int(math.floor(min(xs))), int(math.ceil(max(xs)))
        y0, y1 = int(math.floor(min(ys))), int(math.ceil(max(ys)))

        def edge(a, b, c):
            return (c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])

        area = edge(points[0], points[1], points[2])
        if area == 0:
            return
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                pt = (x, y)
                w0 = edge(points[1], points[2], pt)
                w1 = edge(points[2], points[0], pt)
                w2 = edge(points[0], points[1], pt)
                inside = (w0 >= 0 and w1 >= 0 and w2 >= 0) if area > 0 \
                    else (w0 <= 0 and w1 <= 0 and w2 <= 0)
                if inside:
                    self.put(x, y, ch)

    def ring(self, cx, cy, rx, ry, ch):
        """One-pixel-wide ellipse outline."""
        fill = Sprite(self.w, self.h)
        fill.ellipse(cx, cy, rx, ry, ch)
        for y in range(self.h):
            for x in range(self.w):
                if fill.get(x, y) != ch:
                    continue
                if (fill.get(x - 1, y) == ch and fill.get(x + 1, y) == ch
                        and fill.get(x, y - 1) == ch and fill.get(x, y + 1) == ch):
                    continue
                self.put(x, y, ch)

    # ---- composition --------------------------------------------------
    def stamp(self, rows, x, y, ch=None):
        """Paste a list of strings. ' ' and '.' are holes unless `ch` is given."""
        for dy, row in enumerate(rows):
            for dx, key in enumerate(row):
                if key in (".", " "):
                    continue
                self.put(x + dx, y + dy, key if ch is None else ch)

    def paste(self, src, x=0, y=0, only=None, skip=None):
        """Paste `src` over this sprite.

        only: iterable of keys to take (None = everything non-transparent).
        skip: iterable of keys to leave alone.
        """
        for sy in range(src.h):
            for sx in range(src.w):
                key = src.get(sx, sy)
                if key == TRANSPARENT:
                    continue
                if only is not None and key not in only:
                    continue
                if skip is not None and key in skip:
                    continue
                self.put(x + sx, y + sy, key)

    def place(self, src, x=0, y=0, only=None):
        """Draw `src` only where this sprite is already non-empty."""
        for sy in range(src.h):
            for sx in range(src.w):
                key = src.get(sx, sy)
                if key == TRANSPARENT:
                    continue
                if only is not None and key not in only:
                    continue
                tx, ty = x + sx, y + sy
                if self.get(tx, ty) != TRANSPARENT:
                    self.put(tx, ty, key)

    # ---- selection / recolour ----------------------------------------
    def remap(self, keys, ch):
        keys = keys if isinstance(keys, str) else "".join(keys)
        for i, key in enumerate(self.px):
            if key != TRANSPARENT and key in keys:
                self.px[i] = ch

    def keep_only(self, keys):
        keys = keys if isinstance(keys, str) else "".join(keys)
        for i, key in enumerate(self.px):
            if key not in keys:
                self.px[i] = TRANSPARENT

    def mask_of(self, keys):
        """A copy holding only the listed keys."""
        out = Sprite(self.w, self.h)
        keys = keys if isinstance(keys, str) else "".join(keys)
        for i, key in enumerate(self.px):
            if key in keys:
                out.px[i] = key
        return out

    def edge_light(self, keys, ch, thickness=1):
        """Recolour the top and left rim of the given keys."""
        keys = keys if isinstance(keys, str) else "".join(keys)
        for _ in range(thickness):
            grabs = [(x, y) for y in range(self.h) for x in range(self.w)
                     if self.get(x, y) in keys
                     and (self.get(x, y - 1) == TRANSPARENT
                          or self.get(x - 1, y) == TRANSPARENT)]
            for x, y in grabs:
                self.put(x, y, ch)
            keys = ch

    def edge_shadow(self, keys, ch, thickness=1):
        """Recolour the bottom and right rim of the given keys."""
        keys = keys if isinstance(keys, str) else "".join(keys)
        for _ in range(thickness):
            grabs = [(x, y) for y in range(self.h) for x in range(self.w)
                     if self.get(x, y) in keys
                     and (self.get(x, y + 1) == TRANSPARENT
                          or self.get(x + 1, y) == TRANSPARENT)]
            for x, y in grabs:
                self.put(x, y, ch)
            keys = ch

    def outline(self, ch, diagonal=True):
        """1px border around the whole silhouette, drawn outside it."""
        neighbours = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        if diagonal:
            neighbours += [(-1, -1), (1, -1), (-1, 1), (1, 1)]
        solid = [self.get(x, y) != TRANSPARENT
                 for y in range(self.h) for x in range(self.w)]
        targets = []
        for y in range(self.h):
            for x in range(self.w):
                if solid[self.index(x, y)]:
                    continue
                for dx, dy in neighbours:
                    nx, ny = x + dx, y + dy
                    if self.inside(nx, ny) and solid[self.index(nx, ny)]:
                        targets.append((x, y))
                        break
        for x, y in targets:
            self.put(x, y, ch)

    def shade_below(self, keys, ch, rows=1):
        """Darken a fake ground contact under the listed keys."""
        keys = keys if isinstance(keys, str) else "".join(keys)
        for y in range(self.h - 1, -1, -1):
            for x in range(self.w):
                if self.get(x, y) in keys:
                    continue
            break

    def flip(self):
        """Horizontally mirrored copy."""
        out = Sprite(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                out.put(self.w - 1 - x, y, self.get(x, y))
        return out

    def shift(self, dx, dy):
        """Translate into a fresh sprite of the same size."""
        out = Sprite(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                out.put(x + dx, y + dy, self.get(x, y))
        return out

    def padded(self, x0, y0, x1, y1):
        """Copy of the region (inclusive bounds, may exceed the canvas)."""
        out = Sprite(x1 - x0 + 1, y1 - y0 + 1)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                out.put(x - x0, y - y0, self.get(x, y))
        return out

    def box(self):
        """(x0, y0, x1, y1) of the non-transparent pixels, or None."""
        xs, ys = [], []
        for y in range(self.h):
            for x in range(self.w):
                if self.get(x, y) != TRANSPARENT:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    # ---- output -------------------------------------------------------
    def rows(self, keep=True):
        return ["".join(self.px[y * self.w:(y + 1) * self.w]) for y in range(self.h)]

    def preview(self, keep=True):
        return "\n".join(self.rows(keep))

    def to_rgba(self, palette):
        raw = bytearray()
        for key in self.px:
            colour = palette.get(key)
            if colour is None:
                raise KeyError("palette has no entry for %r" % key)
            raw.extend(colour)
        return bytes(raw)

    def used_keys(self):
        return sorted({k for k in self.px if k != TRANSPARENT})


# =====================================================================
# PNG output (pure python, no deps)
# =====================================================================

def save_png(filepath, width, height, rgba_bytes):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + \
        struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba_bytes[y * width * 4:(y + 1) * width * 4])
    compressed = zlib.compress(bytes(raw), 9)
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + \
        struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + \
        struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    with open(filepath, "wb") as handle:
        handle.write(sig + ihdr + idat + iend)


def rgba_sheet(sprites, palette, scale=6, columns=6, cell_pad=6, label=True):
    """(width, height, rgba) contact sheet of [(label, Sprite), ...]."""
    if not sprites:
        return 0, 0, b""
    cell_w = max(s.w for _l, s in sprites) * scale + cell_pad * 2
    cell_h = max(s.h for _l, s in sprites) * scale + cell_pad * 2 + (10 if label else 0)
    columns = max(1, min(columns, len(sprites)))
    rows = (len(sprites) + columns - 1) // columns
    width, height = cell_w * columns, cell_h * rows

    canvas = [[(38, 38, 46, 255)] * width for _ in range(height)]
    for i, (text, sprite) in enumerate(sprites):
        ox = (i % columns) * cell_w + cell_pad
        oy = (i // columns) * cell_h + cell_pad + (10 if label else 0)
        for y in range(sprite.h):
            for x in range(sprite.w):
                key = sprite.get(x, y)
                if key == TRANSPARENT:
                    shade = (58, 58, 68, 255) if ((x // 2 + y // 2) % 2) else (48, 48, 58, 255)
                    colour = shade
                else:
                    colour = palette[key]
                for sy in range(scale):
                    row = canvas[oy + y * scale + sy]
                    for sx in range(scale):
                        row[ox + x * scale + sx] = colour
        if label:
            draw_text(canvas, ox, oy - 9, text.upper()[:24], (240, 214, 150, 255))

    raw = bytearray()
    for row in canvas:
        for colour in row:
            raw.extend(colour)
    return width, height, bytes(raw)


def save_sheet(filepath, sprites, palette, scale=6, columns=6):
    width, height, rgba = rgba_sheet(sprites, palette, scale, columns)
    save_png(filepath, width, height, rgba)
    return filepath


# =====================================================================
# Minimal 3x5 label font (only what sheets need)
# =====================================================================

_FONT = {
    "A": ["010", "101", "111", "101", "101"],
    "B": ["110", "101", "110", "101", "110"],
    "C": ["011", "100", "100", "100", "011"],
    "D": ["110", "101", "101", "101", "110"],
    "E": ["111", "100", "110", "100", "111"],
    "F": ["111", "100", "110", "100", "100"],
    "G": ["011", "100", "101", "101", "011"],
    "H": ["101", "101", "111", "101", "101"],
    "I": ["111", "010", "010", "010", "111"],
    "J": ["001", "001", "001", "101", "010"],
    "K": ["101", "101", "110", "101", "101"],
    "L": ["100", "100", "100", "100", "111"],
    "M": ["101", "111", "111", "101", "101"],
    "N": ["101", "111", "111", "111", "101"],
    "O": ["010", "101", "101", "101", "010"],
    "P": ["110", "101", "110", "100", "100"],
    "Q": ["010", "101", "101", "010", "001"],
    "R": ["110", "101", "110", "101", "101"],
    "S": ["011", "100", "010", "001", "110"],
    "T": ["111", "010", "010", "010", "010"],
    "U": ["101", "101", "101", "101", "111"],
    "V": ["101", "101", "101", "101", "010"],
    "W": ["101", "101", "111", "111", "101"],
    "X": ["101", "101", "010", "101", "101"],
    "Y": ["101", "101", "010", "010", "010"],
    "Z": ["111", "001", "010", "100", "111"],
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    "-": ["000", "000", "111", "000", "000"],
    "_": ["000", "000", "000", "000", "111"],
    ".": ["000", "000", "000", "000", "010"],
    " ": ["000", "000", "000", "000", "000"],
}


def draw_text(canvas, x, y, text, colour):
    """Blit 3x5 pixels of text onto a list-of-lists RGBA canvas."""
    cx = x
    for character in text.upper():
        glyph = _FONT.get(character, _FONT[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    py, px = y + gy, cx + gx
                    if 0 <= py < len(canvas) and 0 <= px < len(canvas[0]):
                        canvas[py][px] = colour
        cx += 4


# =====================================================================
# Palette helper
# =====================================================================

def hexc(value, alpha=255):
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def write_skin(skin_dir, frames, palette, verbose=True):
    """Write every (name -> Sprite) into skins/<skin>/<name>.png."""
    os.makedirs(skin_dir, exist_ok=True)
    written = []
    for name, sprite in sorted(frames.items()):
        path = os.path.join(skin_dir, "%s.png" % name)
        save_png(path, sprite.w, sprite.h, sprite.to_rgba(palette))
        written.append(name)
    if verbose:
        print("  %d frames -> %s" % (len(written), skin_dir))
    return written
