"""
Loading and normalisation for the SSL Team Tracker.

Two rules govern this module:

1. Nothing is dropped silently. If a row can't be classified it keeps its own
   identity and gets reported through `LoadResult.notices`.
2. Nothing fails silently. Every failure path produces a Notice describing what
   broke and what the app will do about it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import get_close_matches
from typing import Any

import pandas as pd
import requests

import config


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class Notice:
    """A user-visible message. `level` is one of error / warning / info."""

    level: str
    title: str
    detail: str = ""


@dataclass
class LoadResult:
    frame: pd.DataFrame
    fetched_at: datetime
    notices: list[Notice] = field(default_factory=list)
    ok: bool = True

    @property
    def is_empty(self) -> bool:
        return self.frame is None or self.frame.empty


class SchemaError(RuntimeError):
    """Raised when the API response is missing columns the app cannot do without."""


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------


def _coerce_numeric(df: pd.DataFrame, columns: list[str], fill: float = 0.0) -> None:
    """In-place numeric coercion that never raises on unexpected values."""
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(fill)


def _normalise_created(value: Any) -> pd.Timestamp | None:
    """
    `created` arrives in two different formats in the same response.

    Rows created before roughly mid-2024 use a day-serial count (e.g. 19635 =
    days since the Unix epoch). Newer rows use Unix seconds (e.g.
    1722269719.72). Treating them as one type produces dates centuries apart, so
    we branch on magnitude.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    try:
        if num < 100_000:  # day-serial
            return pd.Timestamp("1970-01-01", tz="UTC") + pd.Timedelta(days=num)
        return pd.Timestamp(num, unit="s", tz="UTC")
    except (ValueError, OverflowError, pd.errors.OutOfBoundsDatetime):
        return None


def _derive_organisation(df: pd.DataFrame, notices: list[Notice]) -> None:
    """
    Build the org/tier mapping from the API payload instead of a hardcoded dict.

    Every player carries `organization` (the parent franchise) and `affiliate`
    (1 = Major, 2 = Minor). That is the whole mapping. Teams the app has never
    seen before appear automatically the moment a player is assigned to them.
    """
    df["org"] = df["organization"].fillna("").astype(str).str.strip()
    df["team"] = df["team"].fillna("").astype(str).str.strip()

    # A blank org is not fatal: fall back to the team's own name so the club
    # still appears, and report how many rows needed the fallback.
    missing_org = df["org"].eq("")
    if missing_org.any():
        df.loc[missing_org, "org"] = df.loc[missing_org, "team"]
        affected = sorted(df.loc[missing_org, "team"].unique())
        notices.append(
            Notice(
                "warning",
                f"{len(affected)} team(s) reported no parent organisation",
                "Using the team name as its own organisation: "
                + ", ".join(a or "(blank)" for a in affected),
            )
        )

    df["tier"] = (
        pd.to_numeric(df["affiliate"], errors="coerce")
        .map(config.AFFILIATE_LABELS)
        .fillna("Unclassified")
    )

    unclassified = df["tier"].eq("Unclassified")
    if unclassified.any():
        teams = sorted(df.loc[unclassified, "team"].unique())
        notices.append(
            Notice(
                "warning",
                f"{len(teams)} team(s) have an unrecognised affiliate value",
                "Shown as 'Unclassified' rather than dropped: " + ", ".join(teams),
            )
        )

    # Free agents are a real roster but not a club. Flagged here, filtered by
    # the sidebar, and given their own view.
    df["is_club"] = ~df["team"].isin(config.NON_CLUB_TEAMS)


