"""pet_fx.py - pixel particles around the pet: hearts, Zzz, stars, notes...

The particles live in their own click-through overlay window that follows the
pet, so they can float well outside the pet's 16x16 box without growing the
pet's own window (whose geometry the physics, ledges and speech bubble all
depend on).

Everything is drawn on the pet's art-pixel grid: a particle's position is in
art pixels relative to the sprite's top-left, snapped to whole pixels at paint
time, and each glyph pixel is one `unit` square. At 4x the hearts are made of
the same 4px squares as the cat, which is what keeps it looking like one
piece of pixel art instead of a sprite with stickers on it.
"""

import math
import random

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget

INK = (34, 24, 38)

# Glyphs: rows of palette keys. Each gets an automatic 1px ink outline.
GLYPHS = {
    "heart": ("rr.rr", "Rrrrr", "rrrrr", ".rrr.", "..r.."),
    "heart_s": ("r.r", "rrr", ".r."),
    "z": ("zzz", "..z", ".z.", "zzz"),
    "Z": ("zzzz", "..z.", ".z..", "zzzz"),
    "star": (".y.", "yYy", ".y."),
    "note": (".nn", ".n.", ".n.", "nn."),
    "note2": ("nnnn", "n..n", "n..n", "n.nn", "..nn"),
    "dust": ("dd", "dd"),
    "dust_s": ("d",),
    "sweat": (".b", "bb", "bb"),
    "crumb": ("c",),
    "exclaim": ("e", "e", "e", ".", "e"),
    "question": ("qqq", "..q", ".qq", "...", ".q."),
    "sparkle": (".w.", "wWw", ".w."),
    "spark": ("s",),
    "anger": ("a.a", ".a.", "a.a"),
    "cloud": (".gg.", "gggg"),
}

COLORS = {
    "r": (255, 92, 132), "R": (255, 214, 226),
    "z": (186, 206, 255),
    "y": (255, 214, 64), "Y": (255, 250, 210),
    "n": (255, 240, 170),
    "d": (236, 230, 222),
    "b": (120, 196, 255),
    "c": (200, 136, 74),
    "e": (255, 214, 64),
    "q": (255, 255, 255),
    "w": (255, 255, 255), "W": (255, 246, 190),
    "s": (110, 240, 255),
    "a": (255, 70, 70),
    "g": (200, 200, 214),
}

# glyphs that read better without an ink border (tiny, or meant to be soft)
NO_OUTLINE = {"dust", "dust_s", "crumb", "spark", "cloud"}

# Overlay margins around the 16x16 sprite, in art pixels.
MARGIN_X = 12
MARGIN_TOP = 16
MARGIN_BOTTOM = 3
SPRITE = 16
MAX_PARTICLES = 40


def _outlined(rows):
    """[(x, y, rgb)] for a glyph, with its ink border included."""
    h = len(rows)
    w = len(rows[0]) if rows else 0
    solid = {(x, y) for y in range(h) for x in range(w) if rows[y][x] != "."}
    pixels = []
    border = set()
    for (x, y) in solid:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (x + dx, y + dy)
                if p not in solid:
                    border.add(p)
    for (x, y) in border:
        pixels.append((x, y, INK))
    for (x, y) in solid:
        pixels.append((x, y, COLORS.get(rows[y][x], (255, 255, 255))))
    return pixels


_GLYPH_PIXELS = {}
for _name, _rows in GLYPHS.items():
    if _name in NO_OUTLINE:
        _GLYPH_PIXELS[_name] = [
            (x, y, COLORS.get(k, (255, 255, 255)))
            for y, row in enumerate(_rows) for x, k in enumerate(row) if k != "."]
    else:
        _GLYPH_PIXELS[_name] = _outlined(_rows)
_GLYPH_SIZE = {n: (len(r[0]), len(r)) for n, r in GLYPHS.items()}


class Particle:
    __slots__ = ("kind", "x", "y", "vx", "vy", "gravity", "life", "age",
                 "wobble", "phase", "fade", "blink", "orbit")

    def __init__(self, kind, x, y, vx=0.0, vy=0.0, life=30, gravity=0.0,
                 wobble=0.0, fade=True, blink=False, orbit=None):
        self.kind = kind
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = float(vx), float(vy)
        self.gravity = gravity
        self.life = int(life)
        self.age = 0
        self.wobble = wobble
        self.phase = random.random() * math.tau
        self.fade = fade
        self.blink = blink
        self.orbit = orbit      # (cx, cy, rx, ry, radians per tick, start)

    def step(self):
        self.age += 1
        if self.orbit:
            cx, cy, rx, ry, speed, start = self.orbit
            a = start + self.age * speed
            self.x = cx + math.cos(a) * rx
            self.y = cy + math.sin(a) * ry
            return self.age < self.life
        self.vy += self.gravity
        self.x += self.vx + (math.sin(self.phase + self.age * 0.25)
                             * self.wobble)
        self.y += self.vy
        return self.age < self.life

    def alpha(self):
        if not self.fade:
            return 1.0
        left = self.life - self.age
        return max(0.0, min(1.0, left / 8.0))


