"""
TPE projection.

Two halves, with very different confidence levels:

  Regression is exact. The rulebook fixes it entirely — see REGRESSION_SCHEDULE
  in config. Nothing here is estimated.

  Earning is measured, not assumed. Each player's rate comes from their actual
  logged TPE events in cache/tpe_by_season.csv, averaged over recent complete
  seasons. Earlier drafts of this feature fitted a single constant rate to a
  career and got the peak a season late, because a career's earnings are not
  flat — training camp alone pays 24 a season early and 6 late.

The one thing worth internalising: peak is a plateau at career season 8 and the
cliff is season 9, and that holds at every effort level, because TPE scales with
earnings so the ratio between them doesn't move. Effort sets how high you peak,
never when.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd

import config


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def career_season(current_season: int, draft_class: float | int) -> int:
    """
    Which season of their career a player is in, 1-indexed.

    The rulebook's regression table is keyed on this, not on seasons elapsed —
    a player drafted in S13 is in career season 8 during S20, and season 8 is
    the first that regresses.
    """
    try:
        return int(current_season) - int(draft_class) + 1
    except (TypeError, ValueError):
        return 0


def regression_rate(season_number: int) -> float:
    """Fraction of TPE lost at the end of the given career season."""
    if season_number < config.REGRESSION_FIRST_SEASON:
        return 0.0
    return config.REGRESSION_SCHEDULE.get(season_number, config.REGRESSION_MAX)


def training_camp(season_number: int) -> int:
    """Training camp payout, which steps down as a career progresses."""
    for limit, value in config.TRAINING_CAMP_BANDS:
        if season_number <= limit:
            return value
    return config.TRAINING_CAMP_DEFAULT


def theoretical_max_season() -> int:
    """
    Ceiling on weekly earnings alone: one Activity Check and one PT per week.

    Used only to sanity-check measured rates; capped tasks and predictions sit
    on top of this, so it is a floor for the true ceiling rather than the
    ceiling itself.
    """
    return config.WEEKS_PER_SEASON * (config.AC_PER_WEEK + config.PT_PER_WEEK)


# ---------------------------------------------------------------------------
# Measured earning rates
# ---------------------------------------------------------------------------


@dataclass
class RateTable:
    """Per-player earning rates measured from the history cache."""

    by_name: dict[str, float]
    window: int
    league_median: float
    current_season: int
    generated_at: str | None
    seasons_covered: dict[str, int]

    def rate_for(self, name: str, fallback: float | None = None) -> float:
        return self.by_name.get(name, fallback if fallback is not None
                                else self.league_median)

    def is_measured(self, name: str) -> bool:
        return name in self.by_name


def measure_rates(
    history: pd.DataFrame,
    current_season: int,
    window: int = 2,
    generated_at: str | None = None,
) -> RateTable:
    """
    Average TPE earned per complete season, per player.

    The current season is excluded because it is partial — including it would
    make every player look like they had collapsed. `window` is how many
    complete seasons back to average over: short reacts quickly to someone
    changing their habits, long is steadier.
    """
    if history.empty:
        return RateTable({}, window, 0.0, current_season, generated_at, {})

    complete = history[history["season"] < current_season].copy()
    if complete.empty:
        return RateTable({}, window, 0.0, current_season, generated_at, {})

    cutoff = current_season - window
    recent = complete[complete["season"] >= cutoff]
    # A player who joined inside the window still gets a fair average: we divide
    # by the seasons they actually have, not by the window length.
    grouped = recent.groupby("name")["earned"]
    rates = (grouped.sum() / grouped.count()).round(1)
    counts = recent.groupby("name")["season"].nunique()

    rates = rates[rates.notna()]
    median = float(rates.median()) if len(rates) else 0.0

    return RateTable(
        by_name={str(k): float(v) for k, v in rates.items()},
        window=window,
        league_median=median,
        current_season=current_season,
        generated_at=generated_at,
        seasons_covered={str(k): int(v) for k, v in counts.items()},
    )


# ---------------------------------------------------------------------------
# Single-player projection
# ---------------------------------------------------------------------------


def project_player(
    tpe: float,
    draft_class: int,
    rate: float,
    current_season: int,
    horizon: int = 5,
) -> pd.DataFrame:
    """
    Roll one player forward.

    Order within a season matters and follows the league's: a season's earnings
    accrue first, then regression is applied at the turn against the resulting
    total. The regression post states earnings up to the deadline are included
    in the calculation, which is what this reproduces.

    `rate` is held fixed for the whole horizon by design. One known consequence:
    a measured rate already contains whatever training camp the player drew in
    those seasons, and camp steps down from 24 to 6 across a career, so a young
    player's projection carries up to ~18 TPE per season of optimism. That is
    under a tenth of a typical rate, and correcting it would mean no longer
    projecting at the rate actually measured.
    """
    rows = []
    value = float(tpe)
    for step in range(horizon + 1):
        season = current_season + step
        number = career_season(season, draft_class)
        if step:
            value += rate
            loss = value * regression_rate(number)
            value -= loss
        else:
            loss = 0.0
        rows.append({
            "Season": f"S{season}",
            "season_num": season,
            "Career season": number,
            "TPE": round(value, 1),
            "Regression": f"{regression_rate(number):.0%}" if number >= config.REGRESSION_FIRST_SEASON else "—",
            "Lost": round(loss, 1),
        })
    return pd.DataFrame(rows)


def peak_summary(
    tpe: float, draft_class: int, rate: float, current_season: int
) -> dict:
    """
    Where this player tops out, and how long they stay useful.

    Looks far enough ahead to find the peak even for a brand-new player, so the
    horizon here is deliberately longer than the dashboard's display window.
    """
    number_now = career_season(current_season, draft_class)
    path = project_player(tpe, draft_class, rate, current_season, horizon=18)

    best = path.loc[path["TPE"].idxmax()]
    peak_season = int(best["season_num"])
    peak_value = float(best["TPE"])

    # "Useful life" = seasons until they fall below the current league median,
    # which is a more honest retirement signal than an arbitrary TPE floor.
    return {
        "career_season": number_now,
        "peak_season": peak_season,
        "peak_tpe": peak_value,
        "peak_career_season": career_season(peak_season, draft_class),
        "at_peak": peak_season <= current_season,
        "seasons_to_peak": max(0, peak_season - current_season),
        "current_regression": regression_rate(number_now),
        "next_regression": regression_rate(number_now + 1),
        "path": path,
    }


def seasons_until_below(path: pd.DataFrame, threshold: float) -> int | None:
    """First projected season where TPE drops under `threshold`."""
    below = path[path["TPE"] < threshold]
    if below.empty:
        return None
    return int(below.iloc[0]["season_num"])


# ---------------------------------------------------------------------------
# Organisation projection
# ---------------------------------------------------------------------------


@dataclass
class OrgAssumptions:
    horizon: int = 5
    attrition: float = 0.12          # chance an active user walks, per season
    attrition_age_factor: float = 0.12   # ...rising this much per season past 6
    draftees_per_season: int = 2
    draftee_entry_tpe: int = 420     # 250 start + one academy season
    retiring_is_certain: bool = True
    trials: int = 300


def project_org(
    squad: pd.DataFrame,
    rates: RateTable,
    current_season: int,
    assumptions: OrgAssumptions,
    seed: int | None = 7,
) -> pd.DataFrame:
    """
    Simulate an organisation's Major XI over the horizon.

    Every season: players earn and regress, leavers drop out, draftees arrive,
    and the Major XI is re-picked as the top 11 of the whole org pool — which is
    how promotion from the Minor falls out without needing a rule of its own.

    Returns one row per projected season with median and 10th/90th percentile
    XI averages across `trials` Monte Carlo runs.
    """
    if squad.empty:
        return pd.DataFrame()

    rng = random.Random(seed)

    base = []
    for _, player in squad.iterrows():
        name = str(player["name"])
        live = not bool(player.get("user_inactive", False))
        base.append({
            "name": name,
            "tpe": float(player["tpe"]),
            "cls": int(player["season_num"]) if pd.notna(player.get("season_num")) else current_season,
            # An inactive user earns nothing going forward. Their TPE is frozen
            # and then eaten by regression, which is exactly what happens.
            "rate": rates.rate_for(name) if live else 0.0,
            "live": live,
            "retiring": bool(player.get("retiring", False)),
        })

    runs: list[list[float]] = []
    for _ in range(assumptions.trials):
        pool = [dict(p) for p in base]
        traj = []
        for step in range(assumptions.horizon + 1):
            season = current_season + step
            if step:
                survivors = []
                for p in pool:
                    number = career_season(season, p["cls"])
                    # Flagged retiring means gone next season, no dice roll.
                    if assumptions.retiring_is_certain and p["retiring"] and step == 1:
                        continue
                    if p["live"]:
                        hazard = assumptions.attrition * (
                            1 + assumptions.attrition_age_factor * max(0, number - 7)
                        )
                        if rng.random() < hazard:
                            p["live"] = False
                            p["rate"] = 0.0
                    p["tpe"] += p["rate"]
                    p["tpe"] -= p["tpe"] * regression_rate(number)
                    # Career over once regression has hollowed them out.
                    if number <= config.MAX_CAREER_SEASON:
                        survivors.append(p)
                pool = survivors
                for _d in range(assumptions.draftees_per_season):
                    pool.append({
                        "name": f"S{season} draftee",
                        "tpe": float(assumptions.draftee_entry_tpe),
                        "cls": season,
                        "rate": rates.league_median,
                        "live": True,
                        "retiring": False,
                    })
            xi = sorted(pool, key=lambda p: -p["tpe"])[:11]
            traj.append(sum(p["tpe"] for p in xi) / 11 if xi else 0.0)
        runs.append(traj)

    rows = []
    for step in range(assumptions.horizon + 1):
        values = sorted(run[step] for run in runs)
        n = len(values)
        rows.append({
            "Season": f"S{current_season + step}",
            "season_num": current_season + step,
            "Median": round(values[n // 2], 1),
            "Low": round(values[int(0.10 * n)], 1),
            "High": round(values[min(n - 1, int(0.90 * n))], 1),
        })
    return pd.DataFrame(rows)


def trajectory_verdict(projection: pd.DataFrame) -> tuple[str, str]:
    """A one-line read on where an org is heading."""
    if projection.empty or len(projection) < 2:
        return "Unknown", "Not enough data to project."

    start = projection.iloc[0]["Median"]
    end = projection.iloc[-1]["Median"]
    peak_row = projection.loc[projection["Median"].idxmax()]
    peak_season = peak_row["Season"]
    change = end - start

    if peak_row["season_num"] == projection.iloc[0]["season_num"]:
        return "Past peak", (
            f"Already at the high point. Down {abs(change):,.0f} TPE by "
            f"{projection.iloc[-1]['Season']} on the current core."
        )
    if peak_row["season_num"] == projection.iloc[-1]["season_num"]:
        return "Rising", (
            f"Still climbing at the end of the window — up {change:,.0f} TPE, "
            "with the peak beyond the horizon."
        )
    return "Peaks mid-window", (
        f"Tops out in {peak_season} at {peak_row['Median']:,.0f}, then falls to "
        f"{end:,.0f} by {projection.iloc[-1]['Season']}."
    )
