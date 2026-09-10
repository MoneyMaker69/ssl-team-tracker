"""League-wide overview."""

from __future__ import annotations

import streamlit as st

import charts
import config
import metrics
import ui


def render(ctx) -> None:
    df = ctx.frame
    group_col = ctx.group_col
    metric = ctx.metric

    if df.empty:
        ui.empty_state(
            "No players match these filters",
            "Widen the tier or squad-size filters in the sidebar, or turn "
            "free agents back on if you filtered them out.",
        )
        return

    st.header("League overview")

    findings = metrics.league_insights(df, group_col)
    if findings:
        columns = st.columns(min(3, len(findings)))
        for i, (label, value) in enumerate(findings):
            with columns[i % len(columns)]:
                ui.insight_card(label, value)

    top = st.columns(4)
    top[0].metric("Clubs", df[group_col].nunique())
    top[1].metric("Players", len(df))
    top[2].metric("Mean TPE", f"{df['tpe'].mean():,.0f}")
    at_risk = int(df["at_risk"].sum()) if "at_risk" in df.columns else 0
    top[3].metric("Inactive or retiring", at_risk)

    st.divider()

    tab_spread, tab_power, tab_pos, tab_life, tab_money = st.tabs(
        ["Spread", "Power rankings", "Positions", "Squad age", "Finances"]
    )

    with tab_spread:
        ui.section(
            "Every player, by club",
            "One dot per player. A tall column is a wide talent gap inside the "
            "squad; a tight cluster is an even roster.",
        )
        st.plotly_chart(
            charts.tpe_distribution(
                df, group_col, ctx.color_map,
                f"TPE distribution across {ctx.group_label.lower()}",
            ),
            use_container_width=True,
        )

    with tab_power:
        ui.section(
            "Power rankings",
            f"Ranked on {ctx.roster_label.lower()}, {metric.lower()} TPE.",
        )
        ranked = (
            ctx.ranked_frame.groupby(group_col, dropna=False)["tpe"]
            .agg("mean" if metric == "Average" else "sum")
            .round(0)
            .reset_index()
            .rename(columns={group_col: "Entity", "tpe": f"{metric} TPE"})
        )
        if ranked.empty:
            ui.empty_state("Nothing to rank", "No squads survived the filters.")
        else:
            podium = ranked.sort_values(f"{metric} TPE", ascending=False).head(5)
            cols = st.columns(len(podium))
            for i, (_, row) in enumerate(podium.iterrows()):
                cols[i].metric(
                    f"{i + 1}. {row['Entity']}", f"{row[f'{metric} TPE']:,.0f}"
                )

            st.plotly_chart(
                charts.ranked_bar(
                    ranked, "Entity", f"{metric} TPE", ctx.color_map,
                    f"{metric} TPE — {ctx.roster_label}",
                ),
                use_container_width=True,
            )
            ui.download(ranked, "ssl_power_rankings.csv")

    with tab_pos:
        ui.section(
            f"{metric} TPE by position group",
            "Each player counted once, under their declared primary position — "
            "so the group columns are a true breakdown of the squad rather than "
            "overlapping buckets.",
        )
        matrix = metrics.entity_matrix(df, group_col, metric)
        if matrix.empty:
            ui.empty_state("Nothing to break down", "No squads match the filters.")
        else:
            st.dataframe(matrix, use_container_width=True, hide_index=True)
            ui.download(matrix, "ssl_position_matrix.csv")

            ui.section(
                "Positional coverage across the league",
                "How many players each squad could field at each position. "
                "These overlap by design — a player rated at three positions is "
                "counted three times — so read it as depth of cover, not squad "
                "size.",
            )
            st.plotly_chart(
                charts.coverage_heatmap(
                    metrics.coverage_matrix(df, group_col),
                    "Players rated 15+ at each position",
                ),
                use_container_width=True,
            )

    with tab_life:
        ui.section(
            "Quality against squad age",
            "Draft class is the age proxy: a lower season number means an older "
            "player. Top-left is a young, strong roster; bottom-right is an "
            "ageing one that needs rebuilding.",
        )
        lifecycle = (
            df.groupby(group_col, dropna=False)
            .agg(
                tpe=("tpe", "mean" if metric == "Average" else "sum"),
                season=("season_num", "mean"),
            )
            .dropna()
            .reset_index()
            .rename(columns={group_col: "Entity", "tpe": f"{metric} TPE",
                             "season": "Mean class"})
        )
        if lifecycle.empty:
            ui.empty_state(
                "No draft-class data to plot",
                "Every player in this selection has an unparseable class value. "
                "Check the Admin page for details.",
            )
        else:
            st.plotly_chart(
                charts.quadrant(
                    lifecycle, "Mean class", f"{metric} TPE", "Entity",
                    ctx.color_map, "Squad quality vs squad age",
                ),
                use_container_width=True,
            )
            ui.download(lifecycle, "ssl_squad_age.csv")

    with tab_money:
        ui.section("Bank balances", "")
        if config.CURRENCY_UNVERIFIED:
            st.caption(
                "The API returns these as bare numbers with no unit. Set "
                "`CURRENCY_PREFIX` in config.py once you've confirmed SSL's "
                "in-universe currency."
            )

        finance = (
            df.groupby(group_col, dropna=False)
            .agg(total=("bankBalance", "sum"), mean=("bankBalance", "mean"))
            .round(0)
            .reset_index()
            .rename(columns={group_col: "Entity", "total": "Total bank",
                             "mean": "Mean bank"})
        )
        column = "Total bank" if metric == "Total" else "Mean bank"
        st.plotly_chart(
            charts.ranked_bar(
                finance, "Entity", column, ctx.color_map, column,
                value_format="{:,.0f}",
            ),
            use_container_width=True,
        )

        if "minimum salary" in df.columns:
            ui.section(
                "Salary commitment",
                "Minimum salary is the floor each player must be paid, not the "
                "contract they actually signed — treat it as a lower bound.",
            )
            salary = (
                df.groupby(group_col, dropna=False)["minimum salary"]
                .sum().reset_index()
                .rename(columns={group_col: "Entity",
                                 "minimum salary": "Committed floor"})
            )
            st.plotly_chart(
                charts.ranked_bar(
                    salary, "Entity", "Committed floor", ctx.color_map,
                    "Combined minimum salary floor",
                ),
                use_container_width=True,
            )
            finance = finance.merge(salary, on="Entity", how="left")

        ui.download(finance, "ssl_finances.csv")