class PetFX(QWidget):
    """Click-through particle layer that shadows the pet's position."""

    def __init__(self, title="desktop-pet-overlay"):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowTransparentForInput
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.particles = []
        self.unit = 2
        self.facing = 1
        self.enabled = True

    # ---- emitting ------------------------------------------------------
    def emit(self, kind, x, y, **kw):
        if not self.enabled or kind not in GLYPHS:
            return None
        if len(self.particles) >= MAX_PARTICLES:
            self.particles.pop(0)
        p = Particle(kind, x, y, **kw)
        self.particles.append(p)
        return p

    def burst(self, name):
        """Named effects, in sprite art-pixel space (0..16, y down)."""
        r = random.uniform
        if name == "hearts":
            for i, x in enumerate((8, 3, 13)):
                self.emit("heart_s" if i else "heart", x + r(-1, 1), 1 + i * 2,
                          vx=r(-0.1, 0.1), vy=r(-0.45, -0.3), life=28 + i * 5,
                          wobble=0.2)
        elif name == "heart":
            self.emit("heart", r(4, 8), -1, vy=-0.35, life=26, wobble=0.15)
        elif name == "zzz":
            self.emit("z" if random.random() < 0.6 else "Z",
                      11 + r(0, 2), 2, vx=0.12, vy=-0.18, life=46, wobble=0.25)
        elif name == "stars":
            # three stars circling the head, cartoon-concussion style
            for i in range(3):
                self.emit("star", 8, 0, life=60, fade=False,
                          orbit=(8, 0, 6, 1.6, 0.22, i * math.tau / 3))
        elif name == "notes":
            self.emit("note" if random.random() < 0.6 else "note2",
                      r(0, 14), r(-1, 3), vx=r(-0.2, 0.2), vy=-0.3, life=34,
                      wobble=0.3)
        elif name == "dust":
            for side in (-1, 1):
                for i in range(2):
                    self.emit("dust" if i == 0 else "dust_s",
                              7 + side * (4 + i * 2), 14,
                              vx=side * r(0.3, 0.6), vy=r(-0.25, -0.05),
                              life=12 + i * 3)
        elif name == "kick":
            # a puff behind the feet while running
            back = 1 if self.facing < 0 else -1
            self.emit("dust_s", 8 + back * 7, 14, vx=back * 0.35, vy=-0.12,
                      life=8)
        elif name == "sweat":
            self.emit("sweat", 13, 2, vx=0.15, vy=-0.1, gravity=0.06, life=20)
        elif name == "crumbs":
            for _ in range(3):
                self.emit("crumb", r(11, 14), 12, vx=r(-0.4, 0.4),
                          vy=r(-0.7, -0.3), gravity=0.12, life=14)
        elif name == "exclaim":
            self.emit("exclaim", 7, -6, vy=-0.15, life=18, fade=False)
        elif name == "question":
            self.emit("question", 7, -6, vy=-0.1, life=24, fade=False)
        elif name == "sparkles":
            for _ in range(4):
                self.emit("sparkle", r(0, 15), r(-2, 12), life=14, blink=True)
        elif name == "sparks":
            for _ in range(4):
                self.emit("spark", r(5, 11), r(4, 10), vx=r(-0.6, 0.6),
                          vy=r(-0.8, -0.2), gravity=0.08, life=12)
        elif name == "anger":
            self.emit("anger", 12, 0, life=24, wobble=0.1, fade=False)
        elif name == "puff":
            for _ in range(5):
                self.emit("cloud", r(2, 12), r(4, 12), vx=r(-0.3, 0.3),
                          vy=r(-0.3, 0.0), life=16)

    def clear(self):
        self.particles = []

    # ---- per tick ------------------------------------------------------
    def tick(self, unit, sprite_x, sprite_y, visible, facing=1):
        """Advance particles and follow the sprite's on-screen top-left."""
        self.facing = facing
        self.particles = [p for p in self.particles if p.step()]
        if not self.particles or not visible or not self.enabled:
            if self.isVisible():
                self.hide()
            return
        if unit != self.unit:
            self.unit = unit
        w = (SPRITE + 2 * MARGIN_X) * unit
        h = (SPRITE + MARGIN_TOP + MARGIN_BOTTOM) * unit
        if self.width() != w or self.height() != h:
            self.resize(w, h)
        x = int(sprite_x) - MARGIN_X * unit
        y = int(sprite_y) - MARGIN_TOP * unit
        if self.x() != x or self.y() != y:
            self.move(x, y)
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        u = self.unit
        for p in self.particles:
            if p.blink and (p.age // 3) % 2:
                continue
            pixels = _GLYPH_PIXELS.get(p.kind)
            if not pixels:
                continue
            gw, gh = _GLYPH_SIZE[p.kind]
            ox = (int(round(p.x)) - gw // 2 + MARGIN_X) * u
            oy = (int(round(p.y)) - gh // 2 + MARGIN_TOP) * u
            a = int(255 * p.alpha())
            if a <= 0:
                continue
            for gx, gy, rgb in pixels:
                painter.fillRect(QRect(ox + gx * u, oy + gy * u, u, u),
                                 QColor(rgb[0], rgb[1], rgb[2], a))
        painter.end()
