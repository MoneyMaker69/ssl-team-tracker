"""
Analytics for the SSL Team Tracker.

The important distinction in this module, and the one the previous version got
wrong, is between two different questions:

  "How many midfielders does this club have?"
      Answered from `position`, the player's single declared primary position.
      Every player counts exactly once, so groups sum to the squad total.

  "How many players *could* line up at CM?"
      Answered from the `pos_*` familiarity columns, which overlap heavily — a
      player can be 20 at ST and 20 at CD at the same time. Any view built on
      these is labelled as coverage, never as a squad breakdown.
"""

from __future__ import annotations

import pandas as pd

import config


# ---------------------------------------------------------------------------
# Squad composition (mutually exclusive)
# ---------------------------------------------------------------------------


def group_summary(df: pd.DataFrame, metric: str = "Average") -> pd.DataFrame:
    """
    Squad breakdown by primary position group.

    Because grouping is on `position`, the Players column sums to the squad
    size exactly — unlike a familiarity-threshold count.
    """
    agg = "mean" if metric == "Average" else "sum"
    rows = []
    for group in config.GROUP_ORDER + ["Unclassified"]:
        subset = df[df["primary_group"] == group]
        if subset.empty and group == "Unclassified":
            continue
        rows.append({
            "Group": group,
            "Players": len(subset),
            f"{metric} TPE": round(
                float(getattr(subset["tpe"], agg)()) if not subset.empty else 0.0, 1
            ),
            "Top TPE": int(subset["tpe"].max()) if not subset.empty else 0,
        })
    return pd.DataFrame(rows)


def entity_matrix(df: pd.DataFrame, group_col: str, metric: str = "Average") -> pd.DataFrame:
    """One row per team/org, one column per position group. Rows are additive."""
    agg = "mean" if metric == "Average" else "sum"
    rows = []
    for entity, subset in df.groupby(group_col, dropna=False):
        row: dict[str, object] = {"Entity": entity, "Players": len(subset)}
        row["Overall TPE"] = round(float(getattr(subset["tpe"], agg)()), 1)
        for group in config.GROUP_ORDER:
            members = subset[subset["primary_group"] == group]
            row[group] = round(
                float(getattr(members["tpe"], agg)()) if not members.empty else 0.0, 1
            )
            row[f"{group} n"] = len(members)
        rows.append(row)

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("Overall TPE", ascending=False).reset_index(drop=True)
    return frame


