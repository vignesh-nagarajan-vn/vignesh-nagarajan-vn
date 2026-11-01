"""Render the phoenix as a looping pixel-art GIF.

Frames are drawn at half size and doubled, so every pixel is a crisp 2x2 block.
Anything that moves is a closed-form function of time wrapped to the loop
length, so the last frame runs straight into the first with no seam.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image

import bird
import scene as scene_mod
from heat import Metrics, stage_for
from pixelart import apply_ramp, bayer_map, bird_ramps, lerp, ramp, rgb, stamp, text_mask

FRAME_SECONDS = 0.06
SCALE = 2
RISE_SECONDS = 4.0
ASH_SECONDS = 6.0

SMOKE_RAMP = ramp(("#2a2e36", "#4a4f59", "#6d727c", "#92969f", "#b5b8bf"))
THEME_TEXT = {"dark": ("#f6f1e7", "#0a0710"), "light": ("#fffdf6", "#1f1420")}


@dataclass
class Timeline:
    """Which path the bird is on at a moment in the loop."""

    flight: bird.Path
    rise: bird.Path | None
    total: float

    @property
    def offset(self) -> float:
        return RISE_SECONDS if self.rise else 0.0

    def segment(self, t: float):
        """Return (position function, local time), or None while the bird is unborn."""
        if self.rise:
            if t < 1.4:
                return None
            if t < RISE_SECONDS:
                return self.rise.pos, t - 1.4, self.rise.angle(t - 1.4)
            local = t - RISE_SECONDS
            return self.flight.pos, local, self.flight.angle(local)
        return self.flight.pos, t, self.flight.angle(t)


def _splat(buffer: np.ndarray, xs: np.ndarray, ys: np.ndarray, values: np.ndarray, radius: int) -> None:
    """Add particles to a value buffer as small discs."""
    h, w = buffer.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius + 0.5:
                continue
            falloff = 1 - math.hypot(dx, dy) / (radius + 1)
            px, py = xs + dx, ys + dy
            keep = (px >= 0) & (px < w) & (py >= 0) & (py < h)
            np.add.at(buffer, (py[keep], px[keep]), values[keep] * falloff)


class Flames:
    """Particles emitted along the flight. Age is wrapped to the loop length."""

    def __init__(self, timeline: Timeline, look: bird.Look, width: int, seed: int = 7):
        rng = np.random.default_rng(seed)
        self.total = timeline.total
        starts, xs, ys, vxs, vys, lifes, sizes, kinds = [], [], [], [], [], [], [], []
        t_start = 1.4 if timeline.rise else 0.0
        count = int(look.flame_rate * (timeline.total - t_start))
        times = rng.uniform(t_start, timeline.total, count)
        for te in times:
            seg = timeline.segment(float(te))
            if seg is None:
                continue
            pos_fn, local, angle = seg
            at = pos_fn(local)
            if not (-80 < at[0] < width + 80):
                continue
            pose = bird.Pose(at, angle, look.size)
            phase = 2 * math.pi * te / look.flap
            roll = rng.random()
            if roll < 0.5:
                px, py = pose.point(-24 + rng.normal(0, 4), 3 + rng.normal(0, 4))
            elif roll < 0.82:
                side = 1 if rng.random() < 0.6 else -1
                bones = bird.wing_skeleton(phase, look, side)
                bone = bones[int(rng.integers(3, 7))]
                px, py = pose.point(bone[0] - rng.uniform(0, 28 * look.span), bone[1] + rng.normal(0, 3))
            else:
                px, py = pose.point(rng.uniform(-20, 24), rng.normal(-2, 7))
            heading = np.array([math.cos(angle), math.sin(angle)])
            speed = rng.uniform(6, 24)
            kinds.append(0 if rng.random() < 0.8 else 1)
            lifes.append(look.flame_life * rng.uniform(0.45, 1.15) * (2.1 if kinds[-1] else 1.0))
            starts.append(te)
            xs.append(px)
            ys.append(py)
            vxs.append(-heading[0] * speed + rng.normal(0, 6))
            vys.append(-heading[1] * speed + rng.normal(-10, 7))
            sizes.append(rng.integers(1, 4))
        self.starts = np.array(starts)
        self.xs, self.ys = np.array(xs), np.array(ys)
        self.vxs, self.vys = np.array(vxs), np.array(vys)
        self.lifes = np.array(lifes)
        self.sizes = np.array(sizes, dtype=int)
        self.kinds = np.array(kinds, dtype=int)

    def draw(self, t: float, fire: np.ndarray) -> None:
        if not len(self.starts):
            return
        age = (t - self.starts) % self.total
        alive = age < self.lifes
        if not alive.any():
            return
        a = age[alive]
        life = self.lifes[alive]
        x = (self.xs[alive] + self.vxs[alive] * a).astype(int)
        y = (self.ys[alive] + self.vys[alive] * a - 7 * a * a).astype(int)
        value = (1 - a / life) ** 0.8
        sizes = self.sizes[alive]
        kinds = self.kinds[alive]
        flame = kinds == 0
        for size in (1, 2, 3):
            mask = flame & (sizes == size)
            # Flames shrink as they cool.
            if mask.any():
                _splat(fire, x[mask], y[mask], value[mask] * 0.55, size)
        spark = ~flame
        if spark.any():
            _splat(fire, x[spark], y[spark], value[spark] * 1.2, 0)


def _ambient_rain(look: bird.Look, width: int, height: int, total: float, seed: int = 21):
    rng = np.random.default_rng(seed)
    n = look.rain
    return {
        "x": rng.uniform(0, width, n),
        "phase": rng.random(n),
        "speed": rng.integers(1, 4, n) * height / total * rng.choice([1, 2], n),
        "sway": rng.uniform(0, 6.28, n),
    }


def _rebirth_burst(scene, seed: int = 31):
    rng = np.random.default_rng(seed)
    n = 520
    return {
        "start": rng.uniform(1.05, 2.6, n),
        "x": scene.pile_x + rng.normal(0, 12, n),
        "y": scene.ground_y - rng.uniform(0, 14, n),
        "vx": rng.normal(0, 26, n),
        "vy": -rng.uniform(40, 150, n),
        "life": rng.uniform(0.5, 1.5, n),
        "size": rng.integers(1, 4, n),
    }


def _smoke(pile_x: int, base: int, seed: int = 41, n: int = 60, total: float = ASH_SECONDS):
    rng = np.random.default_rng(seed)
    return {
        "phase": rng.random(n) * total,
        "x": pile_x + rng.normal(0, 4, n),
        "drift": rng.normal(0, 3, n),
        "speed": rng.uniform(7, 15, n),
        "wave": rng.uniform(0, 6.28, n),
        "life": rng.uniform(3, 5.8, n),
        "base": base,
    }


def _caption(stage: str, m: Metrics, reborn: bool) -> tuple[str, str]:
    # Ash carries no numbers, so a quiet stretch doesn't advertise "0 commits".
    if stage == "ash":
        return "ASH", ""
    title = f"REBORN {stage.upper()}" if reborn else stage.upper()
    parts = []
    if m.current_streak:
        parts.append(f"{m.current_streak}-DAY STREAK")
    noun = "CONTRIBUTION" if m.recent14 == 1 else "CONTRIBUTIONS"
    parts.append(f"{m.recent14} {noun} IN 2 WEEKS")
    return title, " - ".join(parts)


def _draw_hud(frame, h: float, title: str, detail: str, theme: str, tagline: str, ramps) -> None:
    fg, shadow = (rgb(c) for c in THEME_TEXT[theme])
    x, y = 6, 6
    big = text_mask(title, 2)
    stamp(frame, big, x + 1, y + 1, shadow)
    stamp(frame, big, x, y, fg)
    bar_y = y + 12
    bar_w = 62
    frame[bar_y:bar_y + 4, x:x + bar_w + 2] = shadow
    fill = round(bar_w * min(h, 1.0))
    if fill:
        steps = np.clip((np.arange(fill) / bar_w * 7).astype(int), 0, 7)
        frame[bar_y + 1:bar_y + 3, x + 1:x + 1 + fill] = ramps[0][steps]
    if detail:
        small = text_mask(detail)
        stamp(frame, small, x + 1, bar_y + 7, shadow)
        stamp(frame, small, x, bar_y + 6, fg)
    if tagline:
        small = text_mask(tagline)
        tx = frame.shape[1] - small.shape[1] - 6
        stamp(frame, small, tx + 1, 7, shadow)
        stamp(frame, small, tx, 6, fg)


def render_frames(h, m, days, today, theme="dark", reborn=False, config=None) -> list[np.ndarray]:
    """Return the loop as a list of RGB arrays with values in 0..1, at half size."""
    config = config or {}
    width = config.get("width", 880) // SCALE
    height = config.get("height", 300) // SCALE
    show_grid = config.get("showGrid", True)
    show_caption = config.get("showCaption", True)
    tagline = config.get("tagline", "")
    stage = stage_for(h)
    lit = stage != "ash"
    scene = scene_mod.build_scene(h, days, today, theme, width, height, show_grid)
    dither = bayer_map(height, width)
    ramps = bird_ramps(h, config.get("colors"))
    title, detail = _caption(stage, m, reborn)
    frames = []

    if not lit:
        total = ASH_SECONDS
        count = round(total / FRAME_SECONDS)
        smoke = _smoke(scene.pile_x, scene.ground_y - 22)
        ex, ey = scene.pile_x, scene.ground_y + 3 - 15
        for i in range(count):
            t = i * FRAME_SECONDS
            frame = scene.bg_pile.copy()
            _draw_smoke(frame, smoke, t, total, dither)
            pulse = 0.5 + 0.5 * math.sin(2 * math.pi * t / total * 2)
            _draw_crack(frame, ex, ey, pulse, height, width)
            _twinkle(frame, scene, t, total)
            if show_caption:
                _draw_hud(frame, 0.0, title, detail, theme, tagline, ramps)
            frames.append(frame)
        return frames

    look = bird.look_for(h)
    flight = bird.flight_path(look, width, scene.horizon)
    rise = bird.rise_path(scene.pile_x, scene.ground_y - 6, width, RISE_SECONDS - 1.4) if reborn else None
    timeline = Timeline(flight, rise, round(look.duration + (RISE_SECONDS if reborn else 0), 2))
    count = round(timeline.total / FRAME_SECONDS)
    timeline.total = count * FRAME_SECONDS
    flames = Flames(timeline, look, width)
    rain = _ambient_rain(look, width, height, timeline.total)
    burst = _rebirth_burst(scene) if reborn else None
    smoke = _smoke(scene.pile_x, scene.ground_y - 22, total=timeline.total) if reborn else None
    ignite_times = _crossings(flight, width, timeline.offset)
    glow_color = ramps[0][5]
    fire_ramp = ramps[0][2:]
    ex, ey = scene.pile_x, scene.ground_y + 3 - 15

    for i in range(count):
        t = i * FRAME_SECONDS
        # The pile is gone by the time the flames die down.
        frame = (scene.bg_pile if reborn and t < 2.6 else scene.bg).copy()
        _twinkle(frame, scene, t, timeline.total)
        _ignite(frame, scene, ignite_times, t, timeline.total, ramps[0], show_grid)

        if reborn and t < 2.6:
            glow = min(1.0, t / 1.1)
            _draw_crack(frame, ex, ey, glow, height, width)
            _add_glow(frame, np.array([ex, ey]), 34 + 60 * glow, glow_color, 0.5 * glow, dither)
            if t < 1.1:
                _draw_smoke(frame, smoke, t, timeline.total, dither)

        seg = timeline.segment(t)
        position = None
        if seg is not None:
            pos_fn, local, angle = seg
            position = pos_fn(local)
            if -100 < position[0] < width + 100:
                _add_glow(frame, position, look.glow_r, glow_color, look.glow, dither)

        fire = np.zeros((height, width))
        flames.draw(t, fire)
        if burst is not None:
            _draw_burst(fire, burst, t)
        back = fire.copy()
        _draw_rain(frame, rain, t, timeline.total, height, fire_ramp)
        _composite_fire(frame, back * 0.75, fire_ramp, dither)

        if seg is not None and -135 < position[0] < width + 135:
            phase = 2 * math.pi * t / look.flap
            if rise is not None and t < RISE_SECONDS:
                grow = min(1.0, 0.3 + (t - 1.4) / 1.3 * 0.7)
                look_now = _scaled(look, grow)
            else:
                look_now = look
            _draw_sprite(frame, pos_fn, angle, local, phase, look_now, h, ramps, dither)
            # A thin layer of the same fire in front, so flame licks over the bird.
            _composite_fire(frame, np.where(dither > 0.62, fire * 0.7, 0), fire_ramp, dither)

        if show_caption:
            _draw_hud(frame, h, title, detail, theme, tagline, ramps)
        frames.append(frame)
    if not reborn:
        # Open with the bird already in view, which is also what a still thumbnail shows.
        start = round(count * 0.36)
        frames = frames[start:] + frames[:start]
    return frames


def _scaled(look: bird.Look, grow: float) -> bird.Look:
    return replace(look, size=look.size * grow, tail=look.tail * grow)


def _draw_sprite(frame, pos_fn, angle, local, phase, look, h, ramps, dither) -> None:
    height, width = frame.shape[:2]
    value_image = Image.new("L", (width, height), 0)
    part_image = Image.new("L", (width, height), 0)
    cv = bird.Canvas(value_image, part_image)
    bird.draw_bird(cv, pos_fn, angle, local, phase, look, h)
    value = np.asarray(value_image, dtype=float) / 255
    part = np.asarray(part_image)
    mask = value > 0
    if not mask.any():
        return
    # A bold dark outline, the thing that makes a sprite read at a glance.
    edge = (
        np.roll(mask, 1, 0) | np.roll(mask, -1, 0) | np.roll(mask, 1, 1) | np.roll(mask, -1, 1)
    ) & ~mask
    frame[edge] = ramps[0][0]
    ys, xs = np.nonzero(mask)
    v = value[ys, xs]
    d = dither[ys, xs]
    p = np.clip(part[ys, xs], 0, 3)
    index = np.clip((v * 7 + d).astype(int), 0, 7)
    frame[ys, xs] = ramps[p, index]


def _crossings(flight: bird.Path, width: int, offset: float) -> np.ndarray:
    """When the bird first reaches each x position, in loop time."""
    x_at = np.minimum.accumulate(flight.xs[::-1])[::-1]
    times = np.interp(np.arange(width), x_at, flight.arc) / flight.speed
    return times + offset


def _ignite(frame, scene, times, t, total, fire, show_grid) -> None:
    """Light the ridge line and the calendar cells behind the bird, then let them fade."""
    age = (t - times) % total
    level = np.exp(-age / 1.15)
    cols = np.nonzero(level > 0.06)[0]
    height = frame.shape[0]
    for x in cols:
        top = scene.ridge_top[x]
        if 0 <= top < height:
            f = level[x]
            idx = int(min(7, 3 + f * 5))
            frame[top, x] = lerp(frame[top, x], fire[idx], min(1.0, f * 1.5))
            if top + 1 < height:
                frame[top + 1, x] = lerp(frame[top + 1, x], fire[max(idx - 2, 0)], min(1.0, f))
    if not show_grid:
        return
    for week, x, y, lvl in scene.cells:
        cx = min(x + 3, frame.shape[1] - 1)
        f = level[cx]
        if f > 0.06:
            idx = int(np.clip(2 + (f * 3 + lvl * 3), 0, 7))
            frame[y:y + scene_mod.CELL_H, x:x + scene_mod.CELL_W] = lerp(
                frame[y:y + scene_mod.CELL_H, x:x + scene_mod.CELL_W], fire[idx], min(1.0, f * 1.4)
            )


def _add_glow(frame, position, radius, color, strength, dither) -> None:
    height, width = frame.shape[:2]
    r = int(radius)
    x0, x1 = max(int(position[0]) - r, 0), min(int(position[0]) + r + 1, width)
    y0, y1 = max(int(position[1]) - r, 0), min(int(position[1]) + r + 1, height)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dist = np.hypot(xx - position[0], yy - position[1]) / max(radius, 1)
    level = np.clip(1 - dist, 0, 1) ** 1.8
    # Few steps, so the halo holds still between frames and the GIF stays small.
    level = np.floor(level * 5 + dither[y0:y1, x0:x1]) / 5
    frame[y0:y1, x0:x1] = np.clip(frame[y0:y1, x0:x1] + level[..., None] * color * strength, 0, 1)


def _composite_fire(frame, fire, fire_ramp, dither) -> None:
    mask = fire + dither * 0.16 > 0.2
    if not mask.any():
        return
    color = apply_ramp(np.clip(fire * 1.05, 0, 1), fire_ramp, dither)
    frame[mask] = color[mask]


def _draw_burst(fire, burst, t) -> None:
    age = t - burst["start"]
    alive = (age >= 0) & (age < burst["life"])
    if not alive.any():
        return
    a = age[alive]
    x = (burst["x"][alive] + burst["vx"][alive] * a).astype(int)
    y = (burst["y"][alive] + burst["vy"][alive] * a + 34 * a * a).astype(int)
    value = 1 - a / burst["life"][alive]
    sizes = burst["size"][alive]
    for size in (1, 2, 3):
        mask = sizes == size
        if mask.any():
            _splat(fire, x[mask], y[mask], value[mask] * 0.8, size)


def _draw_rain(frame, rain, t, total, height, fire_ramp) -> None:
    if not len(rain["x"]):
        return
    # Whole laps per loop, so the fall is seamless.
    laps = np.round(rain["speed"] * total / (height + 8))
    laps = np.maximum(laps, 1)
    y = ((rain["phase"] + laps * t / total) % 1.0) * (height + 8) - 4
    x = rain["x"] + 3 * np.sin(rain["sway"] + 2 * math.pi * t / total * 3)
    fade = np.clip(1 - y / height, 0.2, 1)
    xi, yi = x.astype(int) % frame.shape[1], y.astype(int)
    keep = (yi >= 0) & (yi < height)
    idx = np.clip((fade[keep] * (len(fire_ramp) - 1)).astype(int), 0, len(fire_ramp) - 1)
    frame[yi[keep], xi[keep]] = fire_ramp[idx]


def _draw_smoke(frame, smoke, t, total, dither) -> None:
    age = (t - smoke["phase"]) % total
    alive = age < smoke["life"]
    if not alive.any():
        return
    a = age[alive]
    life = smoke["life"][alive]
    x = (smoke["x"][alive] + smoke["drift"][alive] * a + 2.5 * np.sin(smoke["wave"][alive] + a * 1.6)).astype(int)
    y = (smoke["base"] - smoke["speed"][alive] * a).astype(int)
    value = np.clip(1 - a / life, 0, 1)
    height, width = frame.shape[:2]
    for k in range(len(x)):
        r = 1 + int(a[k] * 0.9)
        y0, y1 = max(y[k] - r, 0), min(y[k] + r + 1, height)
        x0, x1 = max(x[k] - r, 0), min(x[k] + r + 1, width)
        if y0 >= y1 or x0 >= x1:
            continue
        keep = dither[y0:y1, x0:x1] < value[k] * 0.62
        tone = SMOKE_RAMP[min(int(value[k] * 4 + 1), 4)]
        frame[y0:y1, x0:x1][keep] = tone


def _draw_crack(frame, ex, ey, level, height, width) -> None:
    colors = ramp(("#5a1a10", "#a5300e", "#f0701a", "#fdb22a", "#fff0a0"))
    color = colors[min(int(level * 4.99), 4)]
    for dx, dy in scene_mod.CRACK:
        y, x = ey + dy, ex + dx
        if 0 <= y < height and 0 <= x < width:
            frame[y, x] = color


def _twinkle(frame, scene, t, total) -> None:
    for i, (x, y) in enumerate(scene.stars):
        wave = math.sin(2 * math.pi * ((i % 5) + 1) * t / total + i * 1.7)
        if wave > 0.55:
            frame[y, x] = (1.0, 0.98, 0.9)
        elif wave < -0.75:
            frame[y, x] = np.clip(frame[y, x] * 0.5, 0, 1)


def _build_palette(frames: list[np.ndarray]) -> np.ndarray:
    """One global palette: adapted to these frames, with the hot colors kept."""
    sample = np.concatenate([f.reshape(-1, 3) for f in frames[:: max(len(frames) // 14, 1)]])
    side = int(math.sqrt(len(sample))) or 1
    image = Image.fromarray(np.uint8(sample[: side * side].reshape(side, side, 3) * 255))
    quant = image.quantize(colors=232, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = np.array(quant.getpalette()[: 232 * 3], dtype=float).reshape(-1, 3) / 255
    return palette


def _encode(frames: list[np.ndarray], extra_colors: np.ndarray) -> bytes:
    palette = np.concatenate([_build_palette(frames), extra_colors])[:255]
    # A coarse lookup from color to palette index keeps mapping fast and stable.
    bits = 5
    grid = (np.indices((1 << bits,) * 3).reshape(3, -1).T + 0.5) / (1 << bits)
    lut = np.empty(len(grid), dtype=np.uint8)
    for start in range(0, len(grid), 4096):
        chunk = grid[start:start + 4096]
        lut[start:start + 4096] = np.argmin(((chunk[:, None] - palette[None]) ** 2).sum(-1), axis=1)

    flat = (np.clip(palette, 0, 1) * 255).astype(np.uint8).ravel().tolist()
    flat += [0, 0, 0] * (256 - len(palette))

    def to_image(frame):
        q = np.clip((frame * ((1 << bits) - 1e-6)).astype(int), 0, (1 << bits) - 1)
        index = lut[(q[..., 0] << (2 * bits)) | (q[..., 1] << bits) | q[..., 2]]
        index = index.repeat(SCALE, axis=0).repeat(SCALE, axis=1)
        image = Image.fromarray(index, mode="P")
        image.putpalette(flat)
        return image

    images = [to_image(f) for f in frames]
    out = io.BytesIO()
    images[0].save(
        out,
        "GIF",
        save_all=True,
        append_images=images[1:],
        duration=round(FRAME_SECONDS * 1000),
        loop=0,
        disposal=1,
        optimize=True,
    )
    return out.getvalue()


def render(h, m, days, today, theme="dark", reborn=False, config=None) -> bytes:
    frames = render_frames(h, m, days, today, theme, reborn, config)
    ramps = bird_ramps(h, (config or {}).get("colors"))
    return _encode(frames, ramps.reshape(-1, 3))
