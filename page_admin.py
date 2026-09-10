"""
Admin and diagnostics.

This page exists so that a new club appearing in the league is a visible line
item rather than a support ticket six weeks later.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import data
import ui


def render(ctx) -> None:
    st.header("Admin")
    st.caption(
        "Data reconciliation and API diagnostics. Nothing here changes what "
        "other pages show — it explains it."
    )

    tab_orgs, tab_names, tab_schema, tab_probe = st.tabs(
        ["Organisations", "Name matching", "Schema", "API endpoints"]
    )

    with tab_orgs:
        _organisations(ctx)

    with tab_names:
        _name_matching(ctx)

    with tab_schema:
        _schema(ctx)

    with tab_probe:
        _probe()


# ---------------------------------------------------------------------------


def _organisations(ctx) -> None:
    ui.section(
        "Organisation directory",
        "Built at runtime from the API's `organization` and `affiliate` fields. "
        "There is no hardcoded team list any more, so a new club appears here "
        "the moment a player is assigned to it.",
    )

    directory = data.build_org_directory(ctx.full_frame)
    if directory.empty:
        ui.empty_state("No clubs found", "The API returned no club-assigned players.")
        return

    summary = st.columns(4)
    summary[0].metric("Organisations", directory["org"].nunique())
    summary[1].metric("Clubs", directory["team"].nunique())
    summary[2].metric("Majors", int((directory["tier"] == "Major").sum()))
    summary[3].metric("Minors", int((directory["tier"] == "Minor").sum()))

    st.dataframe(
        directory.rename(columns={
            "team": "Club", "org": "Organisation", "tier": "Tier",
            "players": "Players", "total_tpe": "Total TPE",
        }),
        use_container_width=True, hide_index=True,
    )
    ui.download(directory, "ssl_org_directory.csv")

    # Orgs without a full Major/Minor pair are worth flagging: usually it means
    # a new franchise is mid-setup, occasionally it means bad data.
    pairs = directory.groupby("org")["tier"].apply(set)
    incomplete = [org for org, tiers in pairs.items()
                  if not {"Major", "Minor"}.issubset(tiers)]
    if incomplete:
        st.warning(
            "These organisations don't have both a Major and a Minor side: "
            + ", ".join(incomplete),
            icon=":material/info:",
        )

    non_club = ctx.full_frame[~ctx.full_frame["is_club"]]
    if not non_club.empty:
        ui.section(
            "Non-club rosters",
            "The API returns these as teams, but they aren't clubs. They're "
            "excluded from league averages and power rankings by default; the "
            "sidebar can bring them back in.",
        )
        st.dataframe(
            non_club.groupby("team")
            .agg(Players=("name", "count"), **{"Mean TPE": ("tpe", "mean")})
            .round(0).reset_index().rename(columns={"team": "Roster"}),
            use_container_width=True, hide_index=True,
        )


# ---------------------------------------------------------------------------


def _name_matching(ctx) -> None:
    ui.section(
        "Sheet to API name reconciliation",
        "Sheet spellings are matched to API team names by explicit override, "
        "then exact match, then close match. Anything that falls through is "
        "listed here instead of quietly failing the merge.",
    )

    if ctx.history.is_empty:
        ui.empty_state(
            "No sheet data to reconcile",
            "The History page explains why the sheet couldn't be read.",
        )
        return

    api_teams = sorted(ctx.full_frame["team"].dropna().astype(str).unique())

    if ctx.history_fuzzy:
        st.info(
            f"{len(ctx.history_fuzzy)} sheet name(s) were matched by similarity "
            "rather than exactly. If any of these are wrong, add an explicit "
            "entry to `SHEET_NAME_OVERRIDES` in config.py.",
            icon=":material/info:",
        )
        st.dataframe(
            pd.DataFrame(ctx.history_fuzzy, columns=["Sheet name", "Matched to"]),
            use_container_width=True, hide_index=True,
        )

    if ctx.history_unmatched:
        st.warning(
            f"{len(ctx.history_unmatched)} sheet name(s) match no API team. "
            "They're kept in the History page under their own name — these are "
            "usually defunct or renamed franchises.",
            icon=":material/warning:",
        )
        st.dataframe(
            pd.DataFrame({"Unmatched sheet name": ctx.history_unmatched}),
            use_container_width=True, hide_index=True,
        )

    matched_names = set(ctx.history_matched["team"].astype(str).unique())
    absent_from_sheet = [t for t in api_teams if t not in matched_names]
    if absent_from_sheet:
        st.info(
            f"{len(absent_from_sheet)} club(s) in the API have no history in "
            "the sheet. Expected for newly added clubs.",
            icon=":material/info:",
        )
        st.dataframe(
            pd.DataFrame({"API club with no sheet history": absent_from_sheet}),
            use_container_width=True, hide_index=True,
        )

    if not (ctx.history_fuzzy or ctx.history_unmatched or absent_from_sheet):
        st.success(
            "Every name lines up exactly in both directions.",
            icon=":material/check_circle:",
        )


# ---------------------------------------------------------------------------


def _schema(ctx) -> None:
    ui.section("Load messages", "Everything the loaders reported this run.")
    if ctx.players.notices:
        ui.render_notices(ctx.players.notices)
    else:
        st.success("The player load produced no warnings.",
                   icon=":material/check_circle:")

    ui.section("Fields returned", "")
    frame = ctx.full_frame
    known = set(
        config.REQUIRED_COLUMNS + config.OPTIONAL_COLUMNS
        + list(config.POSITION_COLUMNS.values())
        + config.OUTFIELD_ATTRIBUTES + config.GK_ATTRIBUTES
    )
    derived = {"org", "tier", "is_club", "season_num", "primary_group",
               "is_keeper", "user_inactive", "retiring", "at_risk",
               "created_at", "tpe_unspent"}

    rows = []
    for column in frame.columns:
        if column in derived:
            origin = "derived by this app"
        elif column in known:
            origin = "API, in use"
        else:
            origin = "API, not currently used"
        rows.append({
            "Field": column,
            "Origin": origin,
            "Non-empty": int(frame[column].notna().sum()),
            "Example": str(frame[column].dropna().iloc[0])[:60]
            if frame[column].notna().any() else "—",
        })

    inventory = pd.DataFrame(rows)
    unused = inventory[inventory["Origin"] == "API, not currently used"]
    if not unused.empty:
        st.caption(
            f"{len(unused)} field(s) come back from the API without being used "
            "anywhere yet — worth a look if you're planning the next feature."
        )
    st.dataframe(inventory, use_container_width=True, hide_index=True)
    ui.download(inventory, "ssl_field_inventory.csv")


# ---------------------------------------------------------------------------


def _probe() -> None:
    ui.section(
        "Endpoint discovery",
        "The published API docs at /__docs__ currently return 404, so rather "
        "than guess at what exists, this asks the API directly from wherever "
        "this app is running. Anything answering 200 with JSON is real and can "
        "be wired into data.py.",
    )

    st.caption(
        "Candidates live in `CANDIDATE_ENDPOINTS` in config.py — add to that "
        "list to test more."
    )

    if st.button("Probe endpoints", type="primary"):
        with st.spinner(f"Trying {len(config.CANDIDATE_ENDPOINTS)} paths…"):
            results = data.probe_endpoints()
        st.session_state["probe_results"] = results

    results = st.session_state.get("probe_results")
    if results is None:
        st.caption("Not run yet.")
        return

    live = results[results["Status"] == 200]
    if not live.empty:
        st.success(
            f"{len(live)} endpoint(s) responded: "
            + ", ".join(live["Endpoint"].tolist()),
            icon=":material/check_circle:",
        )
    else:
        st.info(
            "None of the candidates responded with 200. The players endpoint "
            "may genuinely be the only public route.",
            icon=":material/info:",
        )

    st.dataframe(results, use_container_width=True, hide_index=True)
    ui.download(results, "ssl_endpoint_probe.csv")
