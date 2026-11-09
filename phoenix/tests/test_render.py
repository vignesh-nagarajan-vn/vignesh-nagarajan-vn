import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bird  # noqa: E402
import generate  # noqa: E402
import heat  # noqa: E402
import pixelart  # noqa: E402
import render  # noqa: E402
import scene  # noqa: E402

with open(os.path.join(ROOT, "phoenix.config.json")) as fh:
    CONFIG = json.load(fh)


def sample(name, config=CONFIG):
    days, end, prev = generate.load_sample(name)
    m = heat.compute_metrics(days, end)
    h = heat.compute_heat(m, config["heat"])
    _, reborn = heat.next_state(prev, heat.stage_for(h), end)
    return h, m, days, end, reborn


def frames_for(name, theme="dark", config=CONFIG):
    h, m, days, end, reborn = sample(name, config)
    return render.render_frames(h, m, days, end, theme, reborn, config)


_cache = {}


def cached(name, theme="dark"):
    if (name, theme) not in _cache:
        _cache[(name, theme)] = frames_for(name, theme)
    return _cache[(name, theme)]


def changed(a, b):
    return np.abs(a - b).sum(axis=2) > 0.02


class MotionTests(unittest.TestCase):
    """The phoenix has to visibly travel, not just shimmer in place."""

    def bird_x(self, frames, start, end):
        """Horizontal center of the biggest change between frames, per frame."""
        out = []
        for a, b in zip(frames[start:end], frames[start + 1:end + 1]):
            xs = np.nonzero(changed(a, b)[:110].any(axis=0))[0]
            if len(xs):
                out.append(np.median(xs))
        return out

    def test_every_lit_stage_crosses_the_frame(self):
        for name in ("ember", "blaze", "inferno"):
            frames = cached(name)
            n = len(frames)
            xs = self.bird_x(frames, 0, n - 1)
            self.assertGreater(max(xs) - min(xs), 200, name)

    def test_wings_change_shape_between_frames(self):
        frames = cached("blaze")
        self.assertGreater(changed(frames[5], frames[8]).sum(), 800)

    def test_loop_opens_with_the_bird_in_view(self):
        for name in ("ember", "blaze", "inferno"):
            frames = cached(name)
            self.assertGreater(changed(frames[0], frames[1])[:110].sum(), 150, name)

    def test_ash_stays_put(self):
        frames = cached("ash")
        moved = np.zeros(frames[0].shape[:2], dtype=bool)
        for a, b in zip(frames, frames[1:]):
            moved |= changed(a, b)
        # Smoke over the pile and a few stars, nothing crossing the sky.
        columns = np.nonzero(moved[72:110].any(axis=0))[0]
        self.assertLess(columns.max() - columns.min(), 90)

    def test_rebirth_runs_longer_and_starts_with_no_bird(self):
        frames = cached("rebirth")
        self.assertGreater(len(frames), len(cached("kindling")))
        h, m, days, end, reborn = sample("rebirth")
        self.assertTrue(reborn)
        look = bird.look_for(h)
        flight = bird.flight_path(look, 440, 111)
        timeline = render.Timeline(flight, bird.rise_path(220, 113, 440, 2.6), 13.0)
        self.assertIsNone(timeline.segment(0.5))
        self.assertIsNotNone(timeline.segment(2.0))

    def test_loop_has_no_seam(self):
        for name in ("blaze", "inferno", "rebirth"):
            frames = cached(name)
            seam = changed(frames[-1], frames[0]).sum()
            typical = np.median([changed(a, b).sum() for a, b in zip(frames[10:], frames[11:40])])
            self.assertLessEqual(seam, typical * 2.5 + 400, name)


