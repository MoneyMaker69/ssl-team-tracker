"""
Offline checks for the parts of the app that don't need Streamlit or a network.

Run with:  python test_offline.py
Exercises normalisation, the Best XI solver, gap analysis and the position
taxonomy against a fixture built from real getAllPlayers records.
"""

import sys

import pandas as pd

import config
import data
import metrics

FAIL = []


def check(label, condition, detail=""):
    status = "pass" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAIL.append(label)


def make_player(name, position, team, org, affiliate, tpe, cls, **overrides):
    row = {
        "name": name, "position": position, "team": team,
        "organization": org, "affiliate": affiliate, "tpe": tpe, "class": cls,
        "bankBalance": 1_000_000, "minimum salary": 3_000_000,
        "timesregressed": 2, "userStatus": "Active", "playerStatus": "Active",
        "nationality": "Zambia", "region": "East Africa", "tpeused": 350,
        "tpebank": 5, "purchasedTPE": 0, "traits": "NO TRAITS",
        "username": name.lower().replace(" ", ""), "pid": 1,
        "created": 19849, "height": 72, "weight": 180,
        "left foot": 20, "right foot": 10,
    }
    for col in config.POSITION_COLUMNS.values():
        row[col] = 0
    natural = config.POSITION_COLUMNS.get(position)
    if natural:
        row[natural] = 20
    for attr in config.OUTFIELD_ATTRIBUTES + config.GK_ATTRIBUTES:
        row[attr] = 10
    row.update(overrides)
    return row


def build_fixture():
    rows = []
    # A full, well-shaped squad.
    shape = ["GK", "GK", "LD", "CD", "CD", "CD", "RD", "CDM", "CM", "CM",
             "LM", "LAM", "RAM", "ST", "ST"]
    for i, pos in enumerate(shape):
        rows.append(make_player(
            f"Alpha {i}", pos, "Reykjavik United", "Reykjavik United", 1,
            1000 + i * 50, "S18",
        ))

    # An unbalanced squad: eleven strikers plus one keeper. This is the case
    # that used to produce a "Starting XI" of eleven forwards.
    for i in range(11):
        rows.append(make_player(
            f"Striker {i}", "ST", "Hollywood FC", "Hollywood FC", 1,
            1500 + i, "S18",
        ))
    rows.append(make_player(
        "Lone Keeper", "GK", "Hollywood FC", "Hollywood FC", 1, 400, "S17"
    ))

    # A minor side of a brand-new organisation absent from the old hardcoded
    # ORG_MAPPING — this is exactly the row that used to be deleted.
    rows.append(make_player(
        "New Signing", "CM", "CD Alfama", "ASC Yumboes de Dakar", 2, 795, "S17"
    ))
    # Free agent.
    rows.append(make_player(
        "Free Bird", "ST", "Free Agent", "Free Agent", 1, 660, "S17"
    ))
    # Multi-position player: counts once by primary position, several times in
    # coverage.
    rows.append(make_player(
        "Utility Man", "ST", "Reykjavik United", "Reykjavik United", 1,
        1590, "S17", pos_st=20, pos_lam=20, pos_ram=20, pos_cd=20,
    ))
    # Inactive user holding a big TPE total, and a retiring player.
    rows.append(make_player(
        "Ghost Star", "CD", "Reykjavik United", "Reykjavik United", 1,
        1703, "S18", userStatus="Inactive",
    ))
    rows.append(make_player(
        "Old Boy", "CM", "Reykjavik United", "Reykjavik United", 1,
        900, "S13", playerStatus="Retiring", timesregressed=7,
        created=1722269719.7245,
    ))
    # Unparseable class, to prove it warns rather than vanishing.
    rows.append(make_player(
        "Mystery Man", "CM", "Reykjavik United", "Reykjavik United", 1,
        500, "rookie",
    ))
    return pd.DataFrame(rows)


def normalise(df):
    notices = []
    for col in config.POSITION_COLUMNS.values():
        if col not in df.columns:
            df[col] = 0
    data._coerce_numeric(df, ["tpe", "bankBalance", "tpeused", "timesregressed",
                              "minimum salary"])
    data._derive_organisation(df, notices)
    data._derive_season(df, notices)
    data._derive_flags(df)
    df["created_at"] = df["created"].map(data._normalise_created)
    df["tpe_unspent"] = df["tpe"] - df["tpeused"]
    return df, notices