def _derive_season(df: pd.DataFrame, notices: list[Notice]) -> None:
    """
    Parse the draft class number out of `class`.

    Values look like "S13" ... "S18". There is no dedicated numeric season field
    in the payload, so the regex stays — but a parse failure is now reported
    rather than becoming a silent NaN that quietly drops rows from charts.
    """
    raw = df["class"].astype(str).str.strip()
    df["season_num"] = pd.to_numeric(
        raw.str.extract(r"(\d+)", expand=False), errors="coerce"
    )

    failed = df["season_num"].isna() & raw.ne("") & raw.ne("nan")
    if failed.any():
        samples = sorted(raw[failed].unique())[:5]
        notices.append(
            Notice(
                "warning",
                f"{int(failed.sum())} player(s) have an unparseable draft class",
                "Age-based charts will skip them. Examples: " + ", ".join(samples),
            )
        )


def _derive_flags(df: pd.DataFrame) -> None:
    """Boolean convenience columns used across several views."""
    if "userStatus" in df.columns:
        df["user_inactive"] = (
            df["userStatus"].astype(str).str.strip().str.lower().eq("inactive")
        )
    else:
        df["user_inactive"] = False

    if "playerStatus" in df.columns:
        df["retiring"] = (
            df["playerStatus"].astype(str).str.strip().str.lower().eq("retiring")
        )
    else:
        df["retiring"] = False

    # A roster spot occupied by a high-TPE player whose user has gone inactive
    # is the single most actionable thing a GM can see, so it gets its own flag.
    df["at_risk"] = df["user_inactive"] | df["retiring"]

    df["primary_group"] = (
        df["position"].astype(str).str.strip().str.upper()
        .map(config.POSITION_TO_GROUP)
        .fillna("Unclassified")
    )
    df["is_keeper"] = df["primary_group"].eq("Goalkeeper")


def _validate_schema(df: pd.DataFrame, notices: list[Notice]) -> None:
    missing_required = [c for c in config.REQUIRED_COLUMNS if c not in df.columns]
    if missing_required:
        raise SchemaError(
            "The API response is missing columns this dashboard cannot work "
            "without: " + ", ".join(missing_required) + ". "
            "The API schema has probably changed — check "
            f"{config.PLAYERS_ENDPOINT} and update config.REQUIRED_COLUMNS."
        )

    missing_pos = [c for c in config.POSITION_COLUMNS.values() if c not in df.columns]
    if missing_pos:
        notices.append(
            Notice(
                "error",
                f"{len(missing_pos)} positional familiarity column(s) missing",
                "Best XI and the coverage matrix will treat these as zero: "
                + ", ".join(missing_pos),
            )
        )

    missing_attrs = [
        c for c in config.OUTFIELD_ATTRIBUTES + config.GK_ATTRIBUTES
        if c not in df.columns
    ]
    if missing_attrs:
        notices.append(
            Notice(
                "warning",
                f"{len(missing_attrs)} attribute column(s) missing",
                "Radars will omit them: " + ", ".join(missing_attrs[:12])
                + ("…" if len(missing_attrs) > 12 else ""),
            )
        )

    missing_optional = [c for c in config.OPTIONAL_COLUMNS if c not in df.columns]
    if missing_optional:
        notices.append(
            Notice(
                "info",
                f"{len(missing_optional)} optional field(s) not returned",
                "Related features are hidden: " + ", ".join(missing_optional),
            )
        )