class InterpolationTests(unittest.TestCase):
    def test_looks_change_continuously_inside_a_stage(self):
        low, high = bird.look_for(0.47), bird.look_for(0.73)
        self.assertGreater(low.flap, high.flap)
        self.assertLess(low.tail, high.tail)
        self.assertLess(low.flame_rate, high.flame_rate)
        self.assertLess(low.amplitude, high.amplitude)
        self.assertLess(low.glow, high.glow)

    def test_no_color_jump_at_a_stage_boundary(self):
        below, above = pixelart.bird_ramps(0.4499), pixelart.bird_ramps(0.4501)
        self.assertLess(np.abs(below - above).max(), 0.01)

    def test_only_the_hottest_birds_loop(self):
        self.assertEqual(bird.look_for(0.6).loop, 0)
        self.assertGreater(bird.look_for(0.95).loop, 0)

    def test_flight_starts_and_ends_outside_the_frame(self):
        for h in (0.05, 0.5, 1.0):
            path = bird.flight_path(bird.look_for(h), 440, 111)
            self.assertLess(path.xs[0], -100)
            self.assertGreater(path.xs[-1], 540)


class SceneTests(unittest.TestCase):
    def test_ridge_follows_the_data(self):
        import datetime as dt

        today = dt.date(2026, 11, 1)
        # Activity only in the most recent months: the ridge climbs on the right.
        days = {today - dt.timedelta(days=i): 20 for i in range(80)}
        s = scene.build_scene(0.6, days, today, "dark", 440, 150)
        self.assertLess(s.ridge_top[380:430].mean(), s.ridge_top[20:200].mean() - 10)

    def test_light_and_dark_differ(self):
        self.assertGreater(np.abs(cached("blaze")[0] - cached("blaze", "light")[0]).mean(), 0.1)


class GifTests(unittest.TestCase):
    def encoded(self, name, theme="dark", config=CONFIG):
        h, m, days, end, reborn = sample(name, config)
        return render.render(h, m, days, end, theme, reborn, config)

    def test_gif_round_trip(self):
        data = self.encoded("blaze")
        self.assertLess(len(data), 4_000_000)
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.format, "GIF")
            self.assertEqual(im.size, (CONFIG["width"], CONFIG["height"]))
            self.assertGreater(im.n_frames, 100)
            self.assertEqual(im.info.get("loop"), 0)
            self.assertEqual(im.info.get("duration"), round(render.FRAME_SECONDS * 1000))
            # Decode a late frame: the encoder's delta frames must rebuild correctly.
            im.seek(im.n_frames // 2)
            decoded = np.asarray(im.convert("RGB"), dtype=float) / 255
        want = cached("blaze")[len(cached("blaze")) // 2].repeat(2, 0).repeat(2, 1)
        self.assertLess(np.abs(decoded - want).mean(), 0.03)

    def test_output_is_deterministic(self):
        a = cached("ash")
        b = frames_for("ash")
        self.assertTrue(all(np.array_equal(x, y) for x, y in zip(a, b)))

    def test_ash_caption_shows_no_numbers(self):
        h, m, *_ = sample("ash")
        self.assertEqual(render._caption("ash", m, False), ("ASH", ""))

    def test_singular_caption(self):
        m = heat.Metrics(1, 1, 0, 8, 0.01, 0)
        self.assertIn("1 CONTRIBUTION IN", render._caption("ember", m, False)[1])

    def test_grid_and_caption_toggles(self):
        h, m, days, end, _ = sample("ash")
        plain = render.render_frames(h, m, days, end, "dark", False, {**CONFIG, "showGrid": False, "showCaption": False})
        self.assertFalse(np.array_equal(plain[0], cached("ash")[0]))
        s = scene.build_scene(0.6, days, end, "dark", 440, 150, show_grid=False)
        self.assertEqual(s.cells, [])

    def test_color_override(self):
        ramp = ["#010203"] * 8
        ramps = pixelart.bird_ramps(0.95, {"inferno": ramp})
        self.assertTrue(np.allclose(ramps[0][0], pixelart.rgb("#010203")))


class CommandLineTests(unittest.TestCase):
    def test_sample_writes_both_themes(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as log:
            generate.main(["--sample", "ash", "--out", tmp])
            self.assertEqual(sorted(os.listdir(tmp)), ["phoenix-dark.gif", "phoenix-light.gif"])
        self.assertIn("stage=ash", log.getvalue())

    def test_disabling_rebirth_in_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w") as fh:
                json.dump({**CONFIG, "enableRebirth": False}, fh)
            with contextlib.redirect_stdout(io.StringIO()) as log:
                generate.main(["--sample", "rebirth", "--out", tmp, "--config", path])
        self.assertIn("reborn=False", log.getvalue())


if __name__ == "__main__":
    unittest.main()
