"""The phoenix: its flight path and its articulated body.

The bird is a bold silhouette: one body shape, each wing one swept shape with a
few primary tips, three tail ribbons and a short crest, shaded in flat bands.
Wings are posed in 3D and projected, so a flap reads as flight: spread on the
upstroke, swept under the body on the downstroke, with the tips lagging behind
the shoulders. Tail ribbons follow the path the bird actually flew, so they
whip through turns and loops.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import ImageDraw

from pixelart import lerp

FIRE, GOLD = 0, 2


def _round(pts, passes: int = 2):
    """Corner-cut a closed polygon, so bodies read as curves instead of facets."""
    for _ in range(passes):
        out = []
        for i, a in enumerate(pts):
            b = pts[(i + 1) % len(pts)]
            out.append((a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25))
            out.append((a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75))
        pts = out
    return pts


@dataclass(frozen=True)
class Look:
    size: float
    girth: float
    span: float
    tail: float
    plumes: int
    flap: float  # seconds per wingbeat
    flap_angle: float  # degrees
    flame_rate: float  # particles per second
    flame_life: float  # seconds
    glow: float
    glow_r: float
    rain: int
    altitude: float  # fraction of the sky, smaller is higher
    amplitude: float
    loop: float  # loop-the-loop radius
    duration: float  # seconds for one crossing


def look_for(h: float) -> Look:
    return Look(
        size=lerp(0.74, 1.12, h),
        girth=lerp(0.72, 1.08, h),
        span=lerp(0.82, 1.15, h),
        tail=lerp(0.55, 1.45, h),
        plumes=round(lerp(3, 7, h)),
        flap=lerp(1.25, 0.42, h),
        flap_angle=lerp(36, 62, h),
        flame_rate=lerp(26, 420, h**1.2),
        flame_life=lerp(0.5, 1.15, h),
        glow=lerp(0.18, 0.62, h),
        glow_r=lerp(26, 70, h),
        rain=round(max(0.0, (h - 0.55) / 0.45) * 70),
        altitude=lerp(0.66, 0.42, h),
        amplitude=lerp(4, 20, h),
        loop=max(0.0, (h - 0.68) / 0.32) * 25,
        duration=lerp(11, 8, h),
    )


class Path:
    """A polyline traveled at constant speed, extended straight past its ends."""

    def __init__(self, xs: np.ndarray, ys: np.ndarray, duration: float):
        self.xs, self.ys = xs, ys
        seg = np.hypot(np.diff(xs), np.diff(ys))
        self.arc = np.concatenate([[0], np.cumsum(seg)])
        self.duration = duration
        self.speed = self.arc[-1] / duration
        self.start_dir = np.array([xs[1] - xs[0], ys[1] - ys[0]]) / max(seg[0], 1e-6)
        self.end_dir = np.array([xs[-1] - xs[-2], ys[-1] - ys[-2]]) / max(seg[-1], 1e-6)

    def pos(self, t: float) -> np.ndarray:
        s = t * self.speed
        if s <= 0:
            return np.array([self.xs[0], self.ys[0]]) + self.start_dir * s
        if s >= self.arc[-1]:
            return np.array([self.xs[-1], self.ys[-1]]) + self.end_dir * (s - self.arc[-1])
        return np.array([np.interp(s, self.arc, self.xs), np.interp(s, self.arc, self.ys)])

    def angle(self, t: float) -> float:
        # A wide window, so small wobbles in the path don't re-rotate the sprite.
        d = self.pos(t + 0.08) - self.pos(t - 0.08)
        return math.atan2(d[1], d[0])


def flight_path(look: Look, width: int, sky: int) -> Path:
    x0, x1 = -135.0, width + 135.0
    us = np.linspace(0, 1, 1800)
    xs = lerp(x0, x1, us)
    alt = sky * look.altitude
    ys = alt + look.amplitude * np.sin(2 * math.pi * 1.6 * us + 0.5) + 0.12 * look.amplitude * np.sin(
        2 * math.pi * 3.7 * us
    )
    if look.loop > 0:
        # Sink a little first, so the top of the loop stays inside the frame.
        ys = lerp(ys, alt + look.loop * 0.72, np.sin(math.pi * us) ** 10)
        a, b = 0.5, 0.57
        inside = (us > a) & (us < b)
        u = (us[inside] - a) / (b - a)
        phi = 2 * math.pi * u * u * (3 - 2 * u)
        xs = xs.copy()
        xs[inside] -= look.loop * np.sin(phi)
        ys[inside] -= look.loop * (1 - np.cos(phi))
    return Path(xs, ys, look.duration)


def rise_path(x: float, base: float, width: int, duration: float) -> Path:
    """Up out of the ash, a turn over the sky, then out to the right."""
    ts = np.linspace(0, 1, 600)
    p = [(x, base), (x - 6, base - 62), (x + 34, base - 92), (x + 150, base - 60), (width + 145, base - 74)]
    # A Catmull-Rom style blend through the control points.
    pts = np.array(p, dtype=float)
    n = len(pts) - 1
    out = []
    for t in ts:
        f = min(t * n, n - 1e-6)
        i = int(f)
        u = f - i
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, n)]
        out.append(
            0.5
            * (
                2 * p1
                + (p2 - p0) * u
                + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u
                + (3 * p1 - p0 - 3 * p2 + p3) * u * u * u
            )
        )
    arr = np.array(out)
    return Path(arr[:, 0], arr[:, 1], duration)


class Pose:
    """Turns local bird coordinates (facing +x, y down) into screen pixels."""

    def __init__(self, position: np.ndarray, angle: float, size: float):
        # Whole pixels, so the sprite slides rigidly instead of re-rasterizing.
        self.position = np.round(position)
        self.c, self.s = math.cos(angle), math.sin(angle)
        self.size = size

    def point(self, x: float, y: float) -> tuple[float, float]:
        x, y = x * self.size, y * self.size
        return (
            self.position[0] + x * self.c - y * self.s,
            self.position[1] + x * self.s + y * self.c,
        )

    def points(self, pts) -> list[tuple[float, float]]:
        return [self.point(x, y) for x, y in pts]


def wing_skeleton(phase: float, look: Look, side: int) -> list[tuple[float, float, np.ndarray]]:
    """Points along the wing's leading edge: (x, y, outward direction in 2D).

    `side` is +1 for the near wing and -1 for the far one. The wing lives in 3D
    and is projected with the camera slightly above the bird.
    """
    amp = math.radians(look.flap_angle)
    # Smooth all the way round, so the span never snaps.
    upstroke = (0.5 + 0.5 * math.cos(phase)) ** 1.5
    span = 33 * look.span * (1 - 0.24 * upstroke)
    x, y, z = 8.0, -6.0, 0.0
    tilt, skew = 0.62, 0.16
    n = 6
    step = span / n
    out = []
    for i in range(n + 1):
        r = i / n
        # The tip lags the shoulder, which is what makes the flap look loose.
        psi = math.radians(10) + amp * math.sin(phase - 1.05 * r) + 0.3 * r * upstroke
        # Swept back toward the tip.
        sweep = lerp(0.1, 0.95, r)
        dy, dz = -math.sin(psi), math.cos(psi)
        px, py = x + skew * z * side, y + tilt * z * side
        out.append((px, py, np.array([-sweep * 0.8, dy + tilt * dz * side])))
        x -= sweep * step * 0.8
        y += dy * step
        z += dz * step
    return out


def _feather(root, tip, width, bend=0.0):
    """A tapered, slightly curved feather as polygon points."""
    rx, ry = root
    tx, ty = tip
    dx, dy = tx - rx, ty - ry
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    left, right = [], []
    for i in range(6):
        s = i / 5
        cx = rx + dx * s + nx * bend * math.sin(math.pi * s)
        cy = ry + dy * s + ny * bend * math.sin(math.pi * s)
        w = width * math.sin(math.pi * min(1.0, s * 0.93 + 0.07) ** 0.72)
        left.append((cx + nx * w, cy + ny * w))
        right.append((cx - nx * w, cy - ny * w))
    return left + right[::-1]


class Canvas:
    """Two 'L' images in lockstep: a shading value and a ramp index per pixel."""

    def __init__(self, value_image, part_image):
        self.value = ImageDraw.Draw(value_image)
        self.part = ImageDraw.Draw(part_image)

    def polygon(self, pts, value: float, part: int = FIRE, edge: float | None = None):
        pts = [(round(x), round(y)) for x, y in pts]
        fill = max(1, int(value * 255))
        outline = max(1, int(edge * 255)) if edge is not None else None
        self.value.polygon(pts, fill=fill, outline=outline)
        self.part.polygon(pts, fill=part, outline=part)

    def line(self, pts, value: float, part: int = FIRE, width: int = 1):
        pts = [(round(x), round(y)) for x, y in pts]
        self.value.line(pts, fill=max(1, int(value * 255)), width=width)
        self.part.line(pts, fill=part, width=width)

    def disc(self, x: float, y: float, r: float, value: float, part: int = FIRE):
        box = (round(x - r), round(y - r), round(x + r), round(y + r))
        self.value.ellipse(box, fill=max(1, int(value * 255)))
        self.part.ellipse(box, fill=part)


def _along(bones, idx: float):
    """A point and outward direction partway along the leading edge."""
    i = min(int(idx), len(bones) - 2)
    u = idx - i
    a, b = bones[i], bones[i + 1]
    return lerp(a[0], b[0], u), lerp(a[1], b[1], u), lerp(a[2], b[2], u)


def draw_wing(cv: Canvas, pose: Pose, phase: float, look: Look, side: int) -> None:
    """One swept shape with a lit leading band and a few primary tips at the hand."""
    bones = wing_skeleton(phase, look, side)
    shade = 0.62 if side < 0 else 1.0

    def trail(x, y, out, length, spread):
        # The trailing edge sits back from the leading edge, fanning out toward the tip.
        dx = -math.cos(spread) + out[0] * 0.35 * math.sin(spread)
        dy = out[1] * math.sin(spread) * 0.95
        norm = math.hypot(dx, dy) or 1.0
        return x + dx / norm * length, y + dy / norm * length

    n = len(bones) - 1
    lead = [(b[0], b[1]) for b in bones]
    back, band = [], []
    for i, (x, y, out) in enumerate(bones):
        r = i / n
        chord = lerp(18, 11, r) * look.span
        spread = lerp(0.2, 1.1, r)
        back.append(trail(x, y, out, chord, spread))
        band.append(trail(x, y, out, chord * 0.42, spread))
    cv.polygon(_round(pose.points(lead + back[::-1]), 1), 0.42 * shade, FIRE, edge=0.16 * shade)

    # Primary tips: long and fanned, hottest at the ends.
    for k in range(5):
        f = k / 4
        x, y, out = _along(bones, 3.4 + f * 2.6)
        tip = trail(x, y, out, (19 + 9 * f) * look.span, lerp(0.85, 1.6, f))
        cv.polygon(pose.points(_feather((x, y), tip, 2.6, bend=1.2 * side)), 0.42 * shade, FIRE, edge=0.16 * shade)
        mid = (x * 0.4 + tip[0] * 0.6, y * 0.4 + tip[1] * 0.6)
        cv.polygon(pose.points(_feather(mid, tip, 1.6)), 0.95 * shade, FIRE)

    cv.polygon(_round(pose.points(lead + band[::-1]), 1), 0.72 * shade, FIRE)
    cv.line(pose.points(lead[:6]), 0.85 * shade, GOLD, width=max(2, round(2 * look.size)))


def draw_ribbon(cv: Canvas, points: list, width: float, value: float, part: int, edge: float | None = None):
    """A ribbon through screen points, widening toward the far end."""
    left, right = [], []
    n = len(points)
    for i, (x, y) in enumerate(points):
        a = points[max(i - 1, 0)]
        b = points[min(i + 1, n - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        w = width * (0.35 + 0.65 * (i / max(n - 1, 1)) ** 1.4)
        if i == n - 1:
            w *= 0.4
        left.append((x - dy / length * w, y + dx / length * w))
        right.append((x + dy / length * w, y - dx / length * w))
    cv.polygon(left + right[::-1], value, part, edge=edge)


def trailing_points(path_pos, t: float, count: int, spacing: float, wave: float, fan: float, phase: float, origin):
    """Screen points that follow where the bird has been, with a travelling wave."""
    pts = [tuple(origin)]
    for k in range(1, count + 1):
        p = path_pos(t - k * spacing)
        q = path_pos(t - k * spacing - 0.02)
        d = p - q
        length = math.hypot(d[0], d[1]) or 1.0
        nx, ny = -d[1] / length, d[0] / length
        f = k / count
        off = fan * f**1.15 + wave * f * math.sin(phase + f * 5.2 - t * 7.5)
        # Blend from the body out to the flown path.
        blend = min(1.0, f * 1.6)
        x = lerp(origin[0] + (p[0] - path_pos(t)[0]), p[0], blend) + nx * off
        y = lerp(origin[1] + (p[1] - path_pos(t)[1]), p[1], blend) + ny * off
        pts.append((x, y))
    return pts


def draw_bird(cv: Canvas, path_pos, angle: float, t: float, phase: float, look: Look, h: float) -> None:
    """Draw the whole bird, back to front."""
    position = path_pos(t)
    # The body rides the wingbeat: a small lift on each downstroke.
    bob = np.array([0.0, -1.2 * look.size * math.cos(phase)])
    pose = Pose(position + bob, angle, look.size)

    # Far wing first, so the body overlaps it.
    draw_wing(cv, pose, phase - 0.25, look, -1)

    # Three tail ribbons whip along the flown path, the center one longest.
    root = pose.point(-24, 3)
    speed = max(np.hypot(*(path_pos(t + 0.05) - position)) * 20, 1)
    tail_px = 74 * look.tail
    for i, f in ((0, -1.0), (2, 1.0), (1, 0.0)):
        length = tail_px * (1 - abs(f) * 0.3)
        pts = trailing_points(path_pos, t, 12, length / 12 / speed, 2.0 + 1.5 * look.tail, f * 16 * look.tail, i * 1.3, root)
        draw_ribbon(cv, pts, 3.0 * look.size, 0.6, FIRE, edge=0.2)
        draw_ribbon(cv, pts[3:], 1.4 * look.size, 0.95, GOLD if f == 0 else FIRE)

    # Body, neck and head as one silhouette.
    g = look.girth
    hx, hy = 32.0, -15.0
    body = [
        (-27, 3), (-18, -3 * g), (-7, -7 * g), (6, -9 * g), (14, -10), (20, -13),
        (hx - 6, hy - 3), (hx - 1, hy - 5), (hx + 4, hy - 2), (hx + 3, hy + 3),
        (hx - 3, hy + 5), (24, -4), (20, 3), (10, 8 * g), (-5, 8 * g), (-17, 6 * g),
    ]
    cv.polygon(_round(pose.points(body)), 0.62, FIRE, edge=0.15)
    breast = [(-15, 5 * g), (-2, 6.5 * g), (11, 5 * g), (19, 1), (23, -5), (hx - 3, hy + 3), (hx - 5, hy), (17, -3), (5, 2 * g), (-8, 3 * g)]
    cv.polygon(_round(pose.points(breast), 1), 0.86, FIRE)

    # A short crest swept back off the crown.
    for i in range(2):
        length = (11 + 6 * h) * (1 - i * 0.2)
        rise = 1.0 - i * 0.4
        flutter = 1.0 * math.sin(t * 9 + i * 1.7)
        pts = []
        for k in range(5):
            s_ = k / 4
            pts.append((hx - 3 - length * s_ * (1 - rise * 0.45), hy - 4 - length * s_ * rise * (1 - 0.35 * s_) + flutter * s_ * s_))
        draw_ribbon(cv, pose.points(pts), 0.9 * look.size, 0.75, GOLD)

    beak = pose.points([(hx + 3, hy - 2.5), (hx + 10, hy - 0.5), (hx + 3, hy + 2)])
    cv.polygon(beak, 0.8, GOLD, edge=0.12)
    ex, ey = pose.point(hx + 1, hy - 1)
    cv.disc(ex, ey, 0.6, 0.02, FIRE)

    # Near wing last, over the body.
    draw_wing(cv, pose, phase, look, 1)
