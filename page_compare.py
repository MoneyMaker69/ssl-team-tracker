"""Head-to-head comparison between two clubs or organisations."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts
import config
import metrics
import ui


def render(ctx) -> None:
    df = ctx.frame
    entities = sorted(str(e) for e in df[ctx.group_col].dropna().unique())

    if len(entities) < 2:
        ui.empty_state(
            "Need two squads to compare",
            "Only one entity survives the current filters. Widen the tier or "
            "squad-size filter in the sidebar.",
        )
        return

    st.header("Head to head")

    picker = st.columns(2)
    team_a = picker[0].selectbox("Side A", entities, index=0)
    team_b = picker[1].selectbox(
        "Side B", entities, index=min(1, len(entities) - 1)
    )

    if team_a == team_b:
        ui.empty_state(
            "Pick two different squads",
            "Side A and Side B are currently the same.",
        )
        return

    squad_a = df[df[ctx.group_col].astype(str) == team_a]
    squad_b = df[df[ctx.group_col].astype(str) == team_b]

    color_a = config.COLORS["primary"]
    color_b = config.COLORS["blue"]

    st.divider()

    headline = st.columns(4)
    headline[0].metric(f"{team_a} — players", len(squad_a))
    headline[1].metric(f"{team_a} — mean TPE", f"{squad_a['tpe'].mean():,.0f}")
    headline[2].metric(f"{team_b} — players", len(squad_b))
    headline[3].metric(f"{team_b} — mean TPE", f"{squad_b['tpe'].mean():,.0f}")

    tab_groups, tab_xi, tab_attrs = st.tabs(
        ["Position groups", "Best XI", "Attributes"]
    )

    with tab_groups:
        ui.section(
            "Strength by position group",
            "Each player counted once, in their declared primary position.",
        )
        summary_a = metrics.group_summary(squad_a, ctx.metric).set_index("Group")
        summary_b = metrics.group_summary(squad_b, ctx.metric).set_index("Group")
        value_col = f"{ctx.metric} TPE"

        merged = pd.DataFrame({
            "Group": config.GROUP_ORDER,
            team_a: [float(summary_a[value_col].get(g, 0)) for g in config.GROUP_ORDER],
            team_b: [float(summary_b[value_col].get(g, 0)) for g in config.GROUP_ORDER],
        })
        merged["Difference"] = (merged[team_a] - merged[team_b]).round(1)

        st.plotly_chart(
            charts.group_comparison(merged, team_a, team_b, ctx.metric),
            use_container_width=True,
        )

        counts = pd.DataFrame({
            "Group": config.GROUP_ORDER,
            f"{team_a} players": [int(summary_a["Players"].get(g, 0))
                                  for g in config.GROUP_ORDER],
            f"{team_b} players": [int(summary_b["Players"].get(g, 0))
                                  for g in config.GROUP_ORDER],
        })
        side_by_side = merged.merge(counts, on="Group")
        st.dataframe(side_by_side, use_container_width=True, hide_index=True)
        ui.download(side_by_side, f"ssl_h2h_{team_a}_vs_{team_b}.csv")

    with tab_xi:
        ui.section(f"Best XI, both sides — {ctx.formation}", "")
        columns = st.columns(2)
        for column, (name, squad) in zip(columns, ((team_a, squad_a), (team_b, squad_b))):
            with column:
                st.markdown(f"**{name}**")
                xi, warnings = metrics.best_xi(squad, ctx.formation)
                if xi.empty:
                    ui.empty_state("No XI available", "Squad too small.")
                    continue
                st.dataframe(
                    xi[["Slot", "Player", "TPE", "Familiarity"]],
                    use_container_width=True, hide_index=True,
                )
                st.metric("XI mean TPE", f"{xi['TPE'].mean():,.0f}")
                for warning in warnings:
                    st.caption(warning)

    with tab_attrs:
        ui.section(
            "Outfield attributes",
            "Keepers excluded from both sides so the comparison is like for like.",
        )
        available = [
            a for a in config.RADAR_OUTFIELD
            if a in df.columns
        ]
        outfield_a = squad_a[~squad_a["is_keeper"]]
        outfield_b = squad_b[~squad_b["is_keeper"]]

        if outfield_a.empty or outfield_b.empty:
            ui.empty_state(
                "One side has no outfield players",
                "The attribute overlay needs outfielders on both sides.",
            )
        else:
            st.plotly_chart(
                charts.radar(
                    [
                        (team_a, outfield_a[available].mean().round(2), color_a),
                        (team_b, outfield_b[available].mean().round(2), color_b),
                    ],
                    "Mean outfield attributes",
                ),
                use_container_width=True,
            )

        ui.section("Goalkeeping", "")
        gk_available = [a for a in config.GK_ATTRIBUTES if a in df.columns]
        keepers_a = squad_a[squad_a["is_keeper"]]
        keepers_b = squad_b[squad_b["is_keeper"]]

        if keepers_a.empty or keepers_b.empty:
            missing = [
                name for name, keepers in ((team_a, keepers_a), (team_b, keepers_b))
                if keepers.empty
            ]
            st.warning(
                "No goalkeeper on the roster: " + ", ".join(missing),
                icon=":material/warning:",
            )
        elif gk_available:
            st.plotly_chart(
                charts.radar(
                    [
                        (team_a, keepers_a[gk_available].mean().round(2), color_a),
                        (team_b, keepers_b[gk_available].mean().round(2), color_b),
                    ],
                    "Mean keeper attributes",
                ),
                use_container_width=True,
            )
