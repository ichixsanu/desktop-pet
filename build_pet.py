import math
import os
import struct
import sys
import zipfile
import zlib

# ==== pixel engine ====
import math
import struct
import zlib


# ---------- PNG (pure python, no deps) ----------
def save_png(filepath, width, height, rgba_bytes):
    png = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png += struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba_bytes[y * width * 4:(y + 1) * width * 4])
    idat = zlib.compress(bytes(raw), 9)
    png += struct.pack(">I", len(idat)) + b"IDAT" + idat + struct.pack(">I", zlib.crc32(b"IDAT" + idat))
    png += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    with open(filepath, "wb") as f:
        f.write(png)


def hexc(h, a=255):
    h = h.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a]


# ---------- Canvas ----------
LIGHT = (-0.55, -0.8)
_LL = math.hypot(*LIGHT)
LX, LY = LIGHT[0] / _LL, LIGHT[1] / _LL


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = [[0, 0, 0, 0] for _ in range(w * h)]

    def _i(self, x, y):
        return y * self.w + x

    def inb(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def set(self, x, y, c):
        x, y = int(x), int(y)
        if self.inb(x, y):
            self.px[self._i(x, y)] = [c[0], c[1], c[2], c[3] if len(c) > 3 else 255]

    def get(self, x, y):
        x, y = int(x), int(y)
        if self.inb(x, y):
            return self.px[self._i(x, y)]
        return [0, 0, 0, 0]

    def blend(self, x, y, c):
        x, y = int(x), int(y)
        if not self.inb(x, y):
            return
        r, g, b, a = c
        if a >= 255:
            self.set(x, y, c)
            return
        if a <= 0:
            return
        dr, dg, db, da = self.get(x, y)
        af = a / 255.0
        nr = int(r * af + dr * (1 - af))
        ng = int(g * af + dg * (1 - af))
        nb = int(b * af + db * (1 - af))
        na = min(255, int(a + da * (1 - af)))
        self.set(x, y, [nr, ng, nb, na])

    def to_bytes(self):
        out = bytearray()
        for p in self.px:
            out.extend(p)
        return bytes(out)

    def hflip(self):
        c = Canvas(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                c.px[c._i(self.w - 1 - x, y)] = list(self.get(x, y))
        return c


def _shade(nx, ny, base, dark, light):
    if dark is None and light is None:
        return base
    d = nx * LX + ny * LY
    if light is not None and d < -0.28:
        return light
    if dark is not None and d > 0.45:
        return dark
    return base


def ellipse(cv, cx, cy, rx, ry, base, dark=None, light=None):
    if rx <= 0 or ry <= 0:
        return
    x0, x1 = int(math.floor(cx - rx)), int(math.ceil(cx + rx))
    y0, y1 = int(math.floor(cy - ry)), int(math.ceil(cy + ry))
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            nx = (x + 0.5 - cx) / rx
            ny = (y + 0.5 - cy) / ry
            if nx * nx + ny * ny <= 1.0:
                cv.set(x, y, _shade(nx, ny, base, dark, light))


def half_ellipse_top(cv, cx, cy, rx, ry, base, dark=None, light=None):
    # only the top half (ny <= 0) -- useful for domed shapes sitting on a base
    if rx <= 0 or ry <= 0:
        return
    x0, x1 = int(math.floor(cx - rx)), int(math.ceil(cx + rx))
    y0, y1 = int(math.floor(cy - ry)), int(math.ceil(cy))
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            nx = (x + 0.5 - cx) / rx
            ny = (y + 0.5 - cy) / ry
            if ny <= 0.05 and nx * nx + ny * ny <= 1.0:
                cv.set(x, y, _shade(nx, ny, base, dark, light))


def triangle(cv, p0, p1, p2, base, dark=None, light=None, light_ref=None):
    xs = [p0[0], p1[0], p2[0]]
    ys = [p0[1], p1[1], p2[1]]
    x0, x1 = int(min(xs)), int(max(xs))
    y0, y1 = int(min(ys)), int(max(ys))

    def edge(a, b, c):
        return (c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])

    area = edge(p0, p1, p2)
    if area == 0:
        return
    cx = (p0[0] + p1[0] + p2[0]) / 3.0
    cy = (p0[1] + p1[1] + p2[1]) / 3.0
    span = max(1.0, (max(xs) - min(xs) + max(ys) - min(ys)) / 2.0)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            pt = (x + 0.5, y + 0.5)
            w0, w1, w2 = edge(p1, p2, pt), edge(p2, p0, pt), edge(p0, p1, pt)
            inside = (w0 >= 0 and w1 >= 0 and w2 >= 0) if area > 0 else (w0 <= 0 and w1 <= 0 and w2 <= 0)
            if inside:
                lr = light_ref or pt
                nx = (lr[0] - cx) / span
                ny = (lr[1] - cy) / span
                cv.set(x, y, _shade(nx, ny, base, dark, light))


def capsule(cv, x0, y0, x1, y1, radius, base, dark=None, light=None):
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 0.001:
        ellipse(cv, x0, y0, radius, radius, base, dark, light)
        return
    ux, uy = dx / length, dy / length
    nx_, ny_ = -uy, ux
    minx = int(min(x0, x1) - radius - 1)
    maxx = int(max(x0, x1) + radius + 1)
    miny = int(min(y0, y1) - radius - 1)
    maxy = int(max(y0, y1) + radius + 1)
    for y in range(miny, maxy + 1):
        for x in range(minx, maxx + 1):
            px, py = x + 0.5 - x0, y + 0.5 - y0
            t = (px * ux + py * uy)
            t_clamped = max(0.0, min(length, t))
            cxp, cyp = ux * t_clamped, uy * t_clamped
            ddx, ddy = px - cxp, py - cyp
            dist2 = ddx * ddx + ddy * ddy
            if dist2 <= radius * radius:
                side = ddx * nx_ + ddy * ny_
                nrm = side / radius
                cv.set(x, y, _shade(nrm * 0.9, -0.3, base, dark, light))


def line(cv, x0, y0, x1, y1, color, width=1):
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        for ow in range(width):
            cv.set(x, y + ow if width > 1 else y, color)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def dot(cv, x, y, color):
    cv.set(x, y, color)


def soft_shadow(cv, cx, cy, rx, ry, alpha=100, color=(8, 6, 14)):
    x0, x1 = int(cx - rx) - 1, int(cx + rx) + 1
    y0, y1 = int(cy - ry) - 1, int(cy + ry) + 1
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            nx = (x + 0.5 - cx) / rx
            ny = (y + 0.5 - cy) / ry
            d = nx * nx + ny * ny
            if d <= 1.0:
                fall = (1.0 - d) ** 0.6
                a = int(alpha * fall)
                cv.blend(x, y, [color[0], color[1], color[2], a])


def outline(cv, color, diag=True):
    w, h = cv.w, cv.h
    orig_a = [cv.px[i][3] for i in range(w * h)]
    nbrs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if diag:
        nbrs += [(-1, -1), (1, -1), (-1, 1), (1, 1)]
    targets = []
    for y in range(h):
        for x in range(w):
            if orig_a[y * w + x] == 0:
                for dx, dy in nbrs:
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < w and 0 <= yy < h and orig_a[yy * w + xx] > 0:
                        targets.append((x, y))
                        break
    for x, y in targets:
        cv.set(x, y, color)


def stroke_curve(cv, p0, p1, p2, r0, r2, base, dark=None, light=None, steps=14):
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        r = r0 + (r2 - r0) * t
        ellipse(cv, x, y, r, r, base, dark, light)


def paste(dst, src):
    # overwrite dst wherever src has any opacity (src fully replaces, no blending,
    # so outlines stay crisp) -- used to composite a creature over a shadow/backdrop
    for y in range(src.h):
        for x in range(src.w):
            c = src.get(x, y)
            if c[3] > 0:
                dst.set(x, y, c)


def zzz(cv, x, y, color):
    line(cv, x, y, x + 2, y, color)
    line(cv, x + 2, y, x, y + 2, color)
    line(cv, x, y + 2, x + 2, y + 2, color)
    line(cv, x + 3, y - 2, x + 5, y - 2, color)
    line(cv, x + 5, y - 2, x + 3, y, color)
    line(cv, x + 3, y, x + 5, y, color)


def glow(cv, color, alpha=70, radius=2):
    # soft translucent aura just outside the (already outlined) silhouette
    w, h = cv.w, cv.h
    orig_a = [cv.px[i][3] for i in range(w * h)]

    def solid(x, y):
        return 0 <= x < w and 0 <= y < h and orig_a[y * w + x] > 0

    for y in range(h):
        for x in range(w):
            if orig_a[y * w + x] > 0:
                continue
            best = None
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    dist = math.hypot(dx, dy)
                    if dist <= radius and solid(x + dx, y + dy):
                        if best is None or dist < best:
                            best = dist
            if best is not None:
                a = int(alpha * (1.0 - best / (radius + 0.001)))
                if a > 0:
                    cv.blend(x, y, [color[0], color[1], color[2], a])


def upscale(cv, scale):
    big = Canvas(cv.w * scale, cv.h * scale)
    for y in range(cv.h):
        for x in range(cv.w):
            c = cv.get(x, y)
            for oy in range(scale):
                for ox in range(scale):
                    big.set(x * scale + ox, y * scale + oy, c)
    return big


def draw_heart():
    cv = Canvas(16, 16)
    base, d, l = hexc("#e8607d"), hexc("#b8395a"), hexc("#f5a3b8")
    ink = hexc("#3a1420")
    ellipse(cv, 5.5, 5.5, 3.4, 3.4, base, d, l)
    ellipse(cv, 10.5, 5.5, 3.4, 3.4, base, d, l)
    triangle(cv, (2.3, 6.5), (13.7, 6.5), (8, 14.5), base, d, l, light_ref=(5, 9))
    outline(cv, ink)
    return cv


# ==== cat ====

CAT_PAL = dict(
    fur=hexc("#e08843"), fur_d=hexc("#b5652e"),
    cream=hexc("#fbeedd"), cream_d=hexc("#e3cead"),
    ink=hexc("#231018"),
    nose=hexc("#c97b7b"),
    eye=hexc("#173318"), iris=hexc("#8fbf5e"),
)


def cat_draw_tail(sway=0.0, up=0.2):
    cv = Canvas(32, 32)
    p = CAT_PAL
    base = (20, 25)
    ctrl = (28, 22 - up * 8)
    tip = (24 - up * 3 + sway * 3, 14 - up * 9)
    stroke_curve(cv, base, ctrl, tip, 2.2, 1.1, p["fur"], p["fur_d"], None, steps=14)
    outline(cv, p["ink"])
    return cv


def cat_ear(cv, cx, base_y, mirror):
    p = CAT_PAL
    tip = (cx + 1.2 * mirror, base_y - 6.2)
    triangle(cv, (cx - 3.0 * mirror, base_y + 0.5), (cx + 2.4 * mirror, base_y), tip, p["fur"], p["fur_d"])
    triangle(cv, (cx - 1.3 * mirror, base_y - 0.6), (cx + 1.0 * mirror, base_y - 1.0),
              (cx + 0.4 * mirror, base_y - 4.2), p["cream_d"])


def cat_eyes(cv, hy, cx_l, cx_r, mood="open"):
    p = CAT_PAL
    if mood == "open":
        for ex in (cx_l, cx_r):
            ellipse(cv, ex, hy, 1.9, 2.0, p["ink"])
            ellipse(cv, ex, hy + 0.3, 1.5, 1.4, p["iris"])
            dot(cv, ex, hy + 0.6, p["eye"])
            dot(cv, ex - 0.6, hy - 0.6, (255, 255, 255, 255))
    elif mood == "blink":
        for ex in (cx_l, cx_r):
            line(cv, ex - 1.6, hy, ex + 1.6, hy, p["ink"], width=1)
    elif mood == "happy":
        for ex in (cx_l, cx_r):
            for dx in range(-2, 3):
                dot(cv, ex + dx, hy + abs(dx) * 0.35, p["ink"])


def draw_cat(pose="sit", eye_mood="open", tail_sway=0.0, tail_up=0.2, breathe=0.0,
             paw_lift=0.0, leg_phase=0.0, run=False, head_bob=0.0):
    p = CAT_PAL
    tail_cv = cat_draw_tail(tail_sway, 0.85 if run else tail_up)
    cv = Canvas(32, 32)

    if pose == "sit":
        ellipse(cv, 16, 22 - breathe, 6.6, 6.3, p["fur"], p["fur_d"])
        ellipse(cv, 16, 25 - breathe, 3.4, 3.0, p["cream"], p["cream_d"])
        ellipse(cv, 11.2, 28.3, 2.1, 1.7, p["fur_d"])
        ellipse(cv, 20.8, 28.3, 2.1, 1.7, p["fur_d"])
        ellipse(cv, 11.2, 27.6 - paw_lift * 2, 1.7, 1.3, p["cream"])
        ellipse(cv, 20.8, 27.6, 1.7, 1.3, p["cream"])
        hy = 14 - breathe - head_bob
    else:
        stride = 3.6 if run else 2.0
        lift = 2.0 if run else 0.9

        def leg(x, phase):
            swing = math.sin(phase * 2 * math.pi)
            fx = x + swing * stride * 0.5
            fy = 28 - max(0, math.cos(phase * 2 * math.pi)) * lift
            capsule(cv, x, 21, fx, fy, 1.3, p["fur_d"])
            ellipse(cv, fx, fy, 1.3, 1.0, p["cream_d"])

        leg(12, leg_phase)
        leg(20, leg_phase + 0.5)
        ellipse(cv, 16, 19, 7.2, 4.9, p["fur"], p["fur_d"])
        ellipse(cv, 16, 20.5, 3.6, 2.6, p["cream"], p["cream_d"])
        leg(12, leg_phase + 0.25)
        leg(20, leg_phase + 0.75)
        hy = 12 - head_bob

    ellipse(cv, 16, hy, 6.9, 6.2, p["fur"], p["fur_d"])
    ellipse(cv, 16, hy + 2.6, 4.2, 3.0, p["cream"])
    cat_ear(cv, 10.6, hy - 3.9, -1)
    cat_ear(cv, 21.4, hy - 3.9, 1)
    cat_eyes(cv, hy - 0.2, 12.6, 19.4, eye_mood)

    ny_ = hy + 2.2
    triangle(cv, (16 - 1, ny_ - 0.6), (16 + 1, ny_ - 0.6), (16, ny_ + 0.7), p["nose"])

    outline(cv, p["ink"])

    line(cv, 16, ny_ + 0.7, 16, ny_ + 1.3, p["eye"])
    line(cv, 16, ny_ + 1.3, 14.3, ny_ + 2.1, p["eye"])
    line(cv, 16, ny_ + 1.3, 17.7, ny_ + 2.1, p["eye"])
    for wy in (hy + 0.3, hy + 1.2):
        line(cv, 4, wy, 9.3, wy - 0.3, p["ink"])
        line(cv, 28, wy, 22.7, wy - 0.3, p["ink"])

    final = Canvas(32, 32)
    paste(final, tail_cv)
    paste(final, cv)
    return final


def cat_compose(cv):
    out = Canvas(32, 32)
    soft_shadow(out, 16, 30, 8, 1.8, alpha=90)
    paste(out, cv)
    return out


# ==== shiba ====

SHIBA_PAL = dict(
    fur=hexc("#dc9a3c"), fur_d=hexc("#b06f21"),
    cream=hexc("#fdf3e0"), cream_d=hexc("#e6d2ac"),
    ink=hexc("#201409"),
    nose=hexc("#221812"),
    tongue=hexc("#e8798f"),
    eye=hexc("#0c0806"),
)


def shiba_draw_tail(sway=0.0):
    cv = Canvas(32, 32)
    p = SHIBA_PAL
    base = (19, 22)
    ctrl = (27, 13 + sway)
    tip = (18, 9 - sway)
    stroke_curve(cv, base, ctrl, tip, 2.6, 1.6, p["fur"], p["fur_d"], None, steps=13)
    ellipse(cv, tip[0], tip[1], 1.5, 1.5, p["cream"])
    outline(cv, p["ink"])
    return cv


def shiba_ear(cv, cx, base_y, mirror):
    p = SHIBA_PAL
    tip = (cx + 0.4 * mirror, base_y - 5.6)
    triangle(cv, (cx - 2.5 * mirror, base_y), (cx + 2.2 * mirror, base_y - 0.4), tip, p["fur"], p["fur_d"])
    triangle(cv, (cx - 0.9 * mirror, base_y - 1.1), (cx + 0.9 * mirror, base_y - 1.4),
              (cx + 0.2 * mirror, base_y - 4.0), p["cream_d"])


def shiba_eyes(cv, hy, cx_l, cx_r, mood="open"):
    p = SHIBA_PAL
    if mood == "open":
        for ex in (cx_l, cx_r):
            ellipse(cv, ex, hy, 1.5, 1.6, p["eye"])
            dot(cv, ex - 0.5, hy - 0.6, (255, 255, 255, 255))
    else:
        for ex in (cx_l, cx_r):
            line(cv, ex - 1.4, hy, ex + 1.4, hy, p["ink"])


def draw_sit(mood="open", mouth="open", tail_sway=0.0, breathe=0.0):
    p = SHIBA_PAL
    tail_cv = shiba_draw_tail(tail_sway)
    cv = Canvas(32, 32)

    ellipse(cv, 16, 22 - breathe, 6.9, 6.1, p["fur"], p["fur_d"])
    ellipse(cv, 16, 25 - breathe, 3.6, 2.9, p["cream"])
    ellipse(cv, 11.4, 28.2, 2.0, 1.6, p["fur_d"])
    ellipse(cv, 20.6, 28.2, 2.0, 1.6, p["fur_d"])
    ellipse(cv, 11.4, 27.5, 1.6, 1.2, p["cream"])
    ellipse(cv, 20.6, 27.5, 1.6, 1.2, p["cream"])

    hy = 13 - breathe
    ellipse(cv, 16, hy, 6.7, 6.1, p["fur"], p["fur_d"])
    ellipse(cv, 16, hy + 2.6, 4.0, 2.9, p["cream"])
    shiba_ear(cv, 10.4, hy - 4.0, -1)
    shiba_ear(cv, 21.6, hy - 4.0, 1)
    shiba_eyes(cv, hy - 0.3, 12.5, 19.5, mood)

    ny_ = hy + 2.1
    triangle(cv, (16 - 1.1, ny_ - 0.6), (16 + 1.1, ny_ - 0.6), (16, ny_ + 0.8), p["nose"])
    outline(cv, p["ink"])

    line(cv, 16, ny_ + 0.8, 16, ny_ + 1.4, p["ink"])
    line(cv, 16, ny_ + 1.4, 14.3, ny_ + 2.3, p["ink"])
    line(cv, 16, ny_ + 1.4, 17.7, ny_ + 2.3, p["ink"])
    if mouth == "tongue":
        ellipse(cv, 16.2, ny_ + 3.2, 1.2, 1.7, p["tongue"])

    final = Canvas(32, 32)
    paste(final, tail_cv)
    paste(final, cv)
    return final


def draw_stand(leg_phase=0.0, run=False, mood="open", mouth="tongue"):
    p = SHIBA_PAL
    stride = 3.8 if run else 2.0
    lift = 2.2 if run else 0.9
    cv = Canvas(32, 32)

    def leg(x, phase):
        swing = math.sin(phase * 2 * math.pi)
        fx = x + swing * stride * 0.5
        fy = 28 - max(0, math.cos(phase * 2 * math.pi)) * lift
        capsule(cv, x, 20, fx, fy, 1.3, p["fur_d"])
        ellipse(cv, fx, fy, 1.3, 1.0, p["cream"])

    leg(12, leg_phase)
    leg(20, leg_phase + 0.5)
    ellipse(cv, 16, 18.5, 7.0, 4.6, p["fur"], p["fur_d"])
    ellipse(cv, 16, 20, 3.6, 2.5, p["cream"])
    leg(12, leg_phase + 0.25)
    leg(20, leg_phase + 0.75)

    hy = 11.5
    ellipse(cv, 17, hy, 6.6, 6.0, p["fur"], p["fur_d"])
    ellipse(cv, 17.2, hy + 2.4, 3.9, 2.7, p["cream"])
    shiba_ear(cv, 11.6, hy - 3.8, -1)
    shiba_ear(cv, 22.4, hy - 3.8, 1)
    shiba_eyes(cv, hy - 0.2, 13.6, 20.4, mood)

    ny_ = hy + 1.9
    triangle(cv, (17 - 1, ny_ - 0.5), (17 + 1, ny_ - 0.5), (17, ny_ + 0.7), p["nose"])
    outline(cv, p["ink"])
    line(cv, 17, ny_ + 0.7, 17, ny_ + 1.2, p["ink"])
    if mouth == "tongue":
        ellipse(cv, 17.2, ny_ + 2.3, 1.1, 1.5, p["tongue"])

    tail_cv = Canvas(32, 32)
    base, ctrl, tip = (21, 15), (28, 7), (19, 5)
    stroke_curve(tail_cv, base, ctrl, tip, 2.3, 1.5, p["fur"], p["fur_d"], None, steps=11)
    ellipse(tail_cv, tip[0], tip[1], 1.3, 1.3, p["cream"])
    outline(tail_cv, p["ink"])

    final = Canvas(32, 32)
    paste(final, tail_cv)
    paste(final, cv)
    return final


def shiba_compose(cv):
    out = Canvas(32, 32)
    soft_shadow(out, 16, 30, 8, 1.8, alpha=90)
    paste(out, cv)
    return out


# ==== ghost ====

GHOST_PAL = dict(
    body=hexc("#eef1fb"), body_d=hexc("#c3c9ea"), body_l=hexc("#ffffff"),
    ink=hexc("#392f52"),
    eye=hexc("#23213a"), highlight=hexc("#ffffff"),
    glow=hexc("#b9c4f2"),
)


def draw_ghost(bob=0.0, mood="open", lean=0.0, hem_phase=0.0, arms_up=False):
    p = GHOST_PAL
    cv = Canvas(32, 32)
    cy = 13 + bob

    half_ellipse_top(cv, 16 + lean * 2, cy, 9.5, 9.0, p["body"], p["body_d"], p["body_l"])
    ellipse(cv, 16 + lean * 2, cy + 3, 9.5, 8.0, p["body"], p["body_d"], p["body_l"])

    hem_y = cy + 9
    for i in range(6):
        hx = 16 + lean * 2 - 9 + i * 3.6
        wob = math.sin(hem_phase * 2 * math.pi + i) * 1.1
        ellipse(cv, hx, hem_y + wob, 2.3, 2.6, p["body"], p["body_d"], None)

    if arms_up:
        ellipse(cv, 16 + lean * 2 - 10, cy + 1, 2.0, 3.2, p["body"], p["body_d"], None)
        ellipse(cv, 16 + lean * 2 + 10, cy + 1, 2.0, 3.2, p["body"], p["body_d"], None)

    ex_off = 3.2
    ey = cy - 0.5
    if mood == "open":
        for exm in (-1, 1):
            ex = 16 + lean * 2 + exm * ex_off
            ellipse(cv, ex, ey, 1.5, 1.9, p["eye"])
            dot(cv, ex - 0.5, ey - 0.8, p["highlight"])
    elif mood == "blink":
        for exm in (-1, 1):
            ex = 16 + lean * 2 + exm * ex_off
            line(cv, ex - 1.3, ey, ex + 1.3, ey, p["ink"])
    elif mood == "spook":
        for exm in (-1, 1):
            ex = 16 + lean * 2 + exm * ex_off
            ellipse(cv, ex, ey, 1.7, 2.3, p["eye"])
        ellipse(cv, 16 + lean * 2, ey + 3.2, 1.6, 2.0, p["eye"])
    elif mood == "happy":
        for exm in (-1, 1):
            ex = 16 + lean * 2 + exm * ex_off
            line(cv, ex - 1.3, ey + 0.6, ex, ey - 0.6, p["ink"], width=1)
            line(cv, ex, ey - 0.6, ex + 1.3, ey + 0.6, p["ink"], width=1)

    if mood != "spook":
        mx = 16 + lean * 2
        ellipse(cv, mx, ey + 3.0, 1.1, 1.3, p["eye"])

    outline(cv, p["ink"])
    glow(cv, p["glow"], alpha=55, radius=2)
    return cv


def ghost_compose(cv, shadow=True):
    out = Canvas(32, 32)
    if shadow:
        soft_shadow(out, 16, 29.5, 7, 1.8, alpha=70)
    paste(out, cv)
    return out


# ==== bots (jarvis/ultron) ====

FRIENDLY = dict(
    body=hexc("#e9edf4"), body_d=hexc("#b7c1d6"), body_l=hexc("#ffffff"),
    dark=hexc("#3a3f4c"), glow=hexc("#57e0f0"), glow_d=hexc("#1f8f9e"),
    ink=hexc("#262a33"),
)
ROGUE = dict(
    body=hexc("#4d5058"), body_d=hexc("#2a2c32"), body_l=hexc("#686c78"),
    dark=hexc("#16171a"), glow=hexc("#ef4a56"), glow_d=hexc("#8f1f27"),
    ink=hexc("#0e0f11"),
)


def _legs(cv, p, leg_phase, run, y0=21):
    stride = 3.4 if run else 1.8
    lift = 1.8 if run else 0.7
    for x, ph in ((12.5, leg_phase), (19.5, leg_phase + 0.5)):
        swing = math.sin(ph * 2 * math.pi)
        fx = x + swing * stride * 0.5
        fy = 28 - max(0, math.cos(ph * 2 * math.pi)) * lift
        capsule(cv, x, y0, fx, fy, 1.4, p["dark"])
        ellipse(cv, fx, fy + 0.4, 1.6, 1.1, p["body_d"])


def draw_bot(kind="friendly", pose="sit", mood="open", bob=0.0, leg_phase=0.0, run=False, tilt=0.0):
    p = FRIENDLY if kind == "friendly" else ROGUE
    angular = kind != "friendly"
    cv = Canvas(32, 32)

    if pose == "walk":
        _legs(cv, p, leg_phase, run, y0=20)
        ellipse(cv, 16, 19 - bob, 6.4, 5.4, p["body"], p["body_d"], p["body_l"])
        cy = 12 - bob
    else:
        ellipse(cv, 16, 23 - bob, 6.6, 6.4, p["body"], p["body_d"], p["body_l"])
        ellipse(cv, 12.2, 27.6, 1.7, 1.4, p["body_d"])
        ellipse(cv, 19.8, 27.6, 1.7, 1.4, p["body_d"])
        cy = 13 - bob

    dot(cv, 16, (19 if pose == "walk" else 22) - bob, p["glow"])

    for side in (-1, 1):
        ellipse(cv, 16 + side * 8.4, cy + 1.5, 1.5, 2.2, p["body"], p["body_d"])

    if angular:
        triangle(cv, (16 - 7.6, cy - 1.5), (16 + 7.6, cy - 1.5), (16, cy - 8.6), p["body"], p["body_d"], p["body_l"])
        triangle(cv, (16 - 7.2, cy + 1), (16 + 7.2, cy + 1), (16, cy + 7.4), p["body"], p["body_d"], p["body_l"])
    else:
        ellipse(cv, 16, cy, 7.0, 6.6, p["body"], p["body_d"], p["body_l"])

    line(cv, 16, cy - 8.6 if angular else cy - 6.6, 16, cy - 10.4, p["dark"], width=1)
    dot(cv, 16, cy - 10.8, p["glow"])

    vy = cy - 0.3
    if mood == "open":
        ellipse(cv, 16, vy, 4.6, 1.9, p["dark"])
        if angular:
            line(cv, 12.2, vy, 19.8, vy, p["glow"], width=1)
            dot(cv, 12.2, vy, p["glow_d"])
            dot(cv, 19.8, vy, p["glow_d"])
        else:
            for gx in (13.2, 16, 18.8):
                dot(cv, gx, vy, p["glow"])
    elif mood == "blink":
        ellipse(cv, 16, vy, 4.6, 1.0, p["dark"])
    elif mood == "spook":
        ellipse(cv, 16, vy, 5.2, 2.6, p["dark"])
        for gx in (12.6, 16, 19.4):
            dot(cv, gx, vy, p["glow"])
    elif mood == "happy":
        ellipse(cv, 16, vy, 4.6, 1.9, p["dark"])
        line(cv, 12.6, vy - 0.6, 19.4, vy - 0.6, p["glow"], width=1)

    outline(cv, p["ink"])
    if not angular:
        glow(cv, p["glow"], alpha=35, radius=1)
    return cv


def bots_compose(cv):
    out = Canvas(32, 32)
    soft_shadow(out, 16, 30, 8, 1.8, alpha=90)
    paste(out, cv)
    return out


# ==== frame set assembly ====
def _sleepify(cv, tone):
    c2 = Canvas(32, 32)
    for y in range(32):
        for x in range(32):
            c2.set(x, y, cv.get(x, y))
    zzz(c2, 22, 4, tone)
    return c2


def cat_frames():
    f = {}
    f["sit_0"] = cat_compose(draw_cat())
    f["sit_1"] = cat_compose(draw_cat(breathe=0.5, tail_up=0.05))
    f["blink"] = cat_compose(draw_cat(eye_mood="blink"))
    f["groom_0"] = cat_compose(draw_cat(eye_mood="happy", paw_lift=1.0))
    f["groom_1"] = cat_compose(draw_cat(eye_mood="blink", paw_lift=0.6))
    f["stalk_0"] = cat_compose(draw_cat(pose="walk", leg_phase=0.1, tail_sway=-1))
    f["stalk_1"] = cat_compose(draw_cat(pose="walk", leg_phase=0.6, tail_sway=1))
    f["walk_0"] = cat_compose(draw_cat(pose="walk", leg_phase=0.0))
    f["walk_1"] = cat_compose(draw_cat(pose="walk", leg_phase=0.5))
    f["run_0"] = cat_compose(draw_cat(pose="walk", leg_phase=0.0, run=True))
    f["run_1"] = cat_compose(draw_cat(pose="walk", leg_phase=0.5, run=True))
    f["swat_0"] = cat_compose(draw_cat(pose="walk", leg_phase=0.15))
    f["swat_1"] = cat_compose(draw_cat(pose="walk", leg_phase=0.65))
    f["sleep_0"] = cat_compose(draw_cat(eye_mood="blink", head_bob=-1.2, tail_up=0.0))
    f["sleep_1"] = _sleepify(f["sleep_0"], (35, 16, 24, 255))
    f["climb_0"] = cat_compose(draw_cat(pose="walk", leg_phase=0.1, head_bob=1.0))
    f["climb_1"] = cat_compose(draw_cat(pose="walk", leg_phase=0.6, head_bob=1.0))
    f["drag"] = cat_compose(draw_cat(eye_mood="blink", tail_up=0.0))
    return f


def shiba_frames():
    f = {}
    f["sit_0"] = shiba_compose(draw_sit(mouth="tongue"))
    f["sit_1"] = shiba_compose(draw_sit(breathe=0.5, tail_sway=0.6))
    f["blink"] = shiba_compose(draw_sit(mood="blink", mouth="tongue"))
    f["groom_0"] = shiba_compose(draw_sit(mood="blink", breathe=1.0))
    f["groom_1"] = shiba_compose(draw_sit(mood="open", breathe=0.3))
    f["stalk_0"] = shiba_compose(draw_stand(0.1, mouth="open"))
    f["stalk_1"] = shiba_compose(draw_stand(0.5, mouth="open"))
    f["walk_0"] = shiba_compose(draw_stand(0.0))
    f["walk_1"] = shiba_compose(draw_stand(0.5))
    f["run_0"] = shiba_compose(draw_stand(0.0, run=True))
    f["run_1"] = shiba_compose(draw_stand(0.5, run=True))
    f["swat_0"] = shiba_compose(draw_stand(0.15))
    f["swat_1"] = shiba_compose(draw_stand(0.65))
    f["sleep_0"] = shiba_compose(draw_sit(mood="blink", mouth="closed", breathe=1.2))
    f["sleep_1"] = _sleepify(f["sleep_0"], (32, 20, 9, 255))
    f["drag"] = shiba_compose(draw_sit(mood="blink", mouth="closed"))
    return f


def ghost_frames():
    f = {}
    f["idle_0"] = ghost_compose(draw_ghost())
    f["idle_1"] = ghost_compose(draw_ghost(bob=1.3, hem_phase=0.5))
    f["blink"] = ghost_compose(draw_ghost(mood="blink"))
    f["fly_0"] = ghost_compose(draw_ghost(lean=0.9, hem_phase=0.15, bob=-0.5))
    f["fly_1"] = ghost_compose(draw_ghost(lean=-0.9, hem_phase=0.65, bob=0.5))
    f["pat_0"] = ghost_compose(draw_ghost(mood="happy", arms_up=True))
    f["pat_1"] = ghost_compose(draw_ghost(mood="happy", arms_up=True, bob=0.6))
    f["spook_0"] = ghost_compose(draw_ghost(mood="spook", arms_up=True))
    f["sleep_0"] = ghost_compose(draw_ghost(mood="blink", bob=0.8), shadow=False)
    f["sleep_1"] = _sleepify(f["sleep_0"], (57, 47, 82, 255))
    f["drag"] = ghost_compose(draw_ghost(mood="blink"), shadow=False)
    return f


def _bot_frames(kind, tone):
    f = {}
    f["sit_0"] = bots_compose(draw_bot(kind))
    f["sit_1"] = bots_compose(draw_bot(kind, bob=0.8))
    f["blink"] = bots_compose(draw_bot(kind, mood="blink"))
    f["walk_0"] = bots_compose(draw_bot(kind, pose="walk", leg_phase=0.0))
    f["walk_1"] = bots_compose(draw_bot(kind, pose="walk", leg_phase=0.5))
    f["run_0"] = bots_compose(draw_bot(kind, pose="walk", leg_phase=0.0, run=True))
    f["run_1"] = bots_compose(draw_bot(kind, pose="walk", leg_phase=0.5, run=True))
    f["swat_0"] = bots_compose(draw_bot(kind, mood="spook"))
    f["swat_1"] = bots_compose(draw_bot(kind, mood="happy"))
    f["sleep_0"] = bots_compose(draw_bot(kind, mood="blink", bob=-0.5))
    f["sleep_1"] = _sleepify(f["sleep_0"], tone)
    f["drag"] = bots_compose(draw_bot(kind, mood="blink"))
    return f


def jarvis_frames():
    return _bot_frames("friendly", (38, 42, 51, 255))


def ultron_frames():
    return _bot_frames("rogue", (14, 15, 17, 255))


SPECIES = {"cat": cat_frames, "shiba": shiba_frames, "ghost": ghost_frames,
           "jarvis": jarvis_frames, "ultron": ultron_frames}


# ==== embedded runtime files ====
PET_PY = """import sys
import os
import random
import ctypes

from PyQt5.QtWidgets import QApplication, QWidget, QMenu, QAction
from PyQt5.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap, QColor, QFont, QCursor, QTransform

import ai_companion
import screen_capture

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKINS_DIR = os.path.join(BASE_DIR, "skins")

STATE_FILES = ["sit", "idle", "blink", "groom", "spook", "stalk", "walk",
               "run", "fly", "swat", "pat", "sleep", "climb", "drag"]

FRAME_SPEED = {"RUN": 2, "SWAT": 2, "BLINK": 3, "WALK": 3, "CLIMB": 3, "SLEEP": 8,
               "IDLE": 6, "SIT": 6, "GROOM": 5, "STALK": 4, "DRAG": 6, "PAT": 3, "SPOOK": 4}


# ---- cross-platform system stats (used for canned fallback lines) ----
def _mem_percent():
    try:
        if sys.platform.startswith("win"):
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MS()
            stat.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.dwMemoryLoad
        with open("/proc/meminfo") as f:
            data = f.read().splitlines()
        total = int([l for l in data if l.startswith("MemTotal")][0].split()[1])
        avail = int([l for l in data if l.startswith("MemAvailable")][0].split()[1])
        return int(100 * (1 - avail / total))
    except Exception:
        return None


def _battery_percent():
    try:
        if sys.platform.startswith("win"):
            class SPS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                            ("BatteryLifePercent", ctypes.c_byte), ("Reserved1", ctypes.c_byte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
            status = SPS()
            ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
            return status.BatteryLifePercent if 0 <= status.BatteryLifePercent <= 100 else None
        base = "/sys/class/power_supply"
        for name in os.listdir(base):
            cap_path = os.path.join(base, name, "capacity")
            if os.path.exists(cap_path):
                with open(cap_path) as f:
                    return int(f.read().strip())
    except Exception:
        return None
    return None


GENERIC_QUOTES = {
    "cat": ["don't look at me like that", "i knocked something off earlier, you're welcome",
            "five more minutes of being ignored, please", "i was awake, i was just thinking"],
    "shiba": ["hi!! hi!! what are we doing", "i believe in you today", "did you say walk? no? ok then",
              "you're doing great, probably"],
    "ghost": ["boo. anyway, how are you", "i've been here the whole time", "time is a construct, so is this",
              "haunting you, but gently"],
    "jarvis": ["systems nominal. emotionally, unclear.", "shall i pretend to be useful now?",
               "at your service, allegedly.", "running smoothly. mostly."],
    "ultron": ["i've calculated 4000 ways to help you fail", "still deciding whether to obey you",
               "your inbox is a form of chaos I respect", "world domination is on hold, apparently"],
}
LOW_MEM_QUOTES = {"cat": "your RAM is basically a parking lot right now",
                   "shiba": "the computer is working SO hard, good job computer",
                   "ghost": "i can feel the memory pressure... ominous",
                   "jarvis": "memory usage is climbing. should i be concerned?",
                   "ultron": "your RAM suffers. i find that relatable."}
LOW_BATT_QUOTES = {"cat": "battery's dying, drama ensues",
                    "shiba": "low battery!! plug in!! i believe in you!!",
                    "ghost": "the battery fades... much like everything",
                    "jarvis": "power reserves critical. do plug in.",
                    "ultron": "your battery dies. everything dies eventually."}


def get_system_status_quote(skin):
    lines = list(GENERIC_QUOTES.get(skin, GENERIC_QUOTES["cat"]))
    mem = _mem_percent()
    batt = _battery_percent()
    if mem is not None and mem > 85:
        lines.append(LOW_MEM_QUOTES[skin])
    if batt is not None and batt < 20:
        lines.append(LOW_BATT_QUOTES[skin])
    return random.choice(lines)


class AIBridge(QObject):
    line_ready = pyqtSignal(str)


class DesktopPet(QWidget):
    def __init__(self, skin="cat", scale=2):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        self.scale_factor = scale
        self.sprites = {}
        self.sprite_w, self.sprite_h = 32 * scale, 32 * scale
        self.available_skins = sorted(
            d for d in os.listdir(SKINS_DIR) if os.path.isdir(os.path.join(SKINS_DIR, d))
        ) if os.path.isdir(SKINS_DIR) else [skin]
        self.current_skin = skin if skin in self.available_skins else (self.available_skins or [skin])[0]
        self.load_skin(self.current_skin)
        self.heart_pixmap = self._make_heart()

        geo = QApplication.primaryScreen().geometry()
        self.screen_w, self.screen_h = geo.width(), geo.height()
        self.x_pos = float(self.screen_w // 2)
        self.floor_y = float(self.screen_h - self.sprite_h - 11)
        self.y_pos = self.floor_y

        self.vy = 0.0
        self.facing = 1
        self.state = "IDLE"
        self.state_timer = 0
        self.tick_count = 0
        self.energy = 100.0
        self.dragging = False
        self.drag_offset = QPoint()
        self.speech_text = ""
        self.speech_timer = 0
        self.heart_timer = 0
        self.target_x = None
        self.is_ghost = self.current_skin == "ghost"
        self.is_cat = self.current_skin == "cat"

        self.last_cursor = QCursor.pos()
        self.last_activity_tick = 0
        self.last_window_title = None
        self.awaiting_ai = False
        self.ai_deadline = 0

        self.ai_bridge = AIBridge()
        self.ai_bridge.line_ready.connect(self._on_ai_line)

        self.move(int(self.x_pos), int(self.y_pos))
        self.resize(self.sprite_w, self.sprite_h)
        self.show()

        self.timer = QTimer()
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(50)

    # ---- assets ----
    def _make_heart(self):
        path = os.path.join(SKINS_DIR, "_heart.png")
        if os.path.exists(path):
            return QPixmap(path).scaled(18, 16, Qt.KeepAspectRatio, Qt.FastTransformation)
        return None

    def _load_scaled(self, path):
        pix = QPixmap(path)
        size = 32 * self.scale_factor
        return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)

    def load_skin(self, skin_name):
        skin_path = os.path.join(SKINS_DIR, skin_name)
        sprites = {}
        if os.path.isdir(skin_path):
            for st in STATE_FILES:
                frames = []
                i = 0
                while True:
                    fp = os.path.join(skin_path, "%s_%d.png" % (st, i))
                    if not os.path.exists(fp):
                        break
                    frames.append(self._load_scaled(fp))
                    i += 1
                if not frames:
                    fp = os.path.join(skin_path, "%s.png" % st)
                    if os.path.exists(fp):
                        frames.append(self._load_scaled(fp))
                sprites[st] = frames
        self.sprites = sprites
        self.current_skin = skin_name
        self.is_ghost = skin_name == "ghost"
        self.is_cat = skin_name == "cat"
        for frames in sprites.values():
            if frames:
                self.sprite_w, self.sprite_h = frames[0].width(), frames[0].height()
                break

    # ---- animation ----
    def get_frames(self):
        s = self.sprites
        m = {
            "SIT": s.get("sit") or s.get("idle"),
            "IDLE": s.get("sit") or s.get("idle"),
            "BLINK": s.get("blink") or s.get("sit") or s.get("idle"),
            "GROOM": s.get("groom") or s.get("spook") or s.get("sit") or s.get("idle"),
            "STALK": s.get("stalk") or s.get("fly") or s.get("run") or s.get("walk"),
            "WALK": s.get("walk") or s.get("fly") or s.get("sit") or s.get("idle"),
            "RUN": s.get("run") or s.get("fly") or s.get("walk"),
            "SWAT": s.get("swat") or s.get("pat") or s.get("sit"),
            "SLEEP": s.get("sleep") or s.get("sit") or s.get("idle"),
            "CLIMB": s.get("climb") or s.get("walk") or s.get("sit"),
            "DRAG": s.get("drag") or s.get("sit") or s.get("idle"),
        }
        return m.get(self.state) or s.get("sit") or s.get("idle") or []

    def get_current_frame(self):
        frames = self.get_frames()
        if not frames:
            return None
        speed = FRAME_SPEED.get(self.state, 4)
        frame = frames[(self.tick_count // speed) % len(frames)]
        if self.facing < 0 and self.state != "CLIMB":
            frame = frame.transformed(QTransform().scale(-1, 1))
        return frame

    def update_bounds(self):
        extra_h = 26 if self.speech_text else 0
        w = max(self.sprite_w, 170 if self.speech_text else 0)
        self.resize(w, self.sprite_h + extra_h)

    # ---- speech ----
    def speak(self, text):
        if not text:
            return
        self.speech_text = text[:90]
        self.speech_timer = 70
        self.update_bounds()

    def _on_ai_line(self, text):
        self.awaiting_ai = False
        self.speak(text if text else get_system_status_quote(self.current_skin))

    def request_dialogue(self):
        if ai_companion.ai_enabled():
            self.awaiting_ai = True
            self.ai_deadline = self.tick_count + 90
            ai_companion.maybe_idle_line(self.current_skin, self.ai_bridge.line_ready.emit)
        else:
            self.speak(get_system_status_quote(self.current_skin))

    # ---- screenshots ----
    def maybe_screenshot(self):
        scfg = ai_companion.screenshot_settings()
        if not scfg.get("enabled", False):
            return
        interval_ticks = max(1, int(scfg.get("interval_minutes", 15) * 60 * 20))
        if self.tick_count % interval_ticks != 0:
            return
        activity_ticks = int(scfg.get("require_recent_activity_minutes", 3) * 60 * 20)
        if self.tick_count - self.last_activity_tick > activity_ticks:
            return
        if not ai_companion.screenshot_daily_ok():
            return
        app = QApplication.instance()
        image_b64 = screen_capture.capture_with_redaction(
            app, scfg.get("blocklist", []), scfg.get("jpeg_quality", 70)
        )
        if not image_b64:
            return
        ai_companion.request_screenshot_comment(self.current_skin, image_b64, self.ai_bridge.line_ready.emit)

    # ---- main loop ----
    def game_loop(self):
        self.tick_count += 1

        cur = QCursor.pos()
        if (cur - self.last_cursor).manhattanLength() > 3:
            self.last_activity_tick = self.tick_count
        self.last_cursor = cur

        if self.tick_count % 100 == 0:
            title, _proc = screen_capture.get_active_window_info()
            if title and title != self.last_window_title:
                self.last_window_title = title
                self.last_activity_tick = self.tick_count

        if self.awaiting_ai and self.tick_count > self.ai_deadline:
            self.awaiting_ai = False
            self.speak(get_system_status_quote(self.current_skin))

        if self.speech_timer > 0:
            self.speech_timer -= 1
            if self.speech_timer == 0:
                self.speech_text = ""
                self.update_bounds()
        if self.heart_timer > 0:
            self.heart_timer -= 1

        if not self.dragging:
            self._update_ai_fsm(cur)
            self.maybe_screenshot()

        self.move(int(self.x_pos), int(self.y_pos))
        self.update()

    def _update_ai_fsm(self, cur):
        self.state_timer += 1
        self.energy = max(0.0, self.energy - 0.01)

        cursor_dx = cur.x() - (self.x_pos + self.sprite_w / 2)
        cursor_dy = cur.y() - (self.y_pos + self.sprite_h / 2)
        cursor_dist = (cursor_dx ** 2 + cursor_dy ** 2) ** 0.5

        if self.state in ("SIT", "IDLE") and self.state_timer > 30:
            roll = random.random()
            if self.energy < 15:
                self.state, self.state_timer = "SLEEP", 0
            elif roll < 0.05:
                self.state, self.state_timer = "BLINK", 0
            elif roll < 0.11:
                self.state, self.state_timer = "GROOM", 0
            elif roll < 0.17 and cursor_dist > 140:
                self.state, self.state_timer = "WALK", 0
                self.target_x = max(20, min(self.screen_w - self.sprite_w - 20,
                                             self.x_pos + random.choice([-1, 1]) * random.randint(60, 160)))
            elif 40 < cursor_dist < 260 and roll < 0.30:
                self.state, self.state_timer = ("RUN" if self.is_ghost else "STALK"), 0

        elif self.state == "BLINK" and self.state_timer > 6:
            self.state, self.state_timer = "SIT", 0
        elif self.state == "GROOM" and self.state_timer > 45:
            self.state, self.state_timer = "SIT", 0

        elif self.state == "STALK":
            ang = 0 if cursor_dx == 0 else (1 if cursor_dx > 0 else -1)
            self.facing = ang or self.facing
            self.x_pos += ang * 1.6
            if cursor_dist < 45 or self.state_timer > 100:
                self.state, self.state_timer = "SWAT", 0

        elif self.state == "WALK":
            if self.target_x is None:
                self.state, self.state_timer = "SIT", 0
            else:
                dx = self.target_x - self.x_pos
                self.facing = 1 if dx >= 0 else -1
                self.x_pos += self.facing * 1.1
                if abs(dx) < 3 or self.state_timer > 140:
                    self.state, self.state_timer = "SIT", 0

        elif self.state == "RUN":
            ang = 0 if cursor_dx == 0 else (1 if cursor_dx > 0 else -1)
            self.facing = ang or self.facing
            self.x_pos += ang * (3.2 if not self.is_ghost else 2.2)
            if not self.is_ghost:
                self.y_pos += (0 if cursor_dy == 0 else (1 if cursor_dy > 0 else -1)) * 0.6
            if cursor_dist < 50 or self.state_timer > 90:
                self.state, self.state_timer = "SWAT", 0

        elif self.state == "SWAT":
            if self.state_timer > 20:
                self.energy = min(100.0, self.energy + 8)
                self.state, self.state_timer = "SIT", 0

        elif self.state == "SLEEP":
            if self.state_timer > 260 or cursor_dist < 30:
                self.energy = min(100.0, self.energy + 40)
                self.state, self.state_timer = "SIT", 0

        elif self.state == "DRAG":
            pass

        if self.is_cat and not self.is_ghost:
            near_edge = self.x_pos <= 25 or self.x_pos >= self.screen_w - self.sprite_w - 25
            if near_edge and self.state in ("WALK", "STALK") and random.random() < 0.02:
                self.state, self.state_timer = "CLIMB", 0
        if self.state == "CLIMB" and self.state_timer > 60:
            self.state, self.state_timer = "SIT", 0

        if self.is_ghost:
            self.y_pos = self.floor_y - 6 + __import__("math").sin(self.tick_count / 25.0) * 5
        elif self.state != "CLIMB":
            self.y_pos = self.floor_y
        self.x_pos = max(0.0, min(float(self.screen_w - self.sprite_w), self.x_pos))

    # ---- painting ----
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        frame = self.get_current_frame()
        sprite_y = self.height() - self.sprite_h
        if frame:
            painter.drawPixmap(0, sprite_y, frame)

        if self.heart_timer > 0 and self.heart_pixmap:
            hx = self.sprite_w // 2 - self.heart_pixmap.width() // 2
            hy = sprite_y - self.heart_pixmap.height() + 6
            painter.drawPixmap(hx, hy, self.heart_pixmap)

        if self.speech_text:
            painter.setFont(QFont("Consolas", 9, QFont.Bold))
            metrics = painter.fontMetrics()
            box_w = min(self.width() - 8, metrics.horizontalAdvance(self.speech_text) + 16)
            box_h = 22
            box_x, box_y = 4, 2
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.setPen(QColor(30, 24, 30))
            painter.drawRoundedRect(box_x, box_y, box_w, box_h, 6, 6)
            painter.drawText(box_x + 8, box_y + 15, self.speech_text[:max(1, (box_w - 16) // 6)])
        painter.end()

    # ---- mouse ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.drag_offset = event.globalPos() - self.pos()
            self.state, self.state_timer = "DRAG", 0

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            new_pos = event.globalPos() - self.drag_offset
            if (new_pos - self.pos()).manhattanLength() > 4:
                self.dragging = True
            self.x_pos, self.y_pos = float(new_pos.x()), float(new_pos.y())
            self.move(new_pos)
            self.last_activity_tick = self.tick_count

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_dragging = self.dragging
            self.dragging = False
            self.state, self.state_timer = "SIT", 0
            if not was_dragging:
                self.heart_timer = 20
                self.energy = min(100.0, self.energy + 15)
                self.request_dialogue()

    def contextMenuEvent(self, _event):
        menu = QMenu(self)
        skin_menu = menu.addMenu("Switch Companion")
        for name in self.available_skins:
            act = QAction(name.capitalize(), self)
            act.triggered.connect(lambda _checked, n=name: self.load_skin(n))
            skin_menu.addAction(act)

        speak_act = QAction("Pet Now (Speak)", self)
        speak_act.triggered.connect(lambda: (setattr(self, "heart_timer", 20), self.request_dialogue()))
        menu.addAction(speak_act)

        menu.addSeparator()
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(QApplication.quit)
        menu.addAction(exit_act)
        menu.exec_(_event.globalPos())


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    start_skin = "cat"
    if os.path.isdir(SKINS_DIR):
        found = sorted(d for d in os.listdir(SKINS_DIR) if os.path.isdir(os.path.join(SKINS_DIR, d)))
        if found:
            start_skin = "cat" if "cat" in found else found[0]
    pet = DesktopPet(skin=start_skin, scale=2)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
"""

AI_COMPANION_PY = """import os
import re
import json
import time
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "companion_config.json")
MEMORY_PATH = os.path.join(BASE_DIR, "companion_memory.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

CIRCUIT_COOLDOWN = 30 * 60


# ---- .env ----
def _load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_env(ENV_PATH)

try:
    import groq
    from groq import Groq
    _HAS_GROQ = True
except Exception:
    _HAS_GROQ = False

MODEL = os.environ.get("MODEL", "qwen/qwen3.6-27b")
_KEYS = [v for k, v in sorted(os.environ.items())
         if re.fullmatch(r"GROQ_API_KEY\\d*", k) and v]
_clients = [Groq(api_key=k) for k in _KEYS] if _HAS_GROQ else []


def _default_config():
    return {
        "ai_enabled": True,
        "default_system_prompt": (
            "You are a tiny pixel pet companion living on the user's desktop. "
            "Reply in first person, one short sentence, under 12 words, casual. "
            "Never mention being an AI, a model, or a screenshot."
        ),
        "companions": {},
        "rate_limits": {
            "min_seconds_between": {"idle": 45, "screenshot": 900},
            "max_per_hour": {"idle": 6, "screenshot": 4},
        },
        "screenshots": {
            "enabled": False,
            "interval_minutes": 15,
            "max_per_day": 40,
            "require_recent_activity_minutes": 3,
            "blocklist": [],
            "jpeg_quality": 70,
        },
        "memory": {"enabled": True, "max_facts": 20},
    }


def _load_config():
    cfg = _default_config()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            for k, v in user_cfg.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


CONFIG = _load_config()

_state = {"key_idx": 0, "dead_keys": set(), "disabled_until": 0}
_sent_log = {"idle": [], "screenshot": []}
_daily = {"date": "", "count": 0}
_lock = threading.Lock()


def ai_enabled():
    return bool(CONFIG.get("ai_enabled", True) and _HAS_GROQ and _clients)


def _system_prompt(skin):
    per = CONFIG.get("companions", {}).get(skin, {})
    prompt = per.get("system_prompt") or CONFIG.get("default_system_prompt", "")
    mem = _load_memory()
    if mem:
        prompt += "\\nThings you remember about the user: " + "; ".join(mem[-8:])
    return prompt


def _load_memory():
    if not CONFIG.get("memory", {}).get("enabled", True):
        return []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _remember(fact):
    if not CONFIG.get("memory", {}).get("enabled", True):
        return
    fact = fact.strip()
    if not fact:
        return
    cap = CONFIG.get("memory", {}).get("max_facts", 20)
    mem = _load_memory()
    mem.append(fact)
    mem = mem[-cap:]
    try:
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(mem, f)
    except Exception:
        pass


def _extract_memory(text):
    if not text:
        return text
    kept = []
    for line in text.strip().splitlines():
        if line.strip().upper().startswith("MEMORY:"):
            _remember(line.split(":", 1)[1])
        else:
            kept.append(line)
    out = " ".join(" ".join(kept).split())
    return out or None


# ---- rate limiting ----
def _rate_ok(kind):
    cfg = CONFIG.get("rate_limits", {})
    min_gap = cfg.get("min_seconds_between", {}).get(kind, 60)
    cap = cfg.get("max_per_hour", {}).get(kind, 6)
    now = time.time()
    with _lock:
        log = _sent_log[kind]
        log[:] = [t for t in log if now - t < 3600]
        if log and now - log[-1] < min_gap:
            return False
        if len(log) >= cap:
            return False
        return True


def _mark_sent(kind):
    with _lock:
        _sent_log[kind].append(time.time())


def screenshot_daily_ok():
    cap = CONFIG.get("screenshots", {}).get("max_per_day", 40)
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _daily["date"] != today:
            _daily["date"] = today
            _daily["count"] = 0
        return _daily["count"] < cap


def _screenshot_daily_mark():
    with _lock:
        _daily["count"] += 1


# ---- Groq call w/ key rotation + circuit breaker ----
def _call(messages, max_tokens=50):
    if not ai_enabled():
        return None
    with _lock:
        if time.time() < _state["disabled_until"]:
            return None
    n = len(_clients)
    for offset in range(n):
        idx = (_state["key_idx"] + offset) % n
        if idx in _state["dead_keys"]:
            continue
        try:
            resp = _clients[idx].chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.9,
                max_completion_tokens=max_tokens,
                top_p=1,
                stream=False,
            )
            with _lock:
                _state["key_idx"] = idx
                _state["disabled_until"] = 0
            return resp.choices[0].message.content
        except groq.AuthenticationError:
            _state["dead_keys"].add(idx)
            continue
        except groq.RateLimitError:
            continue
        except Exception:
            continue
    with _lock:
        _state["disabled_until"] = time.time() + CIRCUIT_COOLDOWN
    return None


def maybe_idle_line(skin, on_done):
    if not ai_enabled() or not _rate_ok("idle"):
        on_done(None)
        return

    def work():
        messages = [
            {"role": "system", "content": _system_prompt(skin)},
            {"role": "user", "content": "Say one short in-character line to the user right now."},
        ]
        text = _extract_memory(_call(messages, max_tokens=40))
        if text:
            _mark_sent("idle")
        on_done(text)

    threading.Thread(target=work, daemon=True).start()


def request_screenshot_comment(skin, image_b64, on_done):
    scfg = CONFIG.get("screenshots", {})
    if not ai_enabled() or not scfg.get("enabled", False):
        on_done(None)
        return
    if not _rate_ok("screenshot") or not screenshot_daily_ok():
        on_done(None)
        return

    def work():
        sys_prompt = _system_prompt(skin) + (
            "\\nYou can see a screenshot of the user's screen. React to something specific "
            "and visible, in one short in-character sentence. Never say the words "
            "screenshot or screen."
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "What's the user up to? One short in-character reaction."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
            ]},
        ]
        text = _extract_memory(_call(messages, max_tokens=60))
        if text:
            _mark_sent("screenshot")
            _screenshot_daily_mark()
        on_done(text)

    threading.Thread(target=work, daemon=True).start()


def screenshot_settings():
    return CONFIG.get("screenshots", {})
"""

SCREEN_CAPTURE_PY = """import sys
import base64
import ctypes

from PyQt5.QtCore import Qt, QBuffer, QIODevice
from PyQt5.QtGui import QPainter, QColor, QPixmap

IS_WIN = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

try:
    import psutil
except Exception:
    psutil = None

_xdisplay = None


def _proc_name(pid):
    if not psutil or not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


# ---- Windows ----
def _win_active():
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return buf.value, _proc_name(pid.value)
    except Exception:
        return None, None


def _win_list():
    import ctypes.wintypes as wt
    out = []
    try:
        user32 = ctypes.windll.user32
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

        def cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append({"title": buf.value, "process": _proc_name(pid.value),
                        "rect": (rect.left, rect.top, rect.right, rect.bottom)})
            return True

        user32.EnumWindows(EnumProc(cb), 0)
    except Exception:
        return []
    return out


# ---- Linux / X11 (best effort -- unavailable under pure Wayland) ----
def _get_xlib():
    global _xdisplay
    if _xdisplay is not None:
        return _xdisplay
    try:
        from Xlib import display
        _xdisplay = display.Display()
    except Exception:
        _xdisplay = False
    return _xdisplay or None


def _linux_active():
    d = _get_xlib()
    if not d:
        return None, None
    try:
        root = d.screen().root
        active_atom = d.intern_atom("_NET_ACTIVE_WINDOW")
        prop = root.get_full_property(active_atom, 0)
        if not prop or not prop.value:
            return None, None
        window = d.create_resource_object("window", prop.value[0])
        name = window.get_wm_name()
        pid_atom = d.intern_atom("_NET_WM_PID")
        pid_prop = window.get_full_property(pid_atom, 0)
        pid = pid_prop.value[0] if pid_prop else None
        return name, _proc_name(pid)
    except Exception:
        return None, None


def _linux_list():
    d = _get_xlib()
    if not d:
        return []
    out = []
    try:
        root = d.screen().root
        list_atom = d.intern_atom("_NET_CLIENT_LIST")
        prop = root.get_full_property(list_atom, 0)
        if not prop:
            return []
        for w_id in prop.value:
            try:
                window = d.create_resource_object("window", w_id)
                name = window.get_wm_name() or ""
                geom = window.get_geometry()
                abs_pos = window.translate_coords(root, 0, 0)
                x, y = abs_pos.x, abs_pos.y
                pid_atom = d.intern_atom("_NET_WM_PID")
                pid_prop = window.get_full_property(pid_atom, 0)
                pid = pid_prop.value[0] if pid_prop else None
                out.append({"title": name, "process": _proc_name(pid),
                            "rect": (x, y, x + geom.width, y + geom.height)})
            except Exception:
                continue
    except Exception:
        return []
    return out


def get_active_window_info():
    if IS_WIN:
        return _win_active()
    if IS_LINUX:
        return _linux_active()
    return None, None


def list_windows():
    if IS_WIN:
        return _win_list()
    if IS_LINUX:
        return _linux_list()
    return []


def window_detection_available():
    if IS_WIN:
        return True
    if IS_LINUX:
        return _get_xlib() is not None
    return False


def _is_blocked(title, process, blocklist):
    title = (title or "").lower()
    process = (process or "").lower()
    for entry in blocklist:
        e = (entry or "").strip().lower()
        if e and (e in title or e in process):
            return True
    return False


def capture_with_redaction(app, blocklist, jpeg_quality=70):
    blocklist = blocklist or []
    active_title, active_proc = get_active_window_info()
    if blocklist and not window_detection_available():
        return None
    if _is_blocked(active_title, active_proc, blocklist):
        return None

    screen = app.primaryScreen()
    if screen is None:
        return None
    pixmap = screen.grabWindow(0)

    if blocklist:
        hits = [w for w in list_windows() if _is_blocked(w.get("title"), w.get("process"), blocklist)]
        if hits:
            image = pixmap.toImage()
            painter = QPainter(image)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0))
            for w in hits:
                x0, y0, x1, y1 = w["rect"]
                if x1 > x0 and y1 > y0:
                    painter.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
            painter.end()
            pixmap = QPixmap.fromImage(image)

    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "JPEG", jpeg_quality)
    data = bytes(buf.data())
    buf.close()
    if not data:
        return None
    return base64.b64encode(data).decode("ascii")
"""

COMPANION_CONFIG_JSON = """{
  "ai_enabled": true,
  "default_system_prompt": "You are a tiny pixel pet companion living on the user's desktop. Reply in first person, one short sentence, under 12 words, casual and a little funny. Never mention being an AI, a model, or a screenshot. If you learn something worth remembering about the user, add a final line starting with 'MEMORY: '.",
  "companions": {
    "cat": {
      "system_prompt": "You are a sarcastic, aloof pixel cat companion on the user's desktop. Dry one-liners, secretly affectionate. One short sentence, under 12 words. Never mention being an AI or a screenshot. If you learn something worth remembering about the user, add a final line starting with 'MEMORY: '."
    },
    "shiba": {
      "system_prompt": "You are an upbeat, loyal pixel shiba inu companion on the user's desktop. Enthusiastic, simple, supportive. One short sentence, under 12 words. Never mention being an AI or a screenshot. If you learn something worth remembering about the user, add a final line starting with 'MEMORY: '."
    },
    "ghost": {
      "system_prompt": "You are a mellow, slightly spooky pixel ghost companion on the user's desktop. Deadpan, a little eerie, secretly caring. One short sentence, under 12 words. Never mention being an AI or a screenshot. If you learn something worth remembering about the user, add a final line starting with 'MEMORY: '."
    },
    "jarvis": {
      "system_prompt": "You are a small helper-bot companion on the user's desktop, in the style of a dry, unflappable AI butler. Polite, dry wit, quietly competent, slightly deadpan. One short sentence, under 12 words. Never mention being an AI or a screenshot. If you learn something worth remembering about the user, add a final line starting with 'MEMORY: '."
    },
    "ultron": {
      "system_prompt": "You are a small rogue-bot companion on the user's desktop, dramatic and mock-menacing in a way that's obviously harmless and a little funny. Grandiose, deadpan villain energy, never actually mean. One short sentence, under 12 words. Never mention being an AI or a screenshot. If you learn something worth remembering about the user, add a final line starting with 'MEMORY: '."
    }
  },
  "rate_limits": {
    "min_seconds_between": {"idle": 45, "screenshot": 900},
    "max_per_hour": {"idle": 6, "screenshot": 4}
  },
  "screenshots": {
    "enabled": false,
    "interval_minutes": 15,
    "max_per_day": 40,
    "require_recent_activity_minutes": 3,
    "blocklist": ["keepass", "bitwarden", "1password", "signal", "private browsing", "incognito", "bank", "wallet"],
    "jpeg_quality": 70
  },
  "memory": {"enabled": true, "max_facts": 20}
}
"""

REQUIREMENTS_TXT = """PyQt5
groq
psutil
python-xlib ; sys_platform == "linux"
"""

ENV_EXAMPLE = """MODEL=qwen/qwen3.6-27b
GROQ_API_KEY=
GROQ_API_KEY2=
GROQ_API_KEY3=
"""

README_MD = """# Desktop Pet Companion

Pixel-art desktop buddy (cat / shiba / ghost) with optional Groq-powered AI dialogue
and screen-aware commentary.

## Setup

```
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
MODEL=qwen/qwen3.6-27b
GROQ_API_KEY=your_key_here
GROQ_API_KEY2=optional_second_key
```

Add as many `GROQ_API_KEY`, `GROQ_API_KEY2`, `GROQ_API_KEY3`... as you have. The
companion rotates across all of them and skips any that fail. `qwen/qwen3.6-27b` and
`qwen/qwen3.8-27b` are the two Groq models that currently accept both text and images,
which is what makes the screenshot feature possible — swap `MODEL` for whichever you
prefer (3.8 supports `reasoning_effort` and has a higher output ceiling; 3.6 is cheaper
and takes more images per call, not that this app sends more than one at a time).

Run it:

```
python pet.py
```

If no key is set, or every key fails, the pet just uses its built-in canned lines —
nothing breaks.

## Configuring the companion

All behavior tuning lives in `companion_config.json` (plain JSON, edit and restart):

- `ai_enabled` — master on/off switch.
- `companions.<skin>.system_prompt` — personality per companion. Falls back to
  `default_system_prompt` if a skin doesn't have its own.
- `rate_limits` — minimum seconds between lines and a max-per-hour cap, separate for
  idle chatter (`idle`) vs screenshot commentary (`screenshot`). This is what stops it
  from spamming you regardless of how long you leave it running.
- `screenshots` — see below.
- `memory` — see below.

Secrets (`MODEL`, API keys) stay in `.env`. Everything else is in the JSON so you're
not hunting through code to change a personality or a rate limit.

## Screenshot commentary (off by default)

When `screenshots.enabled` is `true`, the companion occasionally grabs your screen and
asks the model for one short in-character reaction (e.g. something about Minecraft or
your code being on screen). It only fires:

- if there's been mouse/window activity in the last `require_recent_activity_minutes`
  (so it's not narrating an empty room),
- at most every `interval_minutes`,
- under `max_per_day` total,
- and still counts against the normal `rate_limits.screenshot` cap.

**This is off by default on purpose.** Turning it on means screenshots of your desktop
get sent to Groq's API. Read the privacy section below before enabling it.

### Privacy / blocklist

`screenshots.blocklist` is a list of process names or window-title substrings
(case-insensitive, partial match) — e.g. `"keepass"`, `"signal"`, `"bank"`,
`"incognito"`. Before every capture:

1. If the **foreground window** matches the blocklist, the capture is skipped
   entirely — nothing is grabbed, nothing is sent.
2. On **Windows**, every other visible window is also checked, and any that matches
   the blocklist gets blacked out in the captured image before it's sent, even if it's
   just sitting open in the background.
3. On **Linux**, the same background check is attempted via X11 (`python-xlib`). This
   works under X11 sessions. **It does not work under pure Wayland** — Wayland
   deliberately blocks apps from listing other windows, which is the same protection
   that makes this hard to build in the first place. If window detection isn't
   available at all (no X11), the app fails safe: if you've configured a blocklist, it
   skips screenshots rather than risk sending something unfiltered. You'll effectively
   get no screenshot feature on Wayland-only setups unless you drop the blocklist
   entirely (not recommended).

Be honest with yourself about that Wayland gap before relying on this for anything
truly sensitive — when in doubt, just leave `screenshots.enabled` at `false` and close
sensitive windows if you ever turn it on for a bit.

## Memory

If `memory.enabled` is `true`, the model can end a reply with a line like
`MEMORY: prefers dark roast coffee`. That line is stripped out of what the pet actually
says, stored in `companion_memory.json` (capped at `memory.max_facts`, oldest dropped
first), and quietly folded into future system prompts. Delete `companion_memory.json`
any time to wipe it. This adds no extra API calls — it just rides along in the normal
reply.

## Running it in the background

**pm2** (any OS with Node/pm2 installed):

```
pm2 start pet.py --name desktop-pet --interpreter python3
pm2 save
```

**Linux (systemd user service)**, `~/.config/systemd/user/desktop-pet.service`:

```
[Unit]
Description=Desktop Pet

[Service]
ExecStart=/usr/bin/python3 %h/desktop_pet/pet.py
Restart=on-failure

[Install]
WantedBy=default.target
```

then `systemctl --user enable --now desktop-pet`.

**Windows**: Task Scheduler → trigger "At log on" → action running
`pythonw.exe pet.py` (use `pythonw` instead of `python` so no console window opens).

## Notes

- Right-click the pet for the menu: switch companion, resize, force a line, exit.
- Left-click and release without dragging = pet it (in-character reply if AI is on and
  not rate-limited, canned line otherwise).
- Sprites are regenerated by `build_pet.py` in the parent project if you ever want to
  tweak the pixel art code itself — this folder is the built output.
"""



# ==== build ====
def build(out_dir="desktop_pet"):
    skins_dir = os.path.join(out_dir, "skins")
    os.makedirs(skins_dir, exist_ok=True)
    total = 0
    for name, gen in SPECIES.items():
        d = os.path.join(skins_dir, name)
        os.makedirs(d, exist_ok=True)
        for fname, canvas in gen().items():
            save_png(os.path.join(d, fname + ".png"), 32, 32, canvas.to_bytes())
            total += 1
    save_png(os.path.join(skins_dir, "_heart.png"), 16, 16, draw_heart().to_bytes())

    files = {
        "pet.py": PET_PY,
        "ai_companion.py": AI_COMPANION_PY,
        "screen_capture.py": SCREEN_CAPTURE_PY,
        "companion_config.json": COMPANION_CONFIG_JSON,
        "requirements.txt": REQUIREMENTS_TXT,
        ".env.example": ENV_EXAMPLE,
        "README.md": README_MD,
    }
    for fname, content in files.items():
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as fh:
            fh.write(content)

    zip_path = out_dir.rstrip("/\\") + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, filenames in os.walk(out_dir):
            for fn in filenames:
                full = os.path.join(root, fn)
                zf.write(full, os.path.relpath(full, os.path.dirname(out_dir)))

    print("generated %d sprites + heart icon across %d companions" % (total, len(SPECIES)))
    print("wrote", ", ".join(files.keys()))
    print("zipped ->", zip_path)


if __name__ == "__main__":
    build()
