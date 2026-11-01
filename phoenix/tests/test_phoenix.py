import datetime as dt
import math
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import generate  # noqa: E402
import heat  # noqa: E402
import render  # noqa: E402
import source  # noqa: E402

TODAY = dt.date(2026, 11, 1)


def act(d14, d60, active, window=365):
    return heat.Activity(d14, d60, active, window)


class HeatTests(unittest.TestCase):
    def test_zero_activity_is_zero_heat_and_ash(self):
        a = act(0, 0, 0)
        self.assertEqual(heat.heat(a), 0)
        self.assertEqual(heat.stage_for(a), "ash")

    def test_caps_saturate(self):
        self.assertEqual(heat.heat(act(300, 1200, 365)), 1.0)
        self.assertEqual(heat.heat(act(5000, 9000, 365)), 1.0)

    def test_caps_separate_busy_from_very_busy(self):
        # Under the old caps (60 / 200) these two scored the same.
        self.assertLess(heat.heat(act(80, 250, 100)), heat.heat(act(250, 1000, 100)))

    def test_real_profile_lands_in_blaze(self):
        a = act(233, 1030, 131)
        self.assertAlmostEqual(heat.heat(a), 0.7217, places=4)
        self.assertEqual(heat.stage_for(a), "blaze")

    def test_stage_boundaries(self):
        # Saturate the 14 day term (0.45) and vary the 60 day term to sit
        # just below and exactly on each threshold. Thresholds are inclusive.
        def at(target):
            return act(300, math.ceil((target - 0.45) / 0.35 * 1200), 0)

        self.assertEqual(heat.stage_for(at(0.80)), "inferno")
        self.assertEqual(heat.stage_for(at(0.79)), "blaze")
        self.assertEqual(heat.stage_for(at(0.60)), "blaze")
        self.assertEqual(heat.stage_for(at(0.59)), "flame")
        self.assertEqual(heat.stage_for(act(1, 0, 0)), "ember")
        self.assertEqual(heat.stage_for(act(0, 500, 365)), "ash")

    def test_any_recent_activity_leaves_ash(self):
        self.assertEqual(heat.stage_for(act(1, 1, 1)), "ember")

    def test_summarize_windows(self):
        days = {TODAY - dt.timedelta(days=i): 1 for i in range(100)}
        a = heat.summarize(days, TODAY)
        self.assertEqual((a.last_14, a.last_60, a.active_days), (14, 60, 100))

    def test_summarize_ignores_future_days(self):
        days = {TODAY + dt.timedelta(days=1): 50, TODAY: 2}
        self.assertEqual(heat.summarize(days, TODAY).last_14, 2)


class RebirthTests(unittest.TestCase):
    def test_ash_to_lit_is_rebirth(self):
        prev = {"stage": "ash", "date": "2026-10-31", "rebirth_date": None}
        state, reborn = heat.next_state(prev, "ember", TODAY)
        self.assertTrue(reborn)
        self.assertEqual(state["rebirth_date"], "2026-11-01")

    def test_same_day_rerun_keeps_rebirth(self):
        prev = {"stage": "ash", "date": "2026-10-31", "rebirth_date": None}
        state, _ = heat.next_state(prev, "ember", TODAY)
        state, reborn = heat.next_state(state, "ember", TODAY)
        self.assertTrue(reborn)

    def test_rebirth_ends_next_day(self):
        prev = {"stage": "ember", "date": "2026-11-01", "rebirth_date": "2026-11-01"}
        _, reborn = heat.next_state(prev, "ember", TODAY + dt.timedelta(days=1))
        self.assertFalse(reborn)

    def test_lit_to_lit_is_not_rebirth(self):
        _, reborn = heat.next_state({"stage": "flame", "date": "2026-10-31"}, "blaze", TODAY)
        self.assertFalse(reborn)

    def test_first_run_is_not_rebirth(self):
        _, reborn = heat.next_state({}, "blaze", TODAY)
        self.assertFalse(reborn)

    def test_falling_back_to_ash_same_day_cancels(self):
        prev = {"stage": "ember", "date": "2026-11-01", "rebirth_date": "2026-11-01"}
        _, reborn = heat.next_state(prev, "ash", TODAY)
        self.assertFalse(reborn)


class FixtureTests(unittest.TestCase):
    def test_each_fixture_hits_its_stage(self):
        for stage in heat.STAGES:
            days, end = source.from_fixture(os.path.join(ROOT, "fixtures", f"{stage}.json"))
            self.assertEqual(heat.stage_for(heat.summarize(days, end)), stage, stage)


class RenderTests(unittest.TestCase):
    def test_every_stage_renders_valid_svg_without_filters(self):
        a = act(233, 1030, 131)
        for stage in heat.STAGES:
            for theme in ("light", "dark"):
                for reborn in (False, True):
                    svg = render.render(stage, a, heat.heat(a), theme, reborn)
                    ET.fromstring(svg)
                    self.assertNotIn("<filter", svg)
                    self.assertNotIn("blur(", svg)

    def test_output_is_deterministic(self):
        a = act(233, 1030, 131)
        self.assertEqual(render.render("blaze", a, 0.72), render.render("blaze", a, 0.72))

    def test_cli_writes_both_themes_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "state.json")
            fixture = os.path.join(ROOT, "fixtures", "blaze.json")
            generate.main(["--fixture", fixture, "--out", tmp, "--state", state])
            for theme in ("light", "dark"):
                self.assertTrue(os.path.exists(os.path.join(tmp, f"phoenix-{theme}.svg")))
            self.assertTrue(os.path.exists(state))


if __name__ == "__main__":
    unittest.main()
