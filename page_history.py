"""Historical trends from the published Google Sheet."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

import charts
import ui


def render(ctx) -> None:
    st.header("History")

    result = ctx.history
    label = ctx.history_label

    ui.render_notices(result.notices)

    if result.is_empty:
        ui.empty_state(
            "No historical data loaded",
            "Live player data is unaffected — every other page still works. "
            "The message above says which step failed. This page is the only "
            "part of the dashboard that depends on the Google Sheet.",
        )
        return

    history = ctx.history_matched
    st.caption(
        f"Reading '{label}' from the published sheet · "
        f"{history['season'].nunique()} seasons · "
        f"{history['team'].nunique()} franchises"
    )

    tab_trend, tab_spread, tab_now = st.tabs(
        ["Trend", "Spread", "Then and now"]
    )

    franchises = sorted(history["team"].dropna().astype(str).unique())

    with tab_trend:
        default = franchises[:4]
        chosen = st.multiselect(
            "Franchises", franchises, default=default, key="history_teams"
        )
        if not chosen:
            ui.empty_state(
                "Pick at least one franchise",
                "Choose from the list above to draw the timeline.",
            )
        else:
            subset = history[history["team"].astype(str).isin(chosen)].sort_values(
                "season"
            )
            st.plotly_chart(
                charts.history_lines(subset, ctx.color_map, label),
                use_container_width=True,
            )
            ui.download(subset, "ssl_history_trend.csv")

    with tab_spread:
        ui.section(
            "Every season played",
            "One dot per completed season. A tight cluster near the top is a "
            "consistent side; a long vertical spread is a franchise that has "
            "peaked and rebuilt.",
        )
        order = (
            history.groupby("team")["value"].max()
            .sort_values(ascending=False).index.tolist()
        )
        fig = px.strip(
            history, x="team", y="value", color="team",
            hover_data=["season"], category_orders={"team": order},
            color_discrete_map=ctx.color_map,
            labels={"team": "", "value": label},
            title=f"{label} spread by franchise",
        )
        fig.update_traces(marker=dict(size=8, opacity=0.75), jitter=0.6)
        fig.update_layout(showlegend=False, xaxis_tickangle=-40, height=520)
        st.plotly_chart(fig, use_container_width=True)

    with tab_now:
        ui.section(
            "Peak against today",
            "Historical peak from the sheet, current figure from the live API.",
        )
        current = (
            ctx.full_frame[ctx.full_frame["is_club"]]
            .sort_values("tpe", ascending=False)
            .groupby("team").head(11)
            .groupby("team")["tpe"].mean().round(1)
            .reset_index()
            .rename(columns={"team": "Franchise", "tpe": "Current top 11 mean"})
        )
        # idxmax rather than groupby.apply: the apply signature changed between
        # pandas 2.1 and 3.0, this hasn't.
        peak_rows = history.loc[history.groupby("team")["value"].idxmax()]
        peak = (
            peak_rows[["team", "value", "season"]]
            .rename(columns={"team": "Franchise", "value": "Peak",
                             "season": "Peak season"})
            .reset_index(drop=True)
        )

        merged = current.merge(peak, on="Franchise", how="outer")
        merged["Gap to peak"] = (
            merged["Current top 11 mean"] - merged["Peak"]
        ).round(1)
        merged = merged.sort_values("Peak", ascending=False)

        missing_current = merged["Current top 11 mean"].isna().sum()
        missing_peak = merged["Peak"].isna().sum()
        if missing_current or missing_peak:
            st.caption(
                f"{int(missing_current)} franchise(s) appear only in the sheet, "
                f"{int(missing_peak)} only in the live API. Both are kept here "
                "rather than dropped — see Admin for the name reconciliation."
            )

        st.dataframe(merged, use_container_width=True, hide_index=True)
        ui.download(merged, "ssl_peak_vs_current.csv")
