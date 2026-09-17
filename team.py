"""
SSL Team Tracker & GM Dashboard — application entry point.

Run with:  streamlit run team.py

The filename is inherited from the original single-file version. Streamlit
Community Cloud pins the main file path at deploy time and offers no way to
change it afterwards, so keeping this name is what lets the existing
deployment and its URL carry on working. Everything else was rewritten.
Page modules live in page_*.py; shared logic in config/data/metrics/charts/ui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import charts
import config
import data
import metrics
import projection
import ui
from data import LoadResult
import page_admin
import page_compare
import page_history
import page_overview
import page_players
import page_projection
import page_team

st.set_page_config(
    page_title="SSL Team Tracker",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

charts.install_template()
ui.inject_css()


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------
# The cache key includes a nonce from session state. Bumping the nonce forces a
# real fetch, which is what the Refresh button does — the TTL still applies on
# its own for everyone who doesn't press it.


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def load_players(nonce: int) -> LoadResult:
    return data.fetch_players(nonce)


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def load_history(nonce: int) -> tuple[LoadResult, str]:
    return data.fetch_sheet_history(nonce)


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def load_tpe_history(nonce: int):
    """Local cache file written by the weekly GitHub Action — no API calls."""
    del nonce
    return data.load_history_cache()


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def load_current_season(nonce: int):
    del nonce
    return data.fetch_current_season()


# ---------------------------------------------------------------------------
# View context
# ---------------------------------------------------------------------------


@dataclass
class Context:
    """Everything a view needs, assembled once per run."""

    full_frame: pd.DataFrame          # all players, unfiltered
    frame: pd.DataFrame               # after sidebar filters
    ranked_frame: pd.DataFrame        # after the roster-scope filter
    players: LoadResult
    history: LoadResult
    history_label: str
    history_matched: pd.DataFrame
    history_fuzzy: list
    history_unmatched: list
    group_col: str
    group_label: str
    entity_noun: str
    metric: str
    formation: str
    roster_label: str
    current_season: int
    rates: object = None              # projection.RateTable
    tpe_history: pd.DataFrame | None = None   # per-season logged TPE
    history_notices: list = field(default_factory=list)
    horizon: int = config.DEFAULT_HORIZON
    attrition: float = config.DEFAULT_ATTRITION
    draftees: int = config.DEFAULT_DRAFTEES_PER_SEASON
    draftee_tpe: int = config.DEFAULT_DRAFTEE_ENTRY_TPE
    season_remaining: float = 0.5     # of the current season, for step-1 earnings
    color_map: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def render_status(fetched_at: datetime, ok: bool) -> None:
    local = fetched_at.astimezone(timezone.utc)
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    if age < 90:
        freshness = "just now"
    elif age < 3600:
        freshness = f"{int(age // 60)} min ago"
    else:
        freshness = f"{age / 3600:.1f} h ago"

    state = "Live" if ok else "Stale"
    ui.status_bar(
        state,
        f"Data as of {local:%H:%M UTC on %d %b %Y} · fetched {freshness}",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.session_state.setdefault("nonce", 0)

    st.title("SSL Team Tracker")

    with st.spinner("Loading player data…"):
        players_result = load_players(st.session_state["nonce"])

    # ---- Sidebar: refresh -------------------------------------------------
    with st.sidebar:
        st.markdown("### Data")
        if st.button("Refresh now", use_container_width=True):
            st.cache_data.clear()
            st.session_state["nonce"] += 1
            st.session_state.pop("probe_results", None)
            st.rerun()
        st.caption(
            f"Cached for {config.CACHE_TTL_SECONDS // 60} minutes. Refresh "
            "before a draft or deadline to be sure."
        )

    render_status(players_result.fetched_at, players_result.ok)

    if not players_result.ok or players_result.is_empty:
        ui.render_notices(players_result.notices)
        ui.empty_state(
            "The dashboard has no data to work with",
            "Every page depends on the player endpoint. The message above says "
            "what went wrong. Press Refresh once the API is back.",
        )
        return

    ui.render_notices(players_result.notices, only={"error"})

    full = players_result.frame

    # ---- History (optional; failure must not block the app) ---------------
    history_result, history_label = load_history(st.session_state["nonce"])
    api_teams = sorted(full["team"].dropna().astype(str).unique())
    matched, fuzzy, unmatched = data.match_sheet_teams(
        history_result.frame, api_teams
    )

    # ---- Sidebar: filters -------------------------------------------------
    with st.sidebar:
        st.markdown("### View")
        page = st.radio(
            "Page",
            ["Overview", "Team", "Head to head", "Players", "Projection",
             "History", "Admin"],
            label_visibility="collapsed",
        )

        st.markdown("### Filters")

        grouping = st.radio(
            "Group by", ["Club", "Organisation"], horizontal=True,
        )
        group_col = "team" if grouping == "Club" else "org"
        entity_noun = "club" if grouping == "Club" else "organisation"

        tier = st.radio(
            "Tier", ["Both", "Majors only", "Minors only"], horizontal=True,
        )

        roster_scope = st.radio(
            "Roster scope",
            ["Whole squad", "Top 11 by TPE"],
        )
        if roster_scope == "Top 11 by TPE":
            st.caption(
                "Position is ignored here — this can be eleven strikers. For a "
                "shape-aware eleven, use Best XI on the Team page."
            )

        metric = st.radio("Metric", ["Average", "Total"], horizontal=True)

        formation = st.selectbox(
            "Formation", list(config.FORMATIONS), index=list(
                config.FORMATIONS
            ).index(config.DEFAULT_FORMATION),
        )
        st.caption("Drives Best XI and the gap analysis.")

        with st.expander("Projection assumptions"):
            horizon = st.slider(
                "Seasons ahead", 2, 8, config.DEFAULT_HORIZON,
                help="Beyond ~5 the uncertainty band is wider than the signal.",
            )
            rate_window = st.slider(
                "Seasons used to measure earning rate", 1, 6,
                config.DEFAULT_RATE_WINDOW,
                help="Short reacts fast to a change in habits; long is steadier.",
            )
            attrition = st.slider(
                "Chance a user quits per season", 0.0, 0.40,
                config.DEFAULT_ATTRITION, 0.01,
                help="Rises with career age. Retiring players leave regardless.",
            )
            draftees = st.slider(
                "Draftees per season", 0, 4,
                config.DEFAULT_DRAFTEES_PER_SEASON,
            )
            draftee_tpe = st.slider(
                "Draftee entry TPE", 250, 700,
                config.DEFAULT_DRAFTEE_ENTRY_TPE, 10,
                help="250 at creation plus one academy season of tasks.",
            )

        include_free_agents = st.checkbox(
            "Include free agents", value=False,
            help=(
                "Free agents are returned by the API as a team but aren't a "
                "club. Including them will distort league averages."
            ),
        )

    # ---- Apply filters ----------------------------------------------------
    frame = full if include_free_agents else full[full["is_club"]]

    if tier == "Majors only":
        frame = frame[frame["tier"] == "Major"]
    elif tier == "Minors only":
        frame = frame[frame["tier"] == "Minor"]

    ranked = frame
    if roster_scope == "Top 11 by TPE" and not frame.empty:
        ranked = metrics.top_n_by_tpe(frame, group_col, 11)
        frame = ranked

    color_map = charts.assign_team_colors(
        list(full["team"].dropna().astype(str).unique())
        + list(full["org"].dropna().astype(str).unique())
        + list(matched["team"].astype(str).unique() if not matched.empty else [])
    )

    # Current season: ask the API, else fall back to the highest draft class,
    # which is the same number in practice and never goes stale.
    api_season, season_notice = load_current_season(st.session_state["nonce"])
    fallback_season = int(full["season_num"].max()) if full["season_num"].notna().any() else 0
    current_season = api_season or fallback_season

    tpe_history, history_meta, history_notices = load_tpe_history(
        st.session_state["nonce"]
    )
    if season_notice:
        history_notices = list(history_notices) + [season_notice]
    # Current TPE already contains this season's earnings to date, so the first
    # projected step must only add what is left of it.
    season_left = projection.season_remaining(
        history_meta.get("season_starts"), current_season
    )
    rates = projection.measure_rates(
        tpe_history, current_season, window=rate_window,
        generated_at=history_meta.get("generated_at"),
    )

    ctx = Context(
        full_frame=full,
        frame=frame,
        ranked_frame=ranked,
        players=players_result,
        history=history_result,
        history_label=history_label,
        history_matched=matched,
        history_fuzzy=fuzzy,
        history_unmatched=unmatched,
        group_col=group_col,
        group_label=f"{entity_noun}s",
        entity_noun=entity_noun,
        metric=metric,
        formation=formation,
        roster_label=roster_scope,
        current_season=current_season,
        rates=rates,
        tpe_history=tpe_history,
        history_notices=history_notices,
        horizon=horizon,
        attrition=attrition,
        draftees=draftees,
        draftee_tpe=draftee_tpe,
        season_remaining=season_left,
        color_map=color_map,
    )

    # ---- Route ------------------------------------------------------------
    pages = {
        "Overview": page_overview.render,
        "Team": page_team.render,
        "Head to head": page_compare.render,
        "Players": page_players.render,
        "Projection": page_projection.render,
        "History": page_history.render,
        "Admin": page_admin.render,
    }
    pages[page](ctx)

    # A quiet standing pointer to the reconciliation view, so a new club is
    # never something you have to already know to look for.
    with st.sidebar:
        st.divider()
        clubs = full[full["is_club"]]["team"].nunique()
        orgs = full[full["is_club"]]["org"].nunique()
        st.caption(
            f"Season S{current_season} · {clubs} clubs across {orgs} "
            "organisations, read from the API at run time."
        )


if __name__ == "__main__":
    main()
