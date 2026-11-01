"""Load a daily contribution series from GitHub or from a fixture file."""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def from_github(login: str, token: str | None = None) -> dict[dt.date, int]:
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set; pass --sample to render offline.")
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "User-Agent": "git-phoenix"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise SystemExit(f"GitHub API error: {payload['errors']}")
    weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {
        dt.date.fromisoformat(d["date"]): d["contributionCount"]
        for w in weeks
        for d in w["contributionDays"]
    }


def from_fixture(path: str) -> tuple[dict[dt.date, int], dt.date, dict]:
    """Fixture format: {"end": "YYYY-MM-DD", "counts": [oldest, ..., newest]}.

    A fixture may also carry "previous_state", the stored state to start from.
    """
    with open(path) as fh:
        data = json.load(fh)
    end = dt.date.fromisoformat(data["end"])
    counts = data["counts"]
    days = {end - dt.timedelta(days=len(counts) - 1 - i): c for i, c in enumerate(counts)}
    return days, end, data.get("previous_state", {})
