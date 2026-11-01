"""Metrics, heat score, stage selection, and rebirth state for Git Phoenix.

Everything here is pure: it takes a daily contribution series and returns
numbers, so it can be tested without the network.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

STAGES = ("ash", "ember", "kindling", "blaze", "inferno")

# Lower bound of each lit stage. Ash is exactly zero heat.
THRESHOLDS = (("inferno", 0.75), ("blaze", 0.45), ("kindling", 0.20))


@dataclass(frozen=True)
class Metrics:
    recent14: int
    recent60: int
    current_streak: int
    days_since_last: int | None  # None when there are no contributions at all
    active_days_ratio: float
    today_count: int


def compute_metrics(days: dict[dt.date, int], today: dt.date) -> Metrics:
    def count(offset: int) -> int:
        return days.get(today - dt.timedelta(days=offset), 0)

    # A quiet today doesn't break a streak: the day isn't over yet.
    start = 0 if count(0) > 0 else 1
    streak = 0
    while count(start + streak) > 0:
        streak += 1

    past = [d for d, c in days.items() if c > 0 and d <= today]
    return Metrics(
        recent14=sum(count(i) for i in range(14)),
        recent60=sum(count(i) for i in range(60)),
        current_streak=streak,
        days_since_last=(today - max(past)).days if past else None,
        active_days_ratio=sum(1 for i in range(365) if count(i) > 0) / 365,
        today_count=count(0) or count(1),
    )


def _log_score(value: int, cap: int) -> float:
    return min(1.0, math.log1p(value) / math.log1p(cap))


def compute_heat(m: Metrics, config: dict) -> float:
    if m.days_since_last is None:
        return 0.0
    w, caps, cooling = config["weights"], config["caps"], config["cooling"]
    score = (
        w["recent"] * _log_score(m.recent14, caps["recent14"])
        + w["momentum"] * _log_score(m.recent60, caps["recent60"])
        + w["streak"] * min(1.0, m.current_streak / caps["streakDays"])
        + w["consistency"] * m.active_days_ratio
    )
    if m.days_since_last > cooling["graceDays"]:
        score *= max(0.0, 1 - (m.days_since_last - cooling["graceDays"]) / cooling["fadeDays"])
    return round(score, 4)


def stage_for(h: float) -> str:
    if h <= 0:
        return "ash"
    for name, low in THRESHOLDS:
        if h >= low:
            return name
    return "ember"


def next_state(prev: dict, stage: str, today: dt.date) -> tuple[dict, bool]:
    """Advance the stored state and report whether today is a rebirth day.

    A rebirth happens when the previous stored stage was ash and today's is
    not. The date is stored with it, so a second run on the same day (whose
    previous stage is no longer ash) still renders the rebirth instead of
    cancelling it.
    """
    iso = today.isoformat()
    rebirth_date = prev.get("rebirth_date")
    if prev.get("stage") == "ash" and stage != "ash":
        rebirth_date = iso
    reborn = rebirth_date == iso and stage != "ash"
    return {"stage": stage, "date": iso, "rebirth_date": rebirth_date}, reborn
