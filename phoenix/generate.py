"""Git Phoenix command line.

    python phoenix/generate.py --user vignesh-nagarajan-vn   # live, needs GITHUB_TOKEN
    python phoenix/generate.py --sample blaze --out dist/    # fake data, no token
    python phoenix/generate.py --preview                     # every stage, for preview.html
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
SAMPLES = (*heat.STAGES, "rebirth")
# Heat values halfway between stage anchors, to check that blending works.
BETWEEN = (0.18, 0.46, 0.75)


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_gif(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def load_sample(name: str) -> tuple[dict, dt.date, dict]:
    return source.from_fixture(os.path.join(HERE, "fixtures", f"{name}.json"))


def render_sample(name: str, out_dir: str, config: dict) -> tuple[float, heat.Metrics, bool]:
    days, end, prev = load_sample(name)
    m = heat.compute_metrics(days, end)
    h = heat.compute_heat(m, config["heat"])
    _, reborn = heat.next_state(prev, heat.stage_for(h), end)
    reborn = reborn and config["enableRebirth"]
    for theme in THEMES:
        write_gif(os.path.join(out_dir, f"phoenix-{theme}.gif"), render.render(h, m, days, end, theme, reborn, config))
    return h, m, reborn


def build_preview(out_dir: str, config: dict) -> None:
    for name in SAMPLES:
        days, end, prev = load_sample(name)
        m = heat.compute_metrics(days, end)
        h = heat.compute_heat(m, config["heat"])
        _, reborn = heat.next_state(prev, heat.stage_for(h), end)
        for theme in THEMES:
            write_gif(os.path.join(out_dir, f"{name}-{theme}.gif"), render.render(h, m, days, end, theme, reborn, config))
    days, end, _ = load_sample("blaze")
    m = heat.compute_metrics(days, end)
    for h in BETWEEN:
        for theme in THEMES:
            write_gif(os.path.join(out_dir, f"heat-{round(h * 100)}-{theme}.gif"), render.render(h, m, days, end, theme, False, config),
            )
    print(f"wrote preview GIFs to {out_dir}")


def log_line(today: dt.date, stage: str, h: float, m: heat.Metrics, reborn: bool) -> str:
    return (
        f"{today} stage={stage} heat={h:.4f} recent14={m.recent14} recent60={m.recent60} "
        f"streak={m.current_streak} daysSinceLast={m.days_since_last} "
        f"activeDays={m.active_days_ratio:.1%} today={m.today_count} reborn={reborn}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render the Git Phoenix GIFs.")
    p.add_argument("--user", help="GitHub login to read contributions for (default: username in the config)")
    p.add_argument("--sample", choices=SAMPLES, help="use fake data instead of calling GitHub")
    p.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p.add_argument("--out", default=os.path.join(HERE, "dist"), help="output directory")
    p.add_argument("--state", help="rebirth state file (default: state.json in the output directory)")
    p.add_argument("--config", default=os.path.join(HERE, "phoenix.config.json"), help="config file")
    p.add_argument("--preview", action="store_true", help="render every stage into phoenix/preview/ for preview.html")
    args = p.parse_args(argv)

    config = read_json(args.config)
    if not config:
        p.error(f"config not found: {args.config}")

    if args.preview:
        build_preview(os.path.join(HERE, "preview"), config)
        return 0

    if args.sample:
        h, m, reborn = render_sample(args.sample, args.out, config)
        _, end, _ = load_sample(args.sample)
        print(log_line(end, heat.stage_for(h), h, m, reborn))
        return 0

    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    days = source.from_github(args.user or config["username"])
    m = heat.compute_metrics(days, today)
    h = heat.compute_heat(m, config["heat"])
    stage = heat.stage_for(h)

    state_path = args.state or os.path.join(args.out, "state.json")
    state, reborn = heat.next_state(read_json(state_path), stage, today)
    reborn = reborn and config["enableRebirth"]
    write(state_path, json.dumps(state, indent=2) + "\n")
    for theme in THEMES:
        write_gif(os.path.join(args.out, f"phoenix-{theme}.gif"), render.render(h, m, days, today, theme, reborn, config))

    print(log_line(today, stage, h, m, reborn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
