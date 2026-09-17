"""TPE projection: where players peak and where organisations are heading."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import config
import projection
import ui


def render(ctx) -> None:
    st.header("Projection")

    rates = ctx.rates
    if rates is None or not rates.by_name:
        ui.render_notices(ctx.history_notices)
        ui.empty_state(
            "No measured earning rates available",
            "Projections read cache/tpe_by_season.csv, built by the weekly "
            "'Update TPE history' GitHub Action. Trigger it once from the "
            "Actions tab and this page comes alive. Nothing else in the "
            "dashboard depends on it.",
        )
        return

    covered = len(rates.by_name)
    as_of = (rates.generated_at or "")[:10]
    st.caption(
        f"Earning rates measured from {rates.window} complete season(s) of logged "
        f"TPE events for {covered} players · league median "
        f"{rates.league_median:,.0f} TPE per season"
        + (f" · history as of {as_of}" if as_of else "")
    )
    st.caption(
        "Rates are held fixed across the horizon. They already include training "
        "camp, which steps down from 24 to 6 TPE over a career — so projections "
        "for young players carry a little optimism."
    )

    tab_league, tab_org, tab_player, tab_rates = st.tabs(
        ["League trajectories", "Organisation", "Player peaks", "Rates"]
    )

    with tab_league:
        _league(ctx, rates)
    with tab_org:
        _org(ctx, rates)
    with tab_player:
        _player(ctx, rates)
    with tab_rates:
        _rates(ctx, rates)


# ---------------------------------------------------------------------------


def _org_assumptions(ctx) -> projection.OrgAssumptions:
    return projection.OrgAssumptions(
        horizon=ctx.horizon,
        attrition=ctx.attrition,
        draftees_per_season=ctx.draftees,
        draftee_entry_tpe=ctx.draftee_tpe,
        trials=config.MONTE_CARLO_TRIALS,
    )


def _league(ctx, rates) -> None:
    ui.section(
        "Where every organisation is heading",
        "Major XI average, re-picked each season as the top 11 of the whole org "
        "pool — so promotion from the Minor happens on its own. Bands are the "
        "10th to 90th percentile across simulated attrition.",
    )

    clubs = ctx.full_frame[ctx.full_frame["is_club"]]
    orgs = sorted(clubs["org"].dropna().astype(str).unique())
    if not orgs:
        ui.empty_state("No organisations found", "The API returned no clubs.")
        return

    results = []
    progress = st.progress(0.0, text="Simulating…")
    for i, org in enumerate(orgs, 1):
        squad = clubs[clubs["org"].astype(str) == org]
        proj = projection.project_org(
            squad, rates, ctx.current_season, _org_assumptions(ctx)
        )
        if proj.empty:
            continue
        verdict, detail = projection.trajectory_verdict(proj)
        results.append({
            "Organisation": org,
            "Now": proj.iloc[0]["Median"],
            f"S{ctx.current_season + ctx.horizon}": proj.iloc[-1]["Median"],
            "Change": round(proj.iloc[-1]["Median"] - proj.iloc[0]["Median"], 1),
            "Peak": proj.loc[proj["Median"].idxmax(), "Season"],
            "Verdict": verdict,
            "_proj": proj,
        })
        progress.progress(i / len(orgs), text=f"Simulating… {org}")
    progress.empty()

    if not results:
        ui.empty_state("Nothing to project", "No org had enough players.")
        return

    table = pd.DataFrame(results).drop(columns="_proj").sort_values(
        "Change", ascending=False
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    ui.download(table, "ssl_org_trajectories.csv")

    ui.section("Trajectories", "")
    fig = go.Figure()
    colors = charts.assign_team_colors([r["Organisation"] for r in results])
    for row in results:
        proj = row["_proj"]
        fig.add_trace(go.Scatter(
            x=proj["Season"], y=proj["Median"], name=row["Organisation"],
            mode="lines+markers",
            line=dict(color=colors.get(row["Organisation"]), width=2),
        ))
    fig.update_layout(
        title="Projected Major XI average TPE",
        height=600, hovermode="x unified",
        yaxis_title="XI average TPE",
    )
    st.plotly_chart(fig, use_container_width=True)

    rising = [r for r in results if r["Verdict"] == "Rising"]
    falling = [r for r in results if r["Verdict"] == "Past peak"]
    if falling:
        st.warning(
            "Past peak on their current core: "
            + ", ".join(r["Organisation"] for r in falling),
            icon=":material/trending_down:",
        )
    if rising:
        st.success(
            "Still climbing at the end of the window: "
            + ", ".join(r["Organisation"] for r in rising),
            icon=":material/trending_up:",
        )


# ---------------------------------------------------------------------------


def _org(ctx, rates) -> None:
    clubs = ctx.full_frame[ctx.full_frame["is_club"]]
    orgs = sorted(clubs["org"].dropna().astype(str).unique())
    if not orgs:
        ui.empty_state("No organisations found", "The API returned no clubs.")
        return

    org = st.selectbox("Organisation", orgs, key="proj_org")
    squad = clubs[clubs["org"].astype(str) == org]

    proj = projection.project_org(
        squad, rates, ctx.current_season, _org_assumptions(ctx)
    )
    if proj.empty:
        ui.empty_state("Could not project this org", "Too few players.")
        return

    verdict, detail = projection.trajectory_verdict(proj)
    st.subheader(verdict)
    st.caption(detail)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=proj["Season"], y=proj["High"], mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=proj["Season"], y=proj["Low"], mode="lines", fill="tonexty",
        fillcolor="rgba(47,158,94,0.18)", line=dict(width=0),
        name="80% range",
    ))
    fig.add_trace(go.Scatter(
        x=proj["Season"], y=proj["Median"], mode="lines+markers",
        line=dict(color=config.COLORS["primary"], width=3), name="Median",
    ))
    fig.update_layout(
        title=f"{org} — projected Major XI average",
        height=460, yaxis_title="XI average TPE", hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)
    ui.download(proj, f"ssl_projection_{org}.csv")

    ui.section(
        "Who carries this org, and for how long",
        "Peak season is where each player tops out on their measured rate. "
        "Anyone already past it is losing TPE every season from here.",
    )

    rows = []
    for _, player in squad.sort_values("tpe", ascending=False).iterrows():
        name = str(player["name"])
        if pd.isna(player.get("season_num")):
            continue
        cls = int(player["season_num"])
        live = not bool(player.get("user_inactive", False))
        rate = rates.rate_for(name) if live else 0.0
        summary = projection.peak_summary(
            float(player["tpe"]), cls, rate, ctx.current_season
        )
        rows.append({
            "Player": name,
            "Team": player["team"],
            "Class": player["class"],
            "Career season": summary["career_season"],
            "TPE": int(player["tpe"]),
            "Rate": round(rate),
            "Peak TPE": round(summary["peak_tpe"]),
            "Peak in": ("past peak" if summary["at_peak"]
                        else f"S{summary['peak_season']}"),
            "Regression now": f"{summary['current_regression']:.0%}",
            "Measured": "yes" if rates.is_measured(name) else "assumed",
        })

    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(frame, use_container_width=True, hide_index=True)
        ui.download(frame, f"ssl_player_peaks_{org}.csv")

        past = frame[frame["Peak in"] == "past peak"]
        if not past.empty:
            st.caption(
                f"{len(past)} of {len(frame)} players are past their peak, "
                f"holding {past['TPE'].sum():,} TPE between them."
            )


# ---------------------------------------------------------------------------


def _player(ctx, rates) -> None:
    frame = ctx.full_frame
    names = sorted(frame["name"].dropna().astype(str).unique())
    if not names:
        ui.empty_state("No players loaded", "Nothing to project.")
        return

    name = st.selectbox("Player", names, key="proj_player")
    match = frame[frame["name"].astype(str) == name]
    if match.empty or pd.isna(match.iloc[0].get("season_num")):
        ui.empty_state(
            "Can't project this player",
            "Their draft class couldn't be parsed, so career season is unknown.",
        )
        return

    player = match.iloc[0]
    cls = int(player["season_num"])
    live = not bool(player.get("user_inactive", False))
    measured = rates.is_measured(name)
    rate = rates.rate_for(name) if live else 0.0

    summary = projection.peak_summary(
        float(player["tpe"]), cls, rate, ctx.current_season
    )

    cols = st.columns(5)
    cols[0].metric("TPE now", f"{int(player['tpe']):,}")
    cols[1].metric("Career season", summary["career_season"])
    cols[2].metric("Earning rate", f"{rate:,.0f}/szn")
    cols[3].metric("Peak TPE", f"{summary['peak_tpe']:,.0f}")
    cols[4].metric(
        "Peak", "passed" if summary["at_peak"] else f"S{summary['peak_season']}"
    )

    if not live:
        st.warning(
            "This user is inactive, so the projection assumes zero future "
            "earnings — their TPE only goes down from here.",
            icon=":material/warning:",
        )
    elif not measured:
        st.info(
            "No logged history for this player, so the league median rate is "
            "being used. Treat the numbers as indicative.",
            icon=":material/info:",
        )

    if summary["current_regression"] > 0:
        st.caption(
            f"Regressing {summary['current_regression']:.0%} this season, "
            f"{summary['next_regression']:.0%} next."
        )
    else:
        first = config.REGRESSION_FIRST_SEASON - summary["career_season"]
        st.caption(
            f"No regression yet — first hit in {first} season(s), at "
            f"{config.REGRESSION_SCHEDULE[config.REGRESSION_FIRST_SEASON]:.0%}."
        )

    path = summary["path"].head(ctx.horizon + 1)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=path["Season"], y=path["TPE"], mode="lines+markers",
        line=dict(color=config.COLORS["primary"], width=3), name="Projected TPE",
    ))
    fig.add_hline(
        y=summary["peak_tpe"], line_dash="dot",
        line_color=config.COLORS["amber"],
        annotation_text=f"peak {summary['peak_tpe']:,.0f}",
    )
    fig.update_layout(title=f"{name} — projected TPE", height=420,
                      yaxis_title="TPE")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(path.drop(columns="season_num"),
                 use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------


def _rates(ctx, rates) -> None:
    ui.section(
        "Measured earning rates",
        "Straight from each player's logged TPE events, averaged over complete "
        "seasons only — the current season is partial and would make everyone "
        "look like they had stopped.",
    )

    ui.render_notices(ctx.history_notices)

    frame = ctx.full_frame
    rows = []
    for _, player in frame.iterrows():
        name = str(player["name"])
        rows.append({
            "Player": name,
            "Team": player["team"],
            "Class": player["class"],
            "TPE": int(player["tpe"]),
            "Rate": round(rates.by_name.get(name, float("nan")), 1)
            if name in rates.by_name else None,
            "Seasons measured": rates.seasons_covered.get(name),
            "User": player.get("userStatus", ""),
        })
    table = pd.DataFrame(rows)

    measured = table[table["Rate"].notna()]
    cols = st.columns(4)
    cols[0].metric("Players with history", len(measured))
    cols[1].metric("Without history", len(table) - len(measured))
    cols[2].metric("League median", f"{rates.league_median:,.0f}")
    if not measured.empty:
        cols[3].metric("Highest", f"{measured['Rate'].max():,.0f}")

    ceiling = projection.theoretical_max_season()
    st.caption(
        f"Weekly tasks alone cap out at {ceiling} TPE a season "
        f"({config.WEEKS_PER_SEASON} weeks x one Activity Check plus one PT). "
        "Anything above that is training camp, predictions and capped tasks."
    )

    if not measured.empty:
        fig = go.Figure(go.Histogram(
            x=measured["Rate"], nbinsx=30,
            marker_color=config.COLORS["primary"],
        ))
        fig.add_vline(
            x=ceiling, line_dash="dot", line_color=config.COLORS["amber"],
            annotation_text="weekly-only ceiling",
        )
        fig.update_layout(
            title="Distribution of measured earning rates", height=380,
            xaxis_title="TPE earned per season", yaxis_title="Players",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        table.sort_values("Rate", ascending=False, na_position="last"),
        use_container_width=True, hide_index=True,
    )
    ui.download(table, "ssl_earning_rates.csv")