def main():
    df = build_fixture()
    df, notices = normalise(df)

    print("\nNormalisation")
    check("no rows dropped", len(df) == 33, f"{len(df)} rows in")
    check("new org derived from API, not a hardcoded dict",
          set(df["org"]) >= {"ASC Yumboes de Dakar"},
          "CD Alfama's parent org resolved")
    check("CD Alfama survives (it did not in the old version)",
          "CD Alfama" in set(df["team"]))
    check("affiliate 1/2 maps to Major/Minor",
          set(df["tier"]) == {"Major", "Minor"})
    check("free agents flagged as non-club",
          not df.loc[df["team"] == "Free Agent", "is_club"].any())
    check("unparseable class warns rather than dropping the row",
          any("draft class" in n.title for n in notices)
          and "Mystery Man" in set(df["name"]))
    check("mixed-format `created` normalised both ways",
          df.loc[df["name"] == "Old Boy", "created_at"].iloc[0].year == 2024
          and df.loc[df["name"] == "Alpha 0", "created_at"].iloc[0].year == 2024,
          "day-serial and unix seconds both land in 2024")

    print("\nPosition taxonomy")
    rey = df[df["team"] == "Reykjavik United"]
    summary = metrics.group_summary(rey)
    check("primary groups sum to squad size exactly once",
          int(summary["Players"].sum()) == len(rey),
          f"{int(summary['Players'].sum())} == {len(rey)}")

    coverage = metrics.coverage_matrix(rey, "team")
    total_coverage = sum(int(coverage.iloc[0][p]) for p in config.POSITION_COLUMNS)
    check("coverage deliberately overlaps (versatility, not headcount)",
          total_coverage > len(rey),
          f"{total_coverage} slots covered by {len(rey)} players")

    print("\nBest XI")
    hollywood = df[df["team"] == "Hollywood FC"]
    naive = metrics.top_n_by_tpe(hollywood, "team", 11)
    check("the naive top-11 really does return eleven strikers",
          (naive["position"] == "ST").sum() == 11,
          "which is why it is no longer called 'Starting XI'")

    xi, warnings = metrics.best_xi(hollywood, "4-3-3")
    check("best XI fills all eleven slots", len(xi) == 11, f"{len(xi)} slots")
    check("best XI puts the keeper in goal",
          xi.loc[xi["Slot"] == "GK", "Player"].iloc[0] == "Lone Keeper")
    check("out-of-position fills are reported, not hidden",
          len(warnings) > 0 and not xi["In position"].all(),
          f"{len(warnings)} warning(s)")

    xi_rey, warn_rey = metrics.best_xi(rey, "4-3-3")
    check("a balanced squad needs no out-of-position fills",
          xi_rey["In position"].all(), f"{len(warn_rey)} warning(s)")
    check("no player is used twice in one XI",
          xi_rey["Player"].nunique() == len(xi_rey))
    check("solver takes the strongest legal eleven",
          xi_rey["TPE"].sum() >= 11000, f"{int(xi_rey['TPE'].sum()):,} TPE")

    print("\nGaps")
    gaps = metrics.positional_gaps(hollywood, "4-3-3")
    short = gaps[gaps["Verdict"].str.startswith("Short")]
    check("gap analysis calls out the missing defence",
          {"CD", "LD", "RD"} <= set(short["Position"]),
          f"flagged: {', '.join(short['Position'].tolist())}")
    check("worst problems sort to the top",
          gaps.iloc[0]["Verdict"].startswith(("Short", "No cover")))

    print("\nMetrics")
    clubs = df[df["is_club"]]
    check("free agents excluded from club analytics",
          "Free Agent" not in set(clubs["team"]))
    risk = clubs[clubs["at_risk"]]
    check("inactive and retiring players both flagged",
          {"Ghost Star", "Old Boy"} <= set(risk["name"]),
          f"{len(risk)} at risk")
    efficiency = metrics.efficiency_table(clubs)
    check("value table ranks on TPE per salary unit",
          not efficiency.empty
          and efficiency["TPE per salary unit"].is_monotonic_decreasing)
    insights = metrics.league_insights(clubs, "team")
    check("insights generated", len(insights) >= 4, f"{len(insights)} findings")

    matrix = metrics.entity_matrix(clubs, "team")
    check("entity matrix covers every club",
          set(matrix["Entity"]) == set(clubs["team"]),
          f"{len(matrix)} clubs")

    print("\nSheet matching")
    matched, fuzzy, unmatched = data.match_sheet_teams(
        pd.DataFrame({
            "team_sheet": ["Hollywood Football Club", "Reykjavik United",
                           "Shanghai Dragons", "Defunct Rovers"],
            "season": [17, 17, 17, 12],
            "value": [1500, 1400, 1300, 900],
        }),
        sorted(clubs["team"].unique()),
    )
    check("explicit override applied",
          "Hollywood FC" in set(matched["team"]))
    check("unmatched sheet names kept and reported, not dropped",
          "Defunct Rovers" in unmatched
          and "Defunct Rovers" in set(matched["team"]),
          f"unmatched: {unmatched}")

    print()
    if FAIL:
        print(f"{len(FAIL)} check(s) failed: " + "; ".join(FAIL))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
