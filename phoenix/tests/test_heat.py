import datetime as dt
import json
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import heat  # noqa: E402
import source  # noqa: E402

TODAY = dt.date(2026, 11, 1)

with open(os.path.join(ROOT, "phoenix.config.json")) as fh:
    CONFIG = json.load(fh)["heat"]


def series(*offsets_and_counts):
    """Build {date: count} from (days_ago, count) pairs."""
    return {TODAY - dt.timedelta(days=ago): c for ago, c in offsets_and_counts}


def metrics(recent14=0, recent60=0, streak=0, since=0, ratio=0.0):
    return heat.Metrics(recent14, recent60, streak, since, ratio, 0)


class StreakTests(unittest.TestCase):
    def test_streak_ending_today(self):
        m = heat.compute_metrics(series((0, 1), (1, 1), (2, 1), (4, 1)), TODAY)
        self.assertEqual(m.current_streak, 3)

    def test_streak_ending_yesterday_survives_a_quiet_today(self):
        m = heat.compute_metrics(series((1, 2), (2, 2)), TODAY)
        self.assertEqual(m.current_streak, 2)
        self.assertEqual(m.days_since_last, 1)

    def test_gap_of_two_days_breaks_the_streak(self):
        m = heat.compute_metrics(series((2, 2), (3, 2)), TODAY)
        self.assertEqual(m.current_streak, 0)


class MetricsTests(unittest.TestCase):
    def test_window_edges(self):
        m = heat.compute_metrics(series((13, 1), (14, 2), (59, 4), (60, 8)), TODAY)
        self.assertEqual(m.recent14, 1)
        self.assertEqual(m.recent60, 7)

    def test_today_count_falls_back_to_yesterday(self):
        self.assertEqual(heat.compute_metrics(series((1, 5)), TODAY).today_count, 5)
        self.assertEqual(heat.compute_metrics(series((0, 2), (1, 5)), TODAY).today_count, 2)

    def test_future_days_in_the_calendar_are_ignored(self):
        m = heat.compute_metrics(series((-1, 9), (3, 1)), TODAY)
        self.assertEqual(m.days_since_last, 3)


class HeatTests(unittest.TestCase):
    def test_spec_formula_with_raised_caps(self):
        # Hand calculation from the real profile numbers.
        m = metrics(233, 1030, 3, 0, 0.36)
        expected = (
            0.40 * math.log1p(233) / math.log1p(300)
            + 0.20 * math.log1p(1030) / math.log1p(1200)
            + 0.25 * 3 / 30
            + 0.15 * 0.36
        )
        self.assertAlmostEqual(heat.compute_heat(m, CONFIG), expected, places=3)
        self.assertEqual(heat.stage_for(heat.compute_heat(m, CONFIG)), "blaze")

    def test_caps_separate_busy_from_very_busy(self):
        # Under the spec's original caps (60 / 200) these two scored the same.
        busy = heat.compute_heat(metrics(80, 250, 3, 0, 0.3), CONFIG)
        very_busy = heat.compute_heat(metrics(280, 1100, 3, 0, 0.3), CONFIG)
        self.assertLess(busy, very_busy)

    def test_everything_maxed_is_one(self):
        self.assertEqual(heat.compute_heat(metrics(9000, 9000, 400, 0, 1.0), CONFIG), 1.0)


class CoolingTests(unittest.TestCase):
    def base(self, since):
        return heat.compute_heat(metrics(100, 300, 0, since, 0.3), CONFIG)

    def test_no_cooling_inside_the_grace_period(self):
        self.assertEqual(self.base(0), self.base(3))

    def test_cooling_is_linear_after_grace(self):
        self.assertAlmostEqual(self.base(8), self.base(3) * (1 - 5 / 11), places=3)

    def test_zero_at_fourteen_days_and_beyond(self):
        self.assertEqual(self.base(14), 0)
        self.assertEqual(self.base(40), 0)


class StageTests(unittest.TestCase):
    def test_thresholds(self):
        cases = {
            0.0: "ash",
            0.005: "ember",
            0.01: "ember",
            0.1999: "ember",
            0.20: "kindling",
            0.4499: "kindling",
            0.45: "blaze",
            0.7499: "blaze",
            0.75: "inferno",
            1.0: "inferno",
        }
        for h, stage in cases.items():
            self.assertEqual(heat.stage_for(h), stage, h)

    def test_each_fixture_lands_in_its_stage(self):
        for stage in heat.STAGES:
            days, end, _ = source.from_fixture(os.path.join(ROOT, "fixtures", f"{stage}.json"))
            h = heat.compute_heat(heat.compute_metrics(days, end), CONFIG)
            self.assertEqual(heat.stage_for(h), stage)


class EdgeCaseTests(unittest.TestCase):
    def test_brand_new_account(self):
        m = heat.compute_metrics({}, TODAY)
        self.assertIsNone(m.days_since_last)
        self.assertEqual(heat.compute_heat(m, CONFIG), 0)
        self.assertEqual(heat.stage_for(0), "ash")

    def test_year_of_zero_activity(self):
        days = {TODAY - dt.timedelta(days=i): 0 for i in range(365)}
        m = heat.compute_metrics(days, TODAY)
        self.assertEqual(m.current_streak, 0)
        self.assertEqual(heat.compute_heat(m, CONFIG), 0)

    def test_no_contributions_yet_today_stays_lit(self):
        days = {TODAY - dt.timedelta(days=i): 3 for i in range(1, 11)}
        m = heat.compute_metrics(days, TODAY)
        self.assertEqual(m.current_streak, 10)
        self.assertGreater(heat.compute_heat(m, CONFIG), 0.2)


class RebirthTests(unittest.TestCase):
    def test_leaving_ash_is_a_rebirth(self):
        state, reborn = heat.next_state({"stage": "ash", "date": "2026-10-31"}, "ember", TODAY)
        self.assertTrue(reborn)
        self.assertEqual(state["rebirth_date"], TODAY.isoformat())

    def test_same_day_rerun_keeps_the_rebirth(self):
        state, _ = heat.next_state({"stage": "ash"}, "ember", TODAY)
        _, reborn = heat.next_state(state, "ember", TODAY)
        self.assertTrue(reborn)

    def test_rebirth_lasts_one_day(self):
        state, _ = heat.next_state({"stage": "ash"}, "ember", TODAY)
        _, reborn = heat.next_state(state, "ember", TODAY + dt.timedelta(days=1))
        self.assertFalse(reborn)

    def test_first_ever_run_is_not_a_rebirth(self):
        self.assertFalse(heat.next_state({}, "blaze", TODAY)[1])

    def test_staying_in_ash_is_not_a_rebirth(self):
        self.assertFalse(heat.next_state({"stage": "ash"}, "ash", TODAY)[1])

    def test_rebirth_fixture_triggers_a_rebirth(self):
        days, end, prev = source.from_fixture(os.path.join(ROOT, "fixtures", "rebirth.json"))
        stage = heat.stage_for(heat.compute_heat(heat.compute_metrics(days, end), CONFIG))
        self.assertNotEqual(stage, "ash")
        self.assertTrue(heat.next_state(prev, stage, end)[1])


if __name__ == "__main__":
    unittest.main()
