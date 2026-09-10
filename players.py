"""Player search, individual profiles, and league-wide player leaderboards."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import charts
import config
import metrics
import ui


def render(ctx) -> None:
    st.header("Players")
    st.caption(
        "Search runs across the whole league, independent of the sidebar's club "
        "filters."
    )

    df = ctx.full_frame

    tab_search, tab_profile, tab_regression, tab_value, tab_nations = st.tabs(
        ["Search", "Profile", "Regression", "Value", "Nationality"]
    )

    with tab_search:
        _search(df)

    with tab_profile:
        _profile(df, ctx)

    with tab_regression:
        _regression(df)

    with tab_value:
        _value(df)

    with tab_nations:
        _nations(df, ctx)


# ---------------------------------------------------------------------------


def _search(df: pd.DataFrame) -> None:
    filters = st.columns(4)
    query = filters[0].text_input("Name contains", "")

    positions = ["Any"] + sorted(df["position"].dropna().astype(str).unique())
    position = filters[1].selectbox("Position", positions)

    if "nationality" in df.columns:
        nations = ["Any"] + sorted(df["nationality"].dropna().astype(str).unique())
        nation = filters[2].selectbox("Nationality", nations)
    else:
        nation = "Any"

    teams = ["Any"] + sorted(df["team"].dropna().astype(str).unique())
    team = filters[3].selectbox("Team", teams)

    result = df
    if query.strip():
        result = result[result["name"].astype(str).str.contains(
            query.strip(), case=False, na=False
        )]
    if position != "Any":
        result = result[result["position"].astype(str) == position]
    if nation != "Any":
        result = result[result["nationality"].astype(str) == nation]
    if team != "Any":
        result = result[result["team"].astype(str) == team]

    minimum, maximum = int(df["tpe"].min()), int(df["tpe"].max())
    if minimum < maximum:
        low, high = st.slider("TPE range", minimum, maximum, (minimum, maximum))
        result = result[result["tpe"].between(low, high)]

    st.caption(f"{len(result):,} of {len(df):,} players")

    if result.empty:
        ui.empty_state(
            "Nothing matches that search",
            "Clear a filter or widen the TPE range.",
        )
        return

    columns = [c for c in ("name", "team", "tier", "position", "class", "tpe",
                           "timesregressed", "bankBalance", "nationality",
                           "userStatus", "playerStatus")
               if c in result.columns]
    table = result[columns].rename(columns={
        "name": "Player", "team": "Team", "tier": "Tier", "position": "Pos",
        "class": "Class", "tpe": "TPE", "timesregressed": "Regressions",
        "bankBalance": "Bank", "nationality": "Nationality",
        "userStatus": "User", "playerStatus": "Status",
    }).sort_values("TPE", ascending=False)

    st.dataframe(table, use_container_width=True, hide_index=True)
    ui.download(table, "ssl_player_search.csv")


# ---------------------------------------------------------------------------


def _profile(df: pd.DataFrame, ctx) -> None:
    names = sorted(df["name"].dropna().astype(str).unique())
    if not names:
        ui.empty_state("No players loaded", "The API returned nothing to show.")
        return

    selected = st.selectbox("Player", names, key="profile_player")
    matches = df[df["name"].astype(str) == selected]
    if matches.empty:
        ui.empty_state("Player not found", "Pick another name.")
        return
    player = matches.iloc[0]

    st.subheader(selected)
    subtitle = f"{player['position']} · {player['team']}"
    if player.get("tier") and player["tier"] != "Unclassified":
        subtitle += f" ({player['tier']})"
    if player.get("nationality"):
        subtitle += f" · {player['nationality']}"
    st.caption(subtitle)

    top = st.columns(5)
    top[0].metric("TPE", f"{int(player['tpe']):,}")
    top[1].metric("Class", str(player["class"]))
    top[2].metric("Regressions", int(player.get("timesregressed", 0)))
    top[3].metric("Bank", ui.money_compact(player["bankBalance"]))
    if "minimum salary" in df.columns:
        top[4].metric("Min salary", ui.money_compact(player["minimum salary"]))

    flags = []
    if player.get("user_inactive"):
        flags.append("The account behind this player is inactive.")
    if player.get("retiring"):
        flags.append("This player is flagged as retiring.")
    for flag in flags:
        st.warning(flag, icon=":material/warning:")

    st.divider()

    left, right = st.columns([2, 3])

    with left:
        st.markdown("**Positional familiarity**")
        familiarity = pd.DataFrame({
            "Position": list(config.POSITION_COLUMNS),
            "Rating": [int(player[col]) for col in config.POSITION_COLUMNS.values()],
        })
        familiarity = familiarity[familiarity["Rating"] > 0].sort_values(
            "Rating", ascending=False
        )
        if familiarity.empty:
            st.caption("No position ratings recorded.")
        else:
            st.dataframe(familiarity, use_container_width=True, hide_index=True)

        details = []
        for key, label in (("height", "Height"), ("weight", "Weight"),
                           ("birthplace", "Birthplace"), ("region", "Region"),
                           ("username", "Account"), ("pid", "Player ID")):
            if key in df.columns and pd.notna(player.get(key)) and str(player[key]).strip():
                details.append((label, str(player[key])))
        if "left foot" in df.columns and "right foot" in df.columns:
            details.append((
                "Feet", f"L {int(player['left foot'])} / R {int(player['right foot'])}"
            ))
        if "created_at" in df.columns and pd.notna(player.get("created_at")):
            details.append(("Created", player["created_at"].strftime("%Y-%m-%d")))
        if details:
            st.markdown("**Details**")
            st.dataframe(
                pd.DataFrame(details, columns=["Field", "Value"]),
                use_container_width=True, hide_index=True,
            )

        if "traits" in df.columns:
            traits = str(player.get("traits", "")).strip()
            if traits and traits.upper() != "NO TRAITS":
                st.markdown("**Traits**")
                for trait in traits.split(","):
                    st.caption(f"· {trait.strip()}")

    with right:
        is_keeper = bool(player.get("is_keeper", False))
        attribute_set = config.GK_ATTRIBUTES if is_keeper else config.RADAR_OUTFIELD
        available = [a for a in attribute_set if a in df.columns]
        if available:
            values = player[available].astype(float).round(0)
            st.plotly_chart(
                charts.radar(
                    [(selected, values,
                      config.COLORS["amber"] if is_keeper
                      else config.COLORS["primary"])],
                    "Goalkeeper attributes" if is_keeper else "Outfield attributes",
                ),
                use_container_width=True,
            )

    st.markdown("**Full attribute breakdown**")
    for group, attributes in config.ATTRIBUTE_GROUPS.items():
        present = [a for a in attributes if a in df.columns]
        if not present:
            continue
        st.caption(group)
        st.dataframe(
            pd.DataFrame([{a.title(): int(player[a]) for a in present}]),
            use_container_width=True, hide_index=True,
        )
    gk_present = [a for a in config.GK_ATTRIBUTES if a in df.columns]
    if gk_present and (is_keeper or player[gk_present].max() > 5):
        st.caption("Goalkeeping")
        st.dataframe(
            pd.DataFrame([{a.title(): int(player[a]) for a in gk_present}]),
            use_container_width=True, hide_index=True,
        )

    st.caption(
        "TPE progression and bank history aren't in this API's player payload. "
        "If a history endpoint turns up in the Admin page's endpoint probe, "
        "this is where it would slot in."
    )


# ---------------------------------------------------------------------------


def _regression(df: pd.DataFrame) -> None:
    if "timesregressed" not in df.columns:
        ui.empty_state(
            "Regression data isn't in this response",
            "The API didn't return a `timesregressed` field.",
        )
        return

    ui.section(
        "Regression leaderboard",
        "Regressions accumulate roughly once a season, so this doubles as an "
        "age counter — and the most-regressed players are the ones whose TPE "
        "will keep falling.",
    )

    clubs = df[df["is_club"]]
    top = st.columns(3)
    top[0].metric("Most regressed", int(df["timesregressed"].max()))
    top[1].metric("League mean", f"{df['timesregressed'].mean():.1f}")
    top[2].metric(
        "Players at 5+", int((df["timesregressed"] >= 5).sum())
    )

    columns = [c for c in ("name", "team", "position", "class", "tpe",
                           "timesregressed") if c in df.columns]
    table = (
        df[columns]
        .rename(columns={"name": "Player", "team": "Team", "position": "Pos",
                         "class": "Class", "tpe": "TPE",
                         "timesregressed": "Regressions"})
        .sort_values(["Regressions", "TPE"], ascending=[False, False])
        .head(50)
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    ui.download(table, "ssl_regression_leaderboard.csv")

    if not clubs.empty:
        ui.section("Mean regressions by club", "A proxy for how old each squad is.")
        by_club = (
            clubs.groupby("team")["timesregressed"].mean().round(2)
            .reset_index()
            .rename(columns={"team": "Entity", "timesregressed": "Mean regressions"})
        )
        st.plotly_chart(
            charts.ranked_bar(
                by_club, "Entity", "Mean regressions",
                charts.assign_team_colors(by_club["Entity"].tolist()),
                "Mean regressions per squad", value_format="{:.2f}",
            ),
            use_container_width=True,
        )


# ---------------------------------------------------------------------------


def _value(df: pd.DataFrame) -> None:
    ui.section(
        "Value for money",
        "The API exposes no contract value, so this ranks TPE against minimum "
        "salary — the floor a player must be paid. It answers 'how much quality "
        "am I obliged to pay for', which is the closest honest analogue "
        "available in this payload.",
    )

    table = metrics.efficiency_table(df[df["is_club"]])
    if table.empty:
        ui.empty_state(
            "No salary data to rank",
            "The API didn't return a `minimum salary` field, or every value "
            "was zero.",
        )
        return

    st.dataframe(table.head(50), use_container_width=True, hide_index=True)
    ui.download(table, "ssl_value_rankings.csv")

    if "tpe_unspent" in df.columns:
        ui.section(
            "Unspent TPE",
            "TPE earned minus TPE committed to attributes. Positive means "
            "development still sitting in the bank; negative is normal for "
            "heavily regressed players, whose attributes were bought when "
            "their TPE total was higher.",
        )
        unspent = (
            df[df["is_club"]]
            .nlargest(25, "tpe_unspent")[["name", "team", "class", "tpe",
                                          "tpeused", "tpe_unspent"]]
            .rename(columns={"name": "Player", "team": "Team", "class": "Class",
                             "tpe": "TPE", "tpeused": "TPE used",
                             "tpe_unspent": "Unspent"})
        )
        st.dataframe(unspent, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------


def _nations(df: pd.DataFrame, ctx) -> None:
    if "nationality" not in df.columns:
        ui.empty_state(
            "Nationality isn't in this response",
            "The API didn't return a `nationality` field.",
        )
        return

    ui.section("Where the league comes from", "")

    scope = st.radio(
        "Scope", ["Whole league", "One club"], horizontal=True, key="nation_scope"
    )
    frame = df[df["is_club"]]
    if scope == "One club":
        teams = sorted(frame["team"].dropna().astype(str).unique())
        if teams:
            chosen = st.selectbox("Club", teams, key="nation_team")
            frame = frame[frame["team"].astype(str) == chosen]

    if frame.empty:
        ui.empty_state("No players in scope", "Pick another club.")
        return

    counts = (
        frame.groupby("nationality")
        .agg(Players=("name", "count"), **{"Mean TPE": ("tpe", "mean")})
        .round(0).reset_index()
        .rename(columns={"nationality": "Nationality"})
        .sort_values("Players", ascending=False)
    )

    left, right = st.columns([3, 2])
    with left:
        fig = px.bar(
            counts.head(20).sort_values("Players"),
            x="Players", y="Nationality", orientation="h",
            title="Players by nationality",
            color="Players", color_continuous_scale=config.RAMP,
        )
        fig.update_layout(height=max(360, 24 * min(20, len(counts)) + 120),
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.dataframe(counts, use_container_width=True, hide_index=True)

    if "region" in frame.columns:
        ui.section("By region", "")
        regions = (
            frame.groupby("region")
            .agg(Players=("name", "count"), **{"Mean TPE": ("tpe", "mean")})
            .round(0).reset_index()
            .rename(columns={"region": "Region"})
            .sort_values("Players", ascending=False)
        )
        st.dataframe(regions, use_container_width=True, hide_index=True)
        ui.download(regions, "ssl_regions.csv")