def coverage_matrix(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    How many players each entity could field at each of the 14 positions.

    Rows deliberately do NOT sum to squad size: this counts versatility, and a
    single player legitimately appears in several columns.
    """
    rows = []
    for entity, subset in df.groupby(group_col, dropna=False):
        row: dict[str, object] = {"Entity": entity, "Squad": len(subset)}
        for label, col in config.POSITION_COLUMNS.items():
            row[label] = int((subset[col] >= config.FAMILIARITY_THRESHOLD).sum())
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("Squad", ascending=False).reset_index(drop=True)
    return frame


# ---------------------------------------------------------------------------
# Best XI
# ---------------------------------------------------------------------------


def _max_weight_assignment(
    eligibility: list[list[bool]], n_slots: int
) -> dict[int, int]:
    """
    Assign the highest-TPE players possible to formation slots.

    `eligibility[p][s]` says whether player p (already sorted by TPE, highest
    first) can fill slot s. Players are offered to the matching in descending
    TPE order and admitted via an augmenting path, which never displaces anyone
    already matched — it only reshuffles them. Taking candidates greedily in
    weight order under that rule yields the maximum-TPE valid XI, not merely a
    workable one.

    Returns {slot index: player index}.
    """
    slot_to_player: dict[int, int] = {}

    def try_place(player: int, seen: set[int]) -> bool:
        for slot in range(n_slots):
            if not eligibility[player][slot] or slot in seen:
                continue
            seen.add(slot)
            occupant = slot_to_player.get(slot)
            if occupant is None or try_place(occupant, seen):
                slot_to_player[slot] = player
                return True
        return False

    for player in range(len(eligibility)):
        if len(slot_to_player) == n_slots:
            break
        try_place(player, set())

    return slot_to_player


def best_xi(
    df: pd.DataFrame, formation: str = config.DEFAULT_FORMATION
) -> tuple[pd.DataFrame, list[str]]:
    """
    Pick a formation-respecting best XI.

    Returns the eleven in formation order plus a list of warnings (slots that
    had to be filled by someone out of position).
    """
    slots = config.FORMATIONS.get(formation, config.FORMATIONS[config.DEFAULT_FORMATION])
    warnings: list[str] = []

    if df.empty:
        return pd.DataFrame(), ["No players available for this selection."]

    pool = df.sort_values("tpe", ascending=False).reset_index(drop=True)

    eligibility = [
        [
            float(pool.at[p, col]) >= config.FAMILIARITY_THRESHOLD
            for _, col in slots
        ]
        for p in pool.index
    ]

    assignment = _max_weight_assignment(eligibility, len(slots))

    used = set(assignment.values())
    spare = [p for p in pool.index if p not in used]

    rows = []
    for slot_idx, (label, col) in enumerate(slots):
        player_idx = assignment.get(slot_idx)
        in_position = True
        if player_idx is None:
            # Nobody in the squad is competent here. Rather than leave the slot
            # blank, fill it with the best player left and say so plainly.
            if not spare:
                warnings.append(f"{label}: no player available — squad too small.")
                continue
            player_idx = spare.pop(0)
            in_position = False
            warnings.append(
                f"{label}: no one is rated {config.FAMILIARITY_THRESHOLD}+ here. "
                f"{pool.at[player_idx, 'name']} is filling in out of position."
            )
        player = pool.loc[player_idx]
        rows.append({
            "Slot": label,
            "Player": player["name"],
            "Nat. position": player["position"],
            "TPE": int(player["tpe"]),
            "Familiarity": int(player[col]),
            "Class": player["class"],
            "In position": in_position,
            "At risk": bool(player.get("at_risk", False)),
        })

    return pd.DataFrame(rows), warnings


def top_n_by_tpe(df: pd.DataFrame, group_col: str, n: int = 11) -> pd.DataFrame:
    """
    The naive filter, kept but honestly named.

    This ignores position entirely and can plausibly return eleven strikers. It
    remains useful as a raw-quality measure, which is why it stayed.
    """
    return (
        df.sort_values("tpe", ascending=False)
        .groupby(group_col, dropna=False)
        .head(n)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------


def positional_gaps(
    squad: pd.DataFrame, formation: str = config.DEFAULT_FORMATION
) -> pd.DataFrame:
    """
    Compare cover available at each position against what the formation needs.

    'Cover' counts everyone rated 15+ there, so it is generous by design — if a
    club is short even on this measure, it is genuinely short.
    """
    slots = config.FORMATIONS.get(formation, config.FORMATIONS[config.DEFAULT_FORMATION])

    required: dict[str, int] = {}
    for label, _ in slots:
        required[label] = required.get(label, 0) + 1

    rows = []
    for label, col in config.POSITION_COLUMNS.items():
        need = required.get(label, 0)
        cover = int((squad[col] >= config.FAMILIARITY_THRESHOLD).sum())
        natural = int((squad[col] >= config.FAMILIARITY_NATURAL).sum())
        best = squad.loc[squad[col] >= config.FAMILIARITY_THRESHOLD, "tpe"]
        if need == 0:
            verdict = "Not used in this formation"
        elif cover < need:
            verdict = f"Short — needs {need}, has {cover}"
        elif cover == need:
            verdict = "No cover — one injury deep"
        elif natural < need:
            verdict = "Covered, but nobody natural here"
        else:
            verdict = "Healthy"
        rows.append({
            "Position": label,
            "Needed": need,
            "Can play (15+)": cover,
            "Natural (20)": natural,
            "Best TPE": int(best.max()) if not best.empty else 0,
            "Verdict": verdict,
        })

    frame = pd.DataFrame(rows)
    severity = {
        "Short": 0, "No cover": 1, "Covered,": 2, "Healthy": 3,
        "Not used": 4,
    }
    frame["_sort"] = frame["Verdict"].map(
        lambda v: next((s for k, s in severity.items() if v.startswith(k)), 5)
    )
    return frame.sort_values(["_sort", "Needed"], ascending=[True, False]).drop(
        columns="_sort"
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Value and efficiency
# ---------------------------------------------------------------------------


def efficiency_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Value-for-money ranking.

    The API exposes no actual contract value, so this uses `minimum salary` —
    the floor a player must be paid — as the cost basis. TPE per unit of that
    floor answers "how much quality am I obliged to pay for", which is the
    closest honest analogue to value for money available in this payload.
    """
    if "minimum salary" not in df.columns:
        return pd.DataFrame()

    table = df[df["minimum salary"] > 0].copy()
    if table.empty:
        return pd.DataFrame()

    table["TPE per salary unit"] = (
        table["tpe"] / table["minimum salary"] * 1_000_000
    ).round(1)

    columns = {
        "name": "Player", "team": "Team", "position": "Pos", "class": "Class",
        "tpe": "TPE", "minimum salary": "Min salary",
        "TPE per salary unit": "TPE per salary unit",
    }
    available = {k: v for k, v in columns.items() if k in table.columns}
    return (
        table[list(available)]
        .rename(columns=available)
        .sort_values("TPE per salary unit", ascending=False)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Auto-generated insights
# ---------------------------------------------------------------------------


def league_insights(df: pd.DataFrame, group_col: str) -> list[tuple[str, str]]:
    """A handful of one-line findings for the top of the overview."""
    insights: list[tuple[str, str]] = []
    if df.empty:
        return insights

    by_entity = df.groupby(group_col, dropna=False)

    strongest = by_entity["tpe"].mean().sort_values(ascending=False)
    if len(strongest):
        insights.append((
            "Strongest squad by average TPE",
            f"{strongest.index[0]} — {strongest.iloc[0]:,.0f} average across "
            f"{int(by_entity.size()[strongest.index[0]])} players",
        ))

    ages = by_entity["season_num"].mean().dropna().sort_values(ascending=False)
    if len(ages):
        insights.append((
            "Youngest roster",
            f"{ages.index[0]} — mean draft class S{ages.iloc[0]:.1f}",
        ))
        insights.append((
            "Most veteran roster",
            f"{ages.index[-1]} — mean draft class S{ages.iloc[-1]:.1f}",
        ))

    if "at_risk" in df.columns and df["at_risk"].any():
        risk = (
            df[df["at_risk"]].groupby(group_col)["tpe"].sum().sort_values(ascending=False)
        )
        if len(risk):
            insights.append((
                "Most TPE tied up in inactive or retiring players",
                f"{risk.index[0]} — {risk.iloc[0]:,.0f} TPE across "
                f"{int(df[df['at_risk']].groupby(group_col).size()[risk.index[0]])} players",
            ))

    depth = by_entity.size().sort_values()
    if len(depth):
        insights.append((
            "Thinnest squad",
            f"{depth.index[0]} — {int(depth.iloc[0])} players on the books",
        ))

    keepers = df[df["is_keeper"]].groupby(group_col).size()
    all_entities = set(by_entity.groups)
    keeperless = sorted(all_entities - set(keepers.index))
    if keeperless:
        insights.append((
            "No goalkeeper on the roster",
            ", ".join(str(k) for k in keeperless),
        ))

    return insights
