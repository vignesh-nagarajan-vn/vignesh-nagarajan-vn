# Git Phoenix

An animated SVG phoenix for this profile. It burns hotter as recent commit activity climbs, cools to ash after two quiet weeks, and plays a rebirth animation on the day activity returns. The name is a nod to Phoenix, AZ and BASIS Phoenix.

Open `preview.html` in a browser to see every stage in light and dark.

## Stages

| Stage | When |
|---|---|
| Ash | no contributions in the last 14 days |
| Ember | heat below 0.35 |
| Flame | heat 0.35 to 0.60 |
| Blaze | heat 0.60 to 0.80 |
| Inferno | heat 0.80 and up |

Hotter stages flap faster, glow brighter, raise taller flames, and throw more embers.

## Heat

```
heat = 0.45 * min(last_14_days / 300, 1)
     + 0.35 * min(last_60_days / 1200, 1)
     + 0.20 * active_days_in_last_year / 365
```

Counts come from the GitHub contribution calendar, so they include PRs, issues, and reviews as well as commits. The caps are set high on purpose. With caps of 60 and 200, any busy fortnight hit the ceiling and a normal week looked the same as a sprint.

## Rebirth

`state.json` stores the last stage and the date it was computed. When the stored stage is ash and today's is not, the date is saved as `rebirth_date` and the SVG plays the rebirth sequence. Because the date is stored, a second run on the same day still shows the rebirth instead of cancelling it. The next day the phoenix goes back to its normal stage.

## Running it

Python 3.10 or newer, no dependencies.

```sh
# live data (needs GITHUB_TOKEN)
python phoenix/generate.py --user vignesh-nagarajan-vn

# offline, from a fixture
python phoenix/generate.py --fixture phoenix/fixtures/flame.json --no-state

# regenerate the preview images
python phoenix/generate.py --preview

# tests
python -m unittest discover -s phoenix/tests
```

Output goes to `phoenix/out/phoenix-light.svg` and `phoenix/out/phoenix-dark.svg`.

## Automation

`.github/workflows/phoenix.yml` runs once a day and on manual dispatch. It runs the tests, renders from live data, and commits only when the SVGs or state changed. The commits come from `github-actions[bot]`, so they don't count toward your own activity.

The default `GITHUB_TOKEN` sees public contributions. To count private ones, turn on "Include private contributions on my profile" in your GitHub settings, or add a `PHOENIX_TOKEN` secret with the `read:user` scope.

## Files

| Path | Purpose |
|---|---|
| `heat.py` | heat score, stage choice, rebirth state |
| `source.py` | GitHub GraphQL fetch and fixture loading |
| `render.py` | SVG drawing and animation |
| `generate.py` | command line entry point |
| `fixtures/` | one year of sample data per stage |
| `preview/` | rendered SVGs for every stage, used by `preview.html` |
| `tests/` | unit tests |
