"""Git Phoenix command line.

    python phoenix/generate.py --user vignesh-nagarajan-vn      # live, needs GITHUB_TOKEN
    python phoenix/generate.py --fixture phoenix/fixtures/blaze.json
    python phoenix/generate.py --preview                         # every stage, for preview.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import heat  # noqa: E402
import render  # noqa: E402
import source  # noqa: E402

THEMES = ("light", "dark")


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as fh:
        fh.write(text)


def load_state(path: str) -> dict:
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def build_preview(out_dir: str) -> None:
    for stage in heat.STAGES:
        days, end = source.from_fixture(os.path.join(HERE, "fixtures", f"{stage}.json"))
        a = heat.summarize(days, end)
        for theme in THEMES:
            svg = render.render(heat.stage_for(a), a, heat.heat(a), theme)
            write(os.path.join(out_dir, f"{stage}-{theme}.svg"), svg)
    days, end = source.from_fixture(os.path.join(HERE, "fixtures", "flame.json"))
    a = heat.summarize(days, end)
    for theme in THEMES:
        svg = render.render(heat.stage_for(a), a, heat.heat(a), theme, reborn=True)
        write(os.path.join(out_dir, f"reborn-{theme}.svg"), svg)
    print(f"wrote preview SVGs to {out_dir}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render the Git Phoenix SVGs.")
    p.add_argument("--user", help="GitHub login to read contributions for")
    p.add_argument("--fixture", help="read a fixture JSON file instead of calling GitHub")
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.add_argument("--out", default=os.path.join(HERE, "out"), help="output directory")
    p.add_argument("--state", default=os.path.join(HERE, "state.json"), help="rebirth state file")
    p.add_argument("--no-state", action="store_true", help="do not read or write the state file")
    p.add_argument("--preview", action="store_true", help="render every stage into phoenix/preview/")
    args = p.parse_args(argv)

    if args.preview:
        build_preview(os.path.join(HERE, "preview"))
        return 0

    if args.fixture:
        days, end = source.from_fixture(args.fixture)
        today = dt.date.fromisoformat(args.today) if args.today else end
    elif args.user:
        today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
        days = source.from_github(args.user, today)
    else:
        p.error("pass --user, --fixture, or --preview")

    a = heat.summarize(days, today)
    h = heat.heat(a)
    stage = heat.stage_for(a)

    reborn = False
    if not args.no_state:
        state, reborn = heat.next_state(load_state(args.state), stage, today)
        write(args.state, json.dumps(state, indent=2) + "\n")

    for theme in THEMES:
        write(os.path.join(args.out, f"phoenix-{theme}.svg"), render.render(stage, a, h, theme, reborn))

    print(
        f"{today} stage={stage} heat={h:.2f} 14d={a.last_14} 60d={a.last_60} "
        f"active={a.active_ratio:.0%} reborn={reborn}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
