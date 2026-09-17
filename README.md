# SSL Team Tracker & GM Dashboard

A Streamlit dashboard for Simulation Soccer League GMs: squad quality, positional
depth, finances, availability and historical trends, built on the live SSL API.

## Running it

```bash
pip install -r requirements.txt
streamlit run team.py
```

`python test_offline.py` runs the analytics checks. They need no network and no
Streamlit — just pandas — so they're safe to run in CI.

## Layout

Every file sits at the repo root. There are no packages or subfolders, because
Streamlit Community Cloud pins the main file path at deploy time and the flat
layout is far easier to maintain through GitHub's web interface.

| File | Responsibility |
|---|---|
| `team.py` | Entry point: caching, refresh, sidebar filters, page routing |
| `config.py` | Every constant worth changing. Start here. |
| `data.py` | API fetch, schema validation, normalisation, Sheet loading, endpoint probe |
| `metrics.py` | Position taxonomy, Best XI solver, gap analysis, value metrics, insights |
| `charts.py` | One Plotly template, deterministic team colours, chart builders |
| `ui.py` | Theme CSS, notices, currency formatting, CSV export |
| `page_*.py` | One module per page: overview, team, compare, players, projection, history, admin |
| `projection.py` | Regression rules, measured earning rates, peaks, org simulation |
| `scripts/fetch_history.py` | Builds the TPE history cache (run by the Action) |
| `.github/workflows/` | Weekly job that refreshes `cache/` and commits it |
| `cache/` | Generated. Committed on purpose — do not gitignore it. |
| `.streamlit/config.toml` | Dark theme. Must live at this exact path or it's ignored. |

`team.py` keeps its name from the original single-file version. The deployment is
pinned to that path and Streamlit offers no way to change it after the fact, so
renaming it would break the live app's URL. Nothing else survives from the old
file.

## Things a maintainer should know

**There is no hardcoded team list.** Clubs, parent organisations and Major/Minor
tiers are derived at run time from each player's `organization` and `affiliate`
fields. A new club appears the moment a player is assigned to it. Admin →
Organisations shows the current directory; nothing is ever dropped for being
unrecognised.

**Two different position questions, two different answers.** Squad breakdowns
group on `position`, the player's single declared primary position, so counts sum
to the squad exactly once. The coverage heatmap uses the `pos_*` familiarity
columns, which overlap heavily — one player can be rated at four positions — and
is labelled as depth of cover, never as squad composition. Mixing these is what
made the old positional matrix double-count.

**Best XI is formation-constrained and provably optimal.** Players are offered to
the formation in descending TPE order and admitted via an augmenting path, which
yields the highest-TPE eleven that still fills every slot. `test_offline.py`
checks this against brute force. The old "Starting XI" filter survives under its
honest name, "Top 11 by TPE" — it ignores position and will happily return eleven
strikers.

**Free agents are not a club.** The API returns them as a team with a real roster.
They're excluded from league analytics by default and there's a sidebar toggle.

**Currency is unverified.** The API returns bare integers for `bankBalance` and
`minimum salary` with no unit anywhere in the payload, so `CURRENCY_PREFIX` in
`config.py` is empty. Set it once you've confirmed what SSL actually uses and
every figure in the app updates.

**The Google Sheet is the only fragile input.** It's the sole source for
historical data, and the only thing that can't be validated against a schema. The
loader prefers a pinned layout (`SHEET_LAYOUT`); if you leave `header_row` as
`None` it falls back to scanning and says so. Every failure mode produces a
distinct message rather than an empty tab. Sheet-to-API name matching runs
override, then exact, then close match, and anything that falls through is listed
in Admin → Name matching instead of quietly failing the merge.

**Endpoint discovery is built in.** The published docs at `/__docs__` currently
return 404, so Admin → API endpoints probes a candidate list live from wherever
the app is deployed. If a teams, standings, or player-history endpoint turns up,
add a loader in `data.py` — the Player profile page has a marked spot where TPE
progression would slot in.

## Adding a formation

Add an entry to `FORMATIONS` in `config.py` as a list of `(label, pos_column)`
pairs, eleven long. Best XI and the gap analysis both pick it up with no other
changes.

## Adding a page

Create `page_yourname.py` with a `render(ctx)` function, import it in `team.py`,
and add one line to the `pages` dict. The `Context` dataclass at the top of
`team.py` documents what `ctx` carries.


## Projections

### How the cache works

`getTPEhistory` is one API call per player, so a full refresh is 300+ requests
and can't run on a page load. Streamlit Cloud also wipes its filesystem on every
reboot, so a runtime cache would be rebuilt constantly.

Instead, `.github/workflows/update-tpe-history.yml` runs every Monday, calls
`scripts/fetch_history.py`, and commits two small files to `cache/`. The
dashboard only ever reads those files. You get instant loads and a versioned
archive of league history as a side effect.

Run it by hand any time from the repo's **Actions** tab (Update TPE history →
Run workflow) — worth doing right after a regression post lands. Locally:

```bash
python scripts/fetch_history.py
```

The Projection page degrades gracefully: if `cache/tpe_by_season.csv` is
missing, it says so and points at the Action. Nothing else in the dashboard
depends on it.

### What the model does and doesn't assume

**Regression is exact.** The rulebook fixes it: career season 8 costs 10%,
rising 5 points a season to a 40% cap at season 14+. Career season is
`current_season - class + 1`, so a S13 draftee is in season 8 during S20.

**Earning is measured, never assumed.** Each player's rate is the mean TPE they
actually logged per complete season, over a configurable window. Rates are held
fixed across the horizon by choice — no decay toward the mean.

Two things that will look like bugs and aren't:

- **Historical TPE logs won't reconcile against the current rules.** Both the
  regression table and training camp were changed around S22 (regression used to
  start a season earlier; camp paid 30/20/6 rather than 24/18/12/6). The model
  projects forward under current rules and makes no attempt to replay history.
- **Peak is a plateau at career season 8, not a spike**, and it sits there at
  every effort level. TPE scales with earnings, so the ratio between them doesn't
  move — effort sets how high you peak, never when. The real cliff is season 9,
  where 15% starts outrunning anything a player can earn back.

### Known limits

- A measured rate includes training camp, which steps down from 24 to 6 TPE over
  a career, so young players carry up to ~18 TPE/season of optimism.
- Draftees enter around 420 TPE (250 at creation plus one academy season) and
  need roughly six seasons to reach a strong org's Major XI. Inside a five-season
  horizon the draft only moves the needle for the weakest orgs.
- Attrition is a hazard rate, not a prediction. The 10th-90th percentile band on
  the org projection is as important as the median line.
