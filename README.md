# SSL Team Tracker & GM Dashboard

A Streamlit dashboard for Simulation Soccer League GMs: squad quality, positional
depth, finances, availability and historical trends, built on the live SSL API.

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

`python test_offline.py` runs the analytics checks. They need no network and no
Streamlit — just pandas — so they're safe to run in CI.

## Layout

| File | Responsibility |
|---|---|
| `app.py` | Entry point: caching, refresh, sidebar filters, page routing |
| `config.py` | Every constant worth changing. Start here. |
| `data.py` | API fetch, schema validation, normalisation, Sheet loading, endpoint probe |
| `metrics.py` | Position taxonomy, Best XI solver, gap analysis, value metrics, insights |
| `charts.py` | One Plotly template, deterministic team colours, chart builders |
| `ui.py` | Theme CSS, notices, currency formatting, CSV export |
| `views/` | One module per page |

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
historical data, and it's the only thing that can't be validated against a
schema. The loader prefers a pinned layout (`SHEET_LAYOUT`); if you leave
`header_row` as `None` it falls back to scanning and says so. Every failure mode
produces a distinct message rather than an empty tab. Sheet-to-API name matching
runs override → exact → close match, and anything that falls through is listed in
Admin → Name matching instead of quietly failing the merge.

**Endpoint discovery is built in.** The published docs at `/__docs__` currently
return 404, so Admin → API endpoints probes a candidate list live from wherever
the app is deployed. If a teams, standings, or player-history endpoint turns up,
add a loader in `data.py` — the Player profile page has a marked spot where TPE
progression would slot in.

## Adding a formation

Add an entry to `FORMATIONS` in `config.py` as a list of `(label, pos_column)`
pairs, eleven long. Best XI and the gap analysis both pick it up with no other
changes.
