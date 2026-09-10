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
import ui
from data import LoadResult
import page_admin
import page_compare
import page_history
import page_overview
import page_players
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
    st.markdown(
        f'<div class="ssl-status"><strong>{state}</strong>'
        f"Data as of {local:%H:%M UTC on %d %b %Y} · fetched {freshness}</div>",
        unsafe_allow_html=True,
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
            ["Overview", "Team", "Head to head", "Players", "History", "Admin"],
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
        color_map=color_map,
    )

    # ---- Route ------------------------------------------------------------
    pages = {
        "Overview": page_overview.render,
        "Team": page_team.render,
        "Head to head": page_compare.render,
        "Players": page_players.render,
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
            f"{clubs} clubs across {orgs} organisations, read from the API at "
            "run time. Admin lists them all."
        )


if __name__ == "__main__":
    main()
