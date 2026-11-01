"""Heat score, stage selection, and rebirth state for Git Phoenix.

Everything here is pure: it takes a daily contribution series and returns
numbers, so it can be tested without the network.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# Caps: activity at or above these counts saturates its term at 1.0.
CAP_14D = 300
CAP_60D = 1200

# Term weights. They sum to 1.0, so heat stays in [0, 1].
W_14D = 0.45
W_60D = 0.35
W_ACTIVE = 0.20

# Lower bound of each stage, checked from hottest to coolest.
# Ash is special: it means zero contributions in the last 14 days.
STAGES = ("ash", "ember", "flame", "blaze", "inferno")
THRESHOLDS = {"inferno": 0.80, "blaze": 0.60, "flame": 0.35, "ember": 0.0}


@dataclass(frozen=True)
class Activity:
    last_14: int
    last_60: int
    active_days: int
    window_days: int

    @property
    def active_ratio(self) -> float:
        return self.active_days / self.window_days if self.window_days else 0.0


def summarize(days: dict[dt.date, int], today: dt.date, window: int = 365) -> Activity:
    """Collapse a {date: count} map into the three numbers the heat score uses."""

    def total(n: int) -> int:
        return sum(days.get(today - dt.timedelta(days=i), 0) for i in range(n))

    active = sum(1 for i in range(window) if days.get(today - dt.timedelta(days=i), 0) > 0)
    return Activity(total(14), total(60), active, window)


def heat(a: Activity) -> float:
    score = (
        W_14D * min(a.last_14 / CAP_14D, 1.0)
        + W_60D * min(a.last_60 / CAP_60D, 1.0)
        + W_ACTIVE * min(a.active_ratio, 1.0)
    )
    return round(score, 4)


def stage_for(a: Activity) -> str:
    if a.last_14 == 0:
        return "ash"
    h = heat(a)
    for name in ("inferno", "blaze", "flame", "ember"):
        if h >= THRESHOLDS[name]:
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
    state = {"stage": stage, "date": iso, "rebirth_date": rebirth_date}
    return state, reborn