def fetch_players(cache_buster: int = 0) -> LoadResult:
    """
    Fetch and normalise the active player list.

    `cache_buster` exists so the caller can force a real HTTP round-trip by
    changing the argument; it is otherwise unused.
    """
    del cache_buster
    notices: list[Notice] = []
    fetched_at = datetime.now(timezone.utc)

    try:
        response = requests.get(
            config.PLAYERS_ENDPOINT,
            params=config.PLAYERS_PARAMS,
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        return LoadResult(
            pd.DataFrame(), fetched_at, ok=False,
            notices=[Notice(
                "error", "The SSL API did not respond in time",
                f"No answer from {config.PLAYERS_ENDPOINT} within "
                f"{config.REQUEST_TIMEOUT}s. Try Refresh in a moment.",
            )],
        )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        return LoadResult(
            pd.DataFrame(), fetched_at, ok=False,
            notices=[Notice(
                "error", f"The SSL API returned HTTP {status}",
                f"Endpoint: {config.PLAYERS_ENDPOINT}. This is an API-side "
                "problem, not a dashboard one.",
            )],
        )
    except requests.RequestException as exc:
        return LoadResult(
            pd.DataFrame(), fetched_at, ok=False,
            notices=[Notice(
                "error", "Could not reach the SSL API",
                f"{type(exc).__name__}: {exc}",
            )],
        )
    except ValueError as exc:
        return LoadResult(
            pd.DataFrame(), fetched_at, ok=False,
            notices=[Notice(
                "error", "The SSL API returned something that isn't JSON",
                f"{exc}. The endpoint may be behind a maintenance page.",
            )],
        )

    if not isinstance(payload, list) or not payload:
        return LoadResult(
            pd.DataFrame(), fetched_at, ok=False,
            notices=[Notice(
                "error", "The SSL API returned no players",
                "The request succeeded but the payload was empty.",
            )],
        )

    df = pd.DataFrame(payload)

    try:
        _validate_schema(df, notices)
    except SchemaError as exc:
        return LoadResult(
            pd.DataFrame(), fetched_at, ok=False,
            notices=[Notice("error", "Unexpected API schema", str(exc))],
        )

    # Guarantee every familiarity column exists so downstream code can index
    # them without conditionals.
    for col in config.POSITION_COLUMNS.values():
        if col not in df.columns:
            df[col] = 0

    _coerce_numeric(df, ["tpe", "bankBalance", "tpeused", "tpebank",
                         "purchasedTPE", "timesregressed", "minimum salary",
                         "height", "weight", "left foot", "right foot"])
    _coerce_numeric(df, list(config.POSITION_COLUMNS.values()))
    _coerce_numeric(
        df, [c for c in config.OUTFIELD_ATTRIBUTES + config.GK_ATTRIBUTES
             if c in df.columns]
    )

    _derive_organisation(df, notices)
    _derive_season(df, notices)
    _derive_flags(df)

    if "created" in df.columns:
        df["created_at"] = df["created"].map(_normalise_created)

    # TPE earned but not yet spent on attributes. Goes negative for heavily
    # regressed players, whose attributes were bought at a higher TPE total than
    # they now hold — that's meaningful, not a bug, so it isn't clipped.
    if "tpeused" in df.columns:
        df["tpe_unspent"] = df["tpe"] - df["tpeused"]

    unclassified = df["primary_group"].eq("Unclassified")
    if unclassified.any():
        vals = sorted(df.loc[unclassified, "position"].astype(str).unique())
        notices.append(
            Notice(
                "warning",
                f"{int(unclassified.sum())} player(s) have an unrecognised position",
                "Add them to config.POSITION_TO_GROUP. Seen: " + ", ".join(vals),
            )
        )

    return LoadResult(df, fetched_at, notices=notices, ok=True)


# ---------------------------------------------------------------------------
# Organisation directory
# ---------------------------------------------------------------------------


def build_org_directory(df: pd.DataFrame) -> pd.DataFrame:
    """One row per club, with its parent org, tier and headcount."""
    clubs = df[df["is_club"]]
    if clubs.empty:
        return pd.DataFrame(columns=["team", "org", "tier", "players", "total_tpe"])

    directory = (
        clubs.groupby(["team", "org", "tier"], dropna=False)
        .agg(players=("name", "count"), total_tpe=("tpe", "sum"))
        .reset_index()
        .sort_values(["org", "tier", "team"])
    )
    return directory


# ---------------------------------------------------------------------------
# Google Sheet history
# ---------------------------------------------------------------------------


def _normalise(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _find_column(headers: list[str], candidates: list[str]) -> int:
    """Index of the first header matching any candidate label, else -1."""
    normalised = [_normalise(h) for h in headers]
    for candidate in candidates:
        for idx, header in enumerate(normalised):
            if header == candidate or candidate in header:
                return idx
    return -1


def _scan_for_header(raw: pd.DataFrame) -> tuple[int, int, int, int, str] | None:
    """
    Fallback layout detection.

    Scans rows for one containing a recognisable value label plus a team and
    season column. Returns (row, team_idx, season_idx, value_idx, label).
    """
    for row_idx in range(len(raw)):
        cells = [_normalise(c) for c in raw.iloc[row_idx].tolist()]
        for label, aliases in config.SHEET_VALUE_LABELS:
            value_idx = _find_column(cells, aliases)
            if value_idx == -1:
                continue
            team_idx = _find_column(cells, config.SHEET_TEAM_LABELS)
            season_idx = _find_column(cells, config.SHEET_SEASON_LABELS)
            if team_idx != -1 and season_idx != -1:
                return row_idx, team_idx, season_idx, value_idx, label
    return None


def fetch_sheet_history(cache_buster: int = 0) -> tuple[LoadResult, str]:
    """
    Load the historical leaderboard from the published Google Sheet.

    Returns (result, value_label). Every failure mode produces a distinct notice
    so "empty history tab" is never ambiguous.
    """
    del cache_buster
    notices: list[Notice] = []
    fetched_at = datetime.now(timezone.utc)
    url = (
        f"https://docs.google.com/spreadsheets/d/{config.SPREADSHEET_ID}"
        f"/export?format=csv&gid={config.LEADERBOARD_GID}"
    )
    empty = pd.DataFrame(columns=["team_sheet", "team", "season", "value"])

    try:
        raw = pd.read_csv(url, header=None, dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user below
        notices.append(
            Notice(
                "error",
                "Could not read the historical Google Sheet",
                f"{type(exc).__name__}: {exc}. The sheet must be shared as "
                "'anyone with the link can view' for this to work. Current "
                "data is unaffected — only the History view is.",
            )
        )
        return LoadResult(empty, fetched_at, notices, ok=False), "TPE"

    if raw.empty:
        notices.append(
            Notice("error", "The historical Google Sheet is empty",
                   f"Fetched {url} successfully but it contained no rows.")
        )
        return LoadResult(empty, fetched_at, notices, ok=False), "TPE"

    layout = config.SHEET_LAYOUT
    label = "TPE"

    if layout["header_row"] is not None:
        # Pinned layout: named columns, no string-hunting.
        unset = [k for k in ("team_column", "season_column", "value_column")
                 if not layout.get(k)]
        if unset:
            notices.append(
                Notice(
                    "error",
                    "The pinned sheet layout is incomplete",
                    "config.SHEET_LAYOUT sets header_row but leaves "
                    + ", ".join(unset)
                    + " empty. Either fill them in or set header_row back to "
                    "None to fall back to auto-detection.",
                )
            )
            return LoadResult(empty, fetched_at, notices, ok=False), label
        header_row = int(layout["header_row"])
        headers = raw.iloc[header_row].tolist()
        team_idx = _find_column(headers, [_normalise(layout["team_column"])])
        season_idx = _find_column(headers, [_normalise(layout["season_column"])])
        value_idx = _find_column(headers, [_normalise(layout["value_column"])])
        label = str(layout["value_column"])
        if -1 in (team_idx, season_idx, value_idx):
            notices.append(
                Notice(
                    "error",
                    "The pinned sheet layout no longer matches the sheet",
                    f"Row {header_row} does not contain all of "
                    f"{layout['team_column']!r}, {layout['season_column']!r}, "
                    f"{layout['value_column']!r}. Update config.SHEET_LAYOUT.",
                )
            )
            return LoadResult(empty, fetched_at, notices, ok=False), label
    else:
        found = _scan_for_header(raw)
        if found is None:
            notices.append(
                Notice(
                    "error",
                    "Could not find the history table inside the sheet",
                    "Looked for a row containing a team column, a season column "
                    "and one of: "
                    + ", ".join(lbl for lbl, _ in config.SHEET_VALUE_LABELS)
                    + ". If the sheet's headers were renamed, pin the layout in "
                    "config.SHEET_LAYOUT instead of relying on detection.",
                )
            )
            return LoadResult(empty, fetched_at, notices, ok=False), label
        header_row, team_idx, season_idx, value_idx, label = found
        notices.append(
            Notice(
                "info",
                "Sheet layout was auto-detected",
                f"Header found on row {header_row + 1}, reading '{label}'. Pin "
                "this in config.SHEET_LAYOUT to make it stable.",
            )
        )

    body = raw.iloc[header_row + 1:]
    widest = max(team_idx, season_idx, value_idx)
    if body.shape[1] <= widest:
        notices.append(
            Notice("error", "The sheet's history table is narrower than its header",
                   "Detected columns fall outside the data range.")
        )
        return LoadResult(empty, fetched_at, notices, ok=False), label

    history = pd.DataFrame({
        "team_sheet": body.iloc[:, team_idx].astype(str).str.strip(),
        "season": pd.to_numeric(body.iloc[:, season_idx], errors="coerce"),
        "value": pd.to_numeric(
            body.iloc[:, value_idx].astype(str).str.replace(r"[,\s]", "", regex=True),
            errors="coerce",
        ),
    })

    before = len(history)
    history = history[
        history["team_sheet"].ne("")
        & ~history["team_sheet"].str.lower().isin(["team", "nan"])
    ]
    history = history.dropna(subset=["season", "value"])

    if history.empty:
        notices.append(
            Notice(
                "warning",
                "The history table was found but held no usable rows",
                f"{before} row(s) below the header, none with both a numeric "
                "season and a numeric value.",
            )
        )
        return LoadResult(empty, fetched_at, notices, ok=False), label

    return LoadResult(history, fetched_at, notices, ok=True), label


def match_sheet_teams(
    history: pd.DataFrame, api_teams: list[str]
) -> tuple[pd.DataFrame, list[tuple[str, str]], list[str]]:
    """
    Map sheet spellings onto API team names.

    Three passes: explicit override, exact match, then close-match. Returns the
    frame with a `team` column plus the fuzzy matches made (for disclosure) and
    the names that could not be matched at all.
    """
    if history.empty:
        return history.assign(team=pd.Series(dtype=str)), [], []

    lookup = {_normalise(t): t for t in api_teams}
    fuzzy: list[tuple[str, str]] = []
    unmatched: list[str] = []

    def resolve(name: str) -> str:
        if name in config.SHEET_NAME_OVERRIDES:
            return config.SHEET_NAME_OVERRIDES[name]
        key = _normalise(name)
        if key in lookup:
            return lookup[key]
        close = get_close_matches(key, list(lookup), n=1, cutoff=0.72)
        if close:
            resolved = lookup[close[0]]
            fuzzy.append((name, resolved))
            return resolved
        unmatched.append(name)
        return name  # kept under its own name rather than dropped

    resolved = history.copy()
    resolved["team"] = resolved["team_sheet"].map(resolve)

    # De-duplicate the disclosure lists while preserving order.
    fuzzy = list(dict.fromkeys(fuzzy))
    unmatched = list(dict.fromkeys(unmatched))
    return resolved, fuzzy, unmatched


# ---------------------------------------------------------------------------
# Admin: live endpoint probe
# ---------------------------------------------------------------------------


def probe_endpoints(paths: list[str] | None = None) -> pd.DataFrame:
    """
    Try each candidate path and report what answers.

    The point of this is discovery: the published API docs currently 404, so
    rather than guess at what exists, this runs from wherever the app is
    deployed and tells you. Anything returning 200 with JSON is a real endpoint
    that can be promoted into a loader.
    """
    paths = paths or config.CANDIDATE_ENDPOINTS
    rows = []
    for path in paths:
        url = f"{config.API_BASE}{path}"
        started = time.perf_counter()
        try:
            response = requests.get(url, timeout=8)
            elapsed = (time.perf_counter() - started) * 1000
            content_type = response.headers.get("content-type", "")
            shape = ""
            if response.ok and "json" in content_type:
                try:
                    body = response.json()
                    if isinstance(body, list):
                        shape = f"list[{len(body)}]"
                        if body and isinstance(body[0], dict):
                            keys = list(body[0])[:6]
                            shape += " keys: " + ", ".join(keys)
                    elif isinstance(body, dict):
                        shape = "object keys: " + ", ".join(list(body)[:6])
                except ValueError:
                    shape = "unparseable JSON"
            rows.append({
                "Endpoint": path,
                "Status": response.status_code,
                "Type": content_type.split(";")[0] or "—",
                "ms": round(elapsed),
                "Shape": shape or "—",
            })
        except requests.RequestException as exc:
            rows.append({
                "Endpoint": path,
                "Status": "no response",
                "Type": "—",
                "ms": round((time.perf_counter() - started) * 1000),
                "Shape": type(exc).__name__,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TPE history cache
# ---------------------------------------------------------------------------


def load_history_cache() -> tuple[pd.DataFrame, dict, list[Notice]]:
    """
    Read the per-season TPE history written by scripts/fetch_history.py.

    This is a local file, not an API call: getTPEhistory is one request per
    player, so a live refresh would be 300+ calls per page load. The weekly
    GitHub Action keeps the file current and commits it to the repo.
    """
    import json
    from pathlib import Path

    notices: list[Notice] = []
    empty = pd.DataFrame(columns=["name", "username", "season", "earned",
                                  "regression", "events"])

    csv_path = Path(config.TPE_HISTORY_CSV)
    meta_path = Path(config.HISTORY_META_JSON)

    if not csv_path.exists():
        notices.append(Notice(
            "warning",
            "No TPE history cache yet",
            "Projections need cache/tpe_by_season.csv. Run the 'Update TPE "
            "history' workflow from the Actions tab in GitHub, or run "
            "`python scripts/fetch_history.py` locally and commit the result. "
            "Everything else in the dashboard works without it.",
        ))
        return empty, {}, notices

    try:
        frame = pd.read_csv(csv_path)
    except Exception as exc:  # noqa: BLE001 - surfaced below
        notices.append(Notice(
            "error", "Could not read the TPE history cache",
            f"{type(exc).__name__}: {exc}. The file may be corrupt — re-run the "
            "Update TPE history workflow to rebuild it.",
        ))
        return empty, {}, notices

    missing = [c for c in ("name", "season", "earned") if c not in frame.columns]
    if missing:
        notices.append(Notice(
            "error", "The TPE history cache has unexpected columns",
            "Missing: " + ", ".join(missing) + ". Rebuild it with the workflow.",
        ))
        return empty, {}, notices

    frame["season"] = pd.to_numeric(frame["season"], errors="coerce")
    frame["earned"] = pd.to_numeric(frame["earned"], errors="coerce").fillna(0)
    frame = frame.dropna(subset=["season"])
    frame["season"] = frame["season"].astype(int)

    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            notices.append(Notice(
                "warning", "Could not read the history cache metadata",
                f"{type(exc).__name__}: {exc}. Rates still work; the 'as of' "
                "date will be missing.",
            ))

    return frame, meta, notices


def fetch_current_season() -> tuple[int | None, Notice | None]:
    """Ask the API which season it is. Falls back to max(class) if unavailable."""
    try:
        response = requests.get(config.CURRENT_SEASON_ENDPOINT,
                                timeout=config.REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return None, Notice(
            "info", "Could not read the current season from the API",
            f"{type(exc).__name__}. Falling back to the highest draft class "
            "seen in the player data, which is the same number in practice.",
        )

    if isinstance(payload, dict):
        for key in ("season", "Season", "currentSeason", "current_season"):
            if key in payload:
                try:
                    return int(payload[key]), None
                except (TypeError, ValueError):
                    pass
        if len(payload) == 1:
            try:
                return int(next(iter(payload.values()))), None
            except (TypeError, ValueError):
                pass
    try:
        return int(payload), None
    except (TypeError, ValueError):
        return None, Notice(
            "info", "The current-season endpoint returned an unexpected shape",
            "Falling back to the highest draft class in the player data.",
        )
