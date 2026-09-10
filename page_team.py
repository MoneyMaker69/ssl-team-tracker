"""Single-club deep dive."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts
import config
import metrics
import ui


def _roster_columns(df: pd.DataFrame) -> list[str]:
    wanted = [
        "name", "position", "primary_group", "class", "tpe", "timesregressed",
        "bankBalance", "minimum salary", "userStatus", "playerStatus",
        "nationality",
    ]
    return [c for c in wanted if c in df.columns]


_LABELS = {
    "name": "Player", "position": "Pos", "primary_group": "Group",
    "class": "Class", "tpe": "TPE", "timesregressed": "Regressions",
    "bankBalance": "Bank", "minimum salary": "Min salary",
    "userStatus": "User", "playerStatus": "Status", "nationality": "Nationality",
}


def render(ctx) -> None:
    df = ctx.frame
    if df.empty:
        ui.empty_state(
            "No clubs match these filters",
            "Relax the sidebar filters to bring squads back into view.",
        )
        return

    entities = sorted(str(e) for e in df[ctx.group_col].dropna().unique())
    if not entities:
        ui.empty_state("Nothing to inspect", "No named entity survived the filters.")
        return

    st.header("Team deep dive")
    selected = st.selectbox(f"Choose a {ctx.entity_noun}", entities)
    squad = df[df[ctx.group_col].astype(str) == selected]

    if squad.empty:
        ui.empty_state(
            f"{selected} has no players in this selection",
            "The club exists but every player was filtered out.",
        )
        return

    header = st.columns(5)
    header[0].metric("Players", len(squad))
    header[1].metric("Mean TPE", f"{squad['tpe'].mean():,.0f}")
    header[2].metric("Total TPE", f"{squad['tpe'].sum():,.0f}")
    header[3].metric("Bank", ui.money_compact(squad["bankBalance"].sum()))
    header[4].metric("At risk", int(squad["at_risk"].sum()))

    if ctx.group_col == "team":
        org = squad["org"].iloc[0]
        tier = squad["tier"].iloc[0]
        siblings = sorted(
            ctx.full_frame[
                (ctx.full_frame["org"] == org)
                & (ctx.full_frame["team"] != selected)
            ]["team"].unique()
        )
        note = f"{tier} side of {org}"
        if siblings:
            note += " — affiliated with " + ", ".join(siblings)
        st.caption(note)

    st.divider()

    tabs = st.tabs(
        ["Best XI", "Squad", "Positions", "Gaps", "Attributes", "Availability"]
    )

    # ------------------------------------------------------------------ XI
    with tabs[0]:
        ui.section(
            f"Best XI — {ctx.formation}",
            "Each player is placed in a slot they're rated "
            f"{config.FAMILIARITY_THRESHOLD}+ for, choosing the highest-TPE "
            "eleven that still fills every position.",
        )
        xi, warnings = metrics.best_xi(squad, ctx.formation)
        if xi.empty:
            ui.empty_state(
                "Could not build an XI",
                "This squad has too few players to fill the formation.",
            )
        else:
            display = xi.copy()
            display["In position"] = display["In position"].map(
                {True: "Yes", False: "Out of position"}
            )
            display["At risk"] = display["At risk"].map({True: "Yes", False: ""})
            st.dataframe(display, use_container_width=True, hide_index=True)

            summary = st.columns(3)
            summary[0].metric("XI total TPE", f"{xi['TPE'].sum():,.0f}")
            summary[1].metric("XI mean TPE", f"{xi['TPE'].mean():,.0f}")
            summary[2].metric(
                "Natural fits",
                f"{int((xi['Familiarity'] >= config.FAMILIARITY_NATURAL).sum())}/11",
            )

            for warning in warnings:
                st.warning(warning, icon=":material/warning:")

            ui.download(xi, f"ssl_best_xi_{selected}.csv")

            st.caption(
                "For raw quality regardless of shape, switch the sidebar roster "
                "filter to 'Top 11 by TPE' — that one ignores position entirely."
            )

    # --------------------------------------------------------------- Squad
    with tabs[1]:
        ui.section("Full squad", "Sortable. Regressions double as an age counter.")
        table = squad[_roster_columns(squad)].rename(columns=_LABELS)
        table = table.sort_values("TPE", ascending=False)
        st.dataframe(table, use_container_width=True, hide_index=True)
        ui.download(table, f"ssl_squad_{selected}.csv")

    # ----------------------------------------------------------- Positions
    with tabs[2]:
        ui.section(
            "Squad by position group",
            "Grouped on each player's declared primary position, so the counts "
            "add up to the squad exactly once.",
        )
        st.dataframe(
            metrics.group_summary(squad, ctx.metric),
            use_container_width=True, hide_index=True,
        )

        ui.section(
            "Positional coverage",
            "How many players could line up at each position. These overlap on "
            "purpose — one player rated at three positions counts three times — "
            "so read it as versatility, not squad size.",
        )
        coverage = metrics.coverage_matrix(squad, ctx.group_col)
        if not coverage.empty:
            st.plotly_chart(
                charts.coverage_heatmap(
                    coverage, f"Players able to fill each position — {selected}"
                ),
                use_container_width=True,
            )
            ui.download(coverage, f"ssl_coverage_{selected}.csv")

    # -------------------------------------------------------------- Gaps
    with tabs[3]:
        ui.section(
            "Where this squad is thin",
            f"Measured against {ctx.formation}. Ordered worst first.",
        )
        gaps = metrics.positional_gaps(squad, ctx.formation)
        problems = gaps[gaps["Verdict"].str.startswith(("Short", "No cover"))]
        if problems.empty:
            st.success(
                f"Every position in {ctx.formation} has cover to spare.",
                icon=":material/check_circle:",
            )
        else:
            for _, row in problems.iterrows():
                st.warning(
                    f"**{row['Position']}** — {row['Verdict'].lower()}",
                    icon=":material/warning:",
                )
        st.dataframe(gaps, use_container_width=True, hide_index=True)
        ui.download(gaps, f"ssl_gaps_{selected}.csv")

    # -------------------------------------------------------- Attributes
    with tabs[4]:
        outfield = squad[~squad["is_keeper"]]
        keepers = squad[squad["is_keeper"]]

        ui.section(
            "Outfield attribute profile",
            "Keepers are excluded — their 5s across finishing and crossing drag "
            "a squad average down without saying anything about the outfield.",
        )
        if outfield.empty:
            ui.empty_state(
                "No outfield players in this squad",
                "Everyone here is a goalkeeper.",
            )
        else:
            available = [a for a in config.RADAR_OUTFIELD if a in outfield.columns]
            group_filter = st.selectbox(
                "Limit to a position group",
                ["All outfield"] + [g for g in config.GROUP_ORDER if g != "Goalkeeper"],
                key="team_radar_group",
            )
            scope = outfield if group_filter == "All outfield" else outfield[
                outfield["primary_group"] == group_filter
            ]
            if scope.empty:
                ui.empty_state(
                    f"No {group_filter.lower()} players here",
                    "Pick a different group.",
                )
            else:
                means = scope[available].mean().round(2)
                st.plotly_chart(
                    charts.radar(
                        [(f"{selected} — {group_filter}", means,
                          ctx.color_map.get(selected, config.COLORS["primary"]))],
                        f"{group_filter}, mean of {len(scope)} players",
                    ),
                    use_container_width=True,
                )
                st.caption(
                    "Stamina and natural fitness sit at 20 for nearly every "
                    "player, so they're left off the radar."
                )

        ui.section("Goalkeeping", "")
        gk_available = [a for a in config.GK_ATTRIBUTES if a in squad.columns]
        if keepers.empty:
            st.warning(
                "No goalkeeper on this roster.", icon=":material/warning:"
            )
        elif gk_available:
            gk_means = keepers[gk_available].mean().round(2)
            st.plotly_chart(
                charts.radar(
                    [(f"{selected} keepers", gk_means, config.COLORS["amber"])],
                    f"Keeper attributes, mean of {len(keepers)}",
                ),
                use_container_width=True,
            )
            st.dataframe(
                keepers[["name", "tpe", "class"] + gk_available]
                .rename(columns={"name": "Player", "tpe": "TPE", "class": "Class"})
                .sort_values("TPE", ascending=False),
                use_container_width=True, hide_index=True,
            )

    # ------------------------------------------------------- Availability
    with tabs[5]:
        ui.section(
            "Roster availability",
            "A high-TPE player behind an inactive account is a roster spot that "
            "isn't doing anything. This is the fastest read on that.",
        )
        risk = squad[squad["at_risk"]]
        cols = st.columns(3)
        cols[0].metric("Inactive users", int(squad["user_inactive"].sum()))
        cols[1].metric("Retiring", int(squad["retiring"].sum()))
        cols[2].metric("TPE affected", f"{risk['tpe'].sum():,.0f}")

        if risk.empty:
            st.success(
                "Every player here has an active user and no retirement flag.",
                icon=":material/check_circle:",
            )
        else:
            columns = [c for c in ("name", "position", "tpe", "class",
                                   "userStatus", "playerStatus", "username")
                       if c in risk.columns]
            st.dataframe(
                risk[columns]
                .rename(columns={**_LABELS, "username": "Account"})
                .sort_values("TPE", ascending=False),
                use_container_width=True, hide_index=True,
            )
            ui.download(risk[columns], f"ssl_at_risk_{selected}.csv")
