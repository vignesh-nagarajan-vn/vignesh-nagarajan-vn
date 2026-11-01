"""The desert behind the phoenix: sky, sun, Camelback, the data ridge, saguaros.

The nearest ridge is drawn from the account's weekly contributions, so a busy
year is a tall range and a quiet month is a valley. Everything here is static
for one render, which is what keeps the GIF small.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np

from pixelart import anchor_blend, bayer_map, lerp, ramp, rgb

SKY = {
    "dark": {
        "ash": ("#070b16", "#0e1526", "#1a2236", "#2b3448"),
        "ember": ("#0a0718", "#1c0c2e", "#3d1238", "#6e1c35"),
        "kindling": ("#0d0a24", "#2d1147", "#7a1f4f", "#d1472f"),
        "blaze": ("#150a30", "#4a1152", "#b3233f", "#f97316"),
        "inferno": ("#2a0612", "#7a0f1e", "#e0301a", "#ffb020"),
    },
    "light": {
        "ash": ("#9aa7b5", "#b8c2cc", "#d3d9df", "#e8eaec"),
        "ember": ("#8d8dc0", "#c29cbc", "#ecb6a0", "#f7d59c"),
        "kindling": ("#5fa9d6", "#d8aebd", "#f9b47c", "#fdd870"),
        "blaze": ("#3f9fd6", "#ee9a94", "#fb8340", "#fdc23e"),
        "inferno": ("#e6603a", "#f64c26", "#fd9a1c", "#ffe25a"),
    },
}
# Far range, near range, ground: shadow color and lit color.
LAND = {
    "dark": {"far": ("#231433", "#3b1d48"), "ridge": ("#1b0d24", "#6a1f3a"), "ground": ("#07050d", "#1a0e1e")},
    "light": {"far": ("#a9798f", "#c99a9c"), "ridge": ("#6d3440", "#b5583f"), "ground": ("#3a2230", "#6b3a38")},
}
ASH_LAND = {
    "dark": {"far": ("#141a26", "#232b3a"), "ridge": ("#0c1019", "#272e3c"), "ground": ("#05070c", "#11151d")},
    "light": {"far": ("#a3adb8", "#bac2ca"), "ridge": ("#6d7682", "#949ca7"), "ground": ("#3b414b", "#5a616c")},
}

WEEKS = 53
GRID_ROWS = 7
CELL_W, CELL_H, PITCH_X, PITCH_Y = 7, 2, 8, 3


@dataclass
class Scene:
    bg: np.ndarray  # background with no ash pile
    bg_pile: np.ndarray  # background with the ash pile
    ground_y: int
    ridge_top: np.ndarray  # y of the data ridge at each x
    cells: list  # (week, x, y, level) for each active calendar cell
    pile_x: int
    stars: np.ndarray  # (x, y) of stars that twinkle
    horizon: int


def _noise(width: int, seed: int, waves: int = 7, base: float = 0.012) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.arange(width)
    out = np.zeros(width)
    for i in range(waves):
        freq = base * 1.9**i
        out += np.sin(x * freq * 2 * math.pi + rng.uniform(0, 6.28)) / 1.65**i
    return out / 1.9


def _fill_land(frame, top, colors, ramp_h, dither, strata=None):
    """Fill below a skyline, lighter on the crest and dithered into shadow."""
    h, w = frame.shape[:2]
    shadow, lit = rgb(colors[0]), rgb(colors[1])
    ys = np.arange(h)[:, None]
    depth = (ys - top[None, :]) / ramp_h
    below = depth >= 0
    t = np.clip(1 - depth, 0, 1)
    if strata is not None:
        t = np.clip(t + strata, 0, 1)
    # Three flat tones with dithered borders, the way a 16-bit backdrop is painted.
    t = np.floor(t * 3 + dither * 0.9) / 3
    land = lerp(shadow, lit, t[..., None])
    frame[below] = land[below]


def _saguaro(frame, x, base, height, shadow, rim, sun_side):
    """A cactus with arms, rim-lit on the side facing the sun."""
    h, w = frame.shape[:2]

    def column(cx, y0, y1, width):
        for y in range(max(y0, 0), min(y1, h)):
            for dx in range(width):
                px = cx + dx
                if 0 <= px < w:
                    edge = dx == (width - 1 if sun_side > 0 else 0)
                    frame[y, px] = rim if edge else shadow

    width = 5 if height > 24 else 4
    column(x, base - height, base, width)
    arm_y = base - int(height * 0.55)
    # Left arm rises from a short elbow, right arm sits a little higher.
    column(x - 5, arm_y - 10, arm_y + 1, 3)
    frame[arm_y - 1:arm_y + 2, max(x - 5, 0):x] = shadow
    arm_y2 = base - int(height * 0.68)
    column(x + width + 2, arm_y2 - 9, arm_y2 + 1, 3)
    frame[arm_y2 - 1:arm_y2 + 2, x + width:min(x + width + 5, w)] = shadow
    if h > base - height - 1 >= 0:
        frame[base - height - 1, x + 1:x + width - 1] = shadow


def _ash_pile(frame, x, base, dither):
    colors = ramp(("#1a1d24", "#3a3f49", "#5a606b", "#7f858f", "#a7acb4", "#d3d6db"))
    h, w = frame.shape[:2]
    for y in range(base - 12, base + 3):
        for px in range(x - 34, x + 35):
            if not (0 <= px < w and 0 <= y < h):
                continue
            # A lumpy mound.
            dx = (px - x) / 34
            lump = 11 * (1 - dx * dx) + 1.5 * math.sin(px * 0.7) + math.sin(px * 1.9)
            if y >= base - lump:
                light = 0.75 - (y - (base - lump)) / 12 - dx * 0.3
                frame[y, px] = colors[int(np.clip(light * 5 + dither[y, px], 0, 5))]
    # The cracked egg, half buried.
    ex, ey, rx, ry = x, base - 15, 9, 12
    for y in range(ey - ry, base - 6):
        for px in range(ex - rx, ex + rx + 1):
            if not (0 <= px < w and 0 <= y < h):
                continue
            nx, ny = (px - ex) / rx, (y - ey) / ry
            taper = 1 - 0.18 * ny
            inside = (nx / taper) ** 2 + ny**2
            if inside <= 1:
                light = 0.95 - 0.5 * nx - 0.3 * ny - 0.15 * inside
                frame[y, px] = colors[int(np.clip(light * 5 + dither[y, px] - 0.5, 0, 5))]
            elif inside <= 1.28:
                frame[y, px] = colors[0]


# Crack pixels, relative to the egg center. The renderer lights these up.
CRACK = [(0, -9), (1, -8), (0, -7), (-1, -6), (0, -5), (1, -4), (2, -3), (1, -2), (0, -1), (-1, 0), (-2, 1), (-1, 2),
         (0, 3), (1, 4), (2, -6), (3, -5), (4, -5), (-2, -4), (-3, -3), (-4, -3)]


def weekly_totals(days: dict[dt.date, int], today: dt.date) -> tuple[np.ndarray, dt.date]:
    last_sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    first = last_sunday - dt.timedelta(weeks=WEEKS - 1)
    totals = np.zeros(WEEKS)
    for w in range(WEEKS):
        totals[w] = sum(days.get(first + dt.timedelta(days=w * 7 + d), 0) for d in range(7))
    return totals, first


def build_scene(h: float, days, today, theme: str, width: int, height: int, show_grid: bool = True) -> Scene:
    lit = h > 0
    dark_theme = theme == "dark"
    table = dict(SKY[theme])
    colors = ramp(table["ash"]) if not lit else anchor_blend(h, table)
    land = (LAND if lit else ASH_LAND)[theme]
    dither = bayer_map(height, width)
    frame = np.zeros((height, width, 3))

    ground_y = height - 31
    horizon = ground_y - 8

    # Sky: flat bands with dithered borders.
    ys = np.arange(height)[:, None] / max(horizon, 1)
    bands = 16
    t = np.clip(np.floor(ys.repeat(width, axis=1) * bands + dither) / bands, 0, 1) * (len(colors) - 1)
    lo = np.clip(t.astype(int), 0, len(colors) - 2)
    frame[:] = lerp(colors[lo], colors[lo + 1], (t - lo)[..., None])

    rng = np.random.default_rng(11)
    # Stars thin out as the sky catches fire.
    stars = np.empty((0, 2), dtype=int)
    if dark_theme:
        count = int(lerp(120, 12, min(1.0, h / 0.8)))
        sx = rng.integers(0, width, count)
        sy = (rng.random(count) ** 1.6 * horizon * 0.62).astype(int)
        shade = rng.choice([0.45, 0.65, 1.0], count, p=[0.5, 0.35, 0.15])
        frame[sy, sx] = np.clip(frame[sy, sx] + shade[:, None] * np.array([0.8, 0.82, 0.9]), 0, 1)
        stars = np.stack([sx, sy], axis=1)[shade > 0.6]

    # Sun, or a cold moon once the phoenix is ash.
    sun_x = int(width * 0.74)
    yy, xx = np.mgrid[0:height, 0:width]
    if lit:
        radius = lerp(13, 36, h)
        sun_y = horizon - 26 - radius * 0.35
        dist = np.hypot(xx - sun_x, yy - sun_y)
        halo = np.clip(1 - dist / (radius * 2.6), 0, 1) ** 1.7
        halo = np.floor(halo * 6 + dither) / 6
        hot = rgb("#ffd34d") if h > 0.3 else rgb("#d9482f")
        frame[:] = np.where(
            (yy < horizon + 4)[..., None], np.clip(frame + halo[..., None] * hot * lerp(0.25, 0.55, h), 0, 1), frame
        )
        disc = dist <= radius
        grad = np.clip((yy - (sun_y - radius)) / (2 * radius), 0, 1)
        top, bottom = (rgb("#fff6b0"), rgb("#ff3f6e")) if h > 0.3 else (rgb("#ff7a3d"), rgb("#7a1230"))
        sun = lerp(top, bottom, np.floor(grad * 9)[..., None] / 9)
        # Slatted lower half, the classic sunset poster.
        rel = (yy - sun_y) / radius
        slat = (rel > 0.02) & (((yy - int(sun_y)) % 7) < np.clip(rel * 6, 0, 5))
        frame[disc & ~slat] = sun[disc & ~slat]
    else:
        mx, my, radius = sun_x, 30, 13
        dist = np.hypot(xx - mx, yy - my)
        halo = np.clip(1 - dist / 34, 0, 1) ** 2
        frame[:] = np.clip(frame + (np.floor(halo * 4 + dither) / 4)[..., None] * 0.12, 0, 1)
        moon = rgb("#d8dde6") if dark_theme else rgb("#f7f8fa")
        shade = rgb("#a4acba") if dark_theme else rgb("#ccd2d9")
        disc = dist <= radius
        frame[disc] = moon
        frame[disc & (np.hypot(xx - mx - 4, yy - my + 3) < 3)] = shade
        frame[disc & (np.hypot(xx - mx + 5, yy - my - 2) < 4)] = shade
        frame[disc & (np.hypot(xx - mx + 1, yy - my + 6) < 2)] = shade

    # Long streaks of cloud, lit from below.
    cloud_lit = lerp(colors[-1], rgb("#ffe9a8"), 0.35 if lit else 0.1)
    cloud_dark = lerp(colors[1], colors[2], 0.5)
    for i in range(7):
        cy = int(rng.uniform(horizon * 0.2, horizon * 0.72))
        cx = int(rng.uniform(0, width))
        length = int(rng.uniform(40, 120))
        for layer in range(3):
            y = cy + layer
            half = int(length * (1 - layer * 0.28)) // 2
            offset = int(rng.integers(-8, 8))
            x0, x1 = max(cx - half + offset, 0), min(cx + half + offset, width)
            if x0 < x1 and 0 <= y < height:
                row = frame[y, x0:x1]
                tone = cloud_lit if layer == 2 else cloud_dark
                row[:] = lerp(row, tone, 0.45 if layer == 0 else 0.6)

    # Far range with Camelback Mountain: the head on the left, the long hump behind it.
    gx = np.arange(width)
    far = (horizon - 24) + _noise(width, 3, 6, 0.01) * 7
    camel_x = width * 0.17
    far -= 16 * np.exp(-(((gx - camel_x) / 12) ** 2)) + 24 * np.exp(-(((gx - camel_x - 44) / 30) ** 2))
    _fill_land(frame, far, land["far"], 40, dither)

    # The data ridge: one peak per week of the contribution calendar.
    totals, first = weekly_totals(days, today)
    level = np.log1p(totals) / max(np.log1p(totals.max()), 1e-6)
    level = np.convolve(np.pad(level, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")
    positions = (np.arange(WEEKS) + 0.5) / WEEKS * width
    profile = np.interp(gx, positions, level)
    ridge = (horizon + 3) - (3 + 30 * profile) - np.abs(_noise(width, 5, 7, 0.03)) * 3.5 + _noise(width, 8, 5, 0.09) * 1.4
    ridge_top = np.floor(ridge).astype(int)
    strata = (_noise(width, 9, 4, 0.02)[None, :] + np.sin(np.arange(height)[:, None] * 1.25)) * 0.09
    _fill_land(frame, ridge, land["ridge"], 26, dither, strata)

    # Foreground hills meet the ground, which holds the calendar.
    fore = ground_y + _noise(width, 13, 5, 0.012) * 2.4
    _fill_land(frame, fore, land["ground"], 9, dither)

    # Calendar cells, faintly banked until the phoenix passes.
    cells = []
    x0 = (width - (WEEKS * PITCH_X - (PITCH_X - CELL_W))) // 2
    y0 = ground_y + 8
    peak = max(max(days.values(), default=1), 1)
    base_cell = lerp(rgb(land["ground"][0]), rgb(land["ground"][1]), 0.6 if dark_theme else 0.9)
    warm = rgb("#c9360c") if lit else rgb("#6e7681")
    if show_grid:
        for w in range(WEEKS):
            for d in range(GRID_ROWS):
                day = first + dt.timedelta(days=w * 7 + d)
                if day > today:
                    continue
                x, y = x0 + w * PITCH_X, y0 + d * PITCH_Y
                count = days.get(day, 0)
                color = base_cell
                if count > 0:
                    lvl = math.log1p(count) / math.log1p(peak)
                    color = lerp(base_cell, warm, 0.35 + lvl * 0.5)
                    cells.append((w, x, y, lvl))
                frame[y:y + CELL_H, x:x + CELL_W] = color

    # Saguaros and scrub, rim-lit from the sun.
    sil = lerp(rgb(land["ground"][0]), np.zeros(3), 0.2)
    rim = lerp(sil, lerp(colors[-1], rgb("#ffe08a"), 0.4), 0.55) if lit else rgb(land["ground"][1])
    for cx, cheight in ((22, 34), (62, 20), (150, 15), (278, 18), (372, 28), (414, 38)):
        cx = int(cx / 440 * width)
        _saguaro(frame, cx, int(fore[min(cx, width - 1)]) + 3, cheight, sil, rim, 1 if cx < sun_x else -1)
    for sx in rng.integers(0, width, 34):
        sy = int(fore[sx]) + 1
        spread = int(rng.integers(1, 4))
        frame[sy - spread:sy + 1, sx] = sil
        frame[sy, max(sx - spread, 0):sx + spread] = sil

    frame = np.clip(frame, 0, 1)
    pile_x = width // 2
    with_pile = frame.copy()
    _ash_pile(with_pile, pile_x, ground_y + 3, dither)
    return Scene(frame, with_pile, ground_y, ridge_top, cells, pile_x, stars, horizon)
