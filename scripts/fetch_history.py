#!/usr/bin/env python3
"""
Build the TPE history cache.

Run by .github/workflows/update-tpe-history.yml once a week. Pulls every active
player's full TPE event log, buckets it into seasons, and writes two small files
into cache/ that the dashboard reads instead of ever calling the history
endpoint itself.

Run locally the same way:  python scripts/fetch_history.py

Why a cache at all: getTPEhistory is one request per player, so a full refresh is
300+ calls and ~15 MB. That can't happen on a page load, and Streamlit Cloud
wipes its filesystem on every reboot, so anything written at runtime would be
rebuilt constantly. Committing the result to the repo makes it instant to read
and gives you a versioned archive of league history for free.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://api.simulationsoccer.com"
PLAYERS_URL = f"{API}/player/getAllPlayers"
HISTORY_URL = f"{API}/player/getTPEhistory"
SCHEDULE_URL = f"{API}/index/schedule"
CURRENT_SEASON_URL = f"{API}/admin/getCurrentSeason"

OUT_DIR = Path(__file__).resolve().parent.parent / "cache"
SEASONS_CSV = OUT_DIR / "tpe_by_season.csv"
META_JSON = OUT_DIR / "history_meta.json"

TIMEOUT = 30
RETRIES = 3
PAUSE = 0.15          # gentle on the API; ~50s for a full run
SEASON_LEAD_DAYS = 7  # matchday 1 is ~a week after a season actually opens

# A genuine regression looks exactly like "S26 Regression". Three things in the
# feed would fool a substring match:
#   "S21 Regression Adjustment"  +100  — a correction, and positive
#   "Weekly PT #214 (Regressed)"   +4  — an ordinary earning, oddly labelled
#   "Weekly PT #207 Correction"    -6  — negative, but not regression
REGRESSION_RE = re.compile(r"^S\d+\s+Regression$", re.IGNORECASE)

# The portal migration seeded everyone with a lump "Initial TPE" entry. It is a
# snapshot of TPE already held, not TPE earned, and must never count as earnings.
EXCLUDED_SOURCES = {"initial tpe"}


def get(url: str, params: dict | None = None):
    """GET with retries. Returns None rather than raising, so one bad player
    can't abort a whole run."""
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == RETRIES - 1:
                print(f"    failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
    return None


def current_season() -> int | None:
    payload = get(CURRENT_SEASON_URL)
    if payload is None:
        return None
    if isinstance(payload, dict):
        for key in ("season", "Season", "currentSeason", "current_season"):
            if key in payload:
                try:
                    return int(payload[key])
                except (TypeError, ValueError):
                    pass
        # Single-key object of unknown name
        if len(payload) == 1:
            try:
                return int(next(iter(payload.values())))
            except (TypeError, ValueError):
                return None
    try:
        return int(payload)
    except (TypeError, ValueError):
        return None


def season_boundaries(latest: int) -> dict[int, str]:
    """
    Start date per season, taken as the earliest fixture minus a week.

    Matchday 1 falls in week 2 of a season, so the earliest fixture slightly
    postdates the real start. A seven-day lead is enough to put pre-season
    earnings in the right bucket without overlapping the previous season.
    """
    starts: dict[int, str] = {}
    for season in range(1, latest + 1):
        payload = get(SCHEDULE_URL, {"season": season, "league": "ALL"})
        time.sleep(PAUSE)
        if not payload:
            continue
        dates = [row.get("IRLDate") for row in payload if row.get("IRLDate")]
        if not dates:
            continue
        first = datetime.strptime(min(dates), "%Y-%m-%d") - timedelta(days=SEASON_LEAD_DAYS)
        starts[season] = first.strftime("%Y-%m-%d")
        print(f"  S{season}: opens ~{starts[season]}")
    return starts


def build_season_lookup(starts: dict[int, str]):
    ordered = sorted(((datetime.strptime(v, "%Y-%m-%d"), k) for k, v in starts.items()))

    def season_of(when: datetime) -> int | None:
        found = None
        for start, season in ordered:
            if when >= start:
                found = season
            else:
                break
        return found

    return season_of


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    latest = current_season()
    if latest is None:
        print("Could not read the current season; aborting.", file=sys.stderr)
        return 1
    print(f"Current season: S{latest}")

    print("Mapping season boundaries from the schedule endpoint…")
    starts = season_boundaries(latest)
    if not starts:
        print("No season boundaries resolved; aborting.", file=sys.stderr)
        return 1
    season_of = build_season_lookup(starts)

    players = get(PLAYERS_URL, {"active": "true"})
    if not players:
        print("Could not read the player list; aborting.", file=sys.stderr)
        return 1
    print(f"{len(players)} active players to fetch")

    rows: list[dict] = []
    ok = missing = 0

    for i, player in enumerate(players, 1):
        name = str(player.get("name", "")).strip()
        if not name:
            continue
        history = get(f"{HISTORY_URL}?name={quote(name)}")
        time.sleep(PAUSE)

        if not history:
            missing += 1
            print(f"  [{i}/{len(players)}] {name}: no history")
            continue

        earned: dict[int, int] = defaultdict(int)
        regressed: dict[int, int] = defaultdict(int)
        events: dict[int, int] = defaultdict(int)

        for entry in history:
            raw_time = entry.get("Time")
            source = str(entry.get("Source", "")).strip()
            try:
                change = int(entry.get("TPE Change", 0))
                when = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                continue

            season = season_of(when)
            if season is None:
                continue

            if REGRESSION_RE.match(source) and change < 0:
                regressed[season] += change
            elif source.lower() in EXCLUDED_SOURCES:
                continue  # migration snapshot, not earnings
            else:
                earned[season] += change
                events[season] += 1

        for season in sorted(set(earned) | set(regressed)):
            rows.append({
                "name": name,
                "username": str(player.get("username", "")).strip(),
                "season": season,
                "earned": earned.get(season, 0),
                "regression": regressed.get(season, 0),
                "events": events.get(season, 0),
            })
        ok += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(players)}] …{ok} fetched, {missing} missing")

    if not rows:
        print("No history rows produced; refusing to overwrite the cache.",
              file=sys.stderr)
        return 1

    with SEASONS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["name", "username", "season", "earned",
                            "regression", "events"])
        writer.writeheader()
        writer.writerows(rows)

    META_JSON.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_season": latest,
        "season_starts": starts,
        "players_fetched": ok,
        "players_missing": missing,
        "rows": len(rows),
    }, indent=2), encoding="utf-8")

    print(f"\nWrote {len(rows)} rows for {ok} players "
          f"({missing} without history) to {SEASONS_CSV.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
