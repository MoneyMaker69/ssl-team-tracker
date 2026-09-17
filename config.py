"""
Central configuration for the SSL Team Tracker.

Everything that a future maintainer might reasonably need to change lives here:
API endpoints, the position taxonomy, formations, currency formatting, and the
Google Sheet layout. No business logic.
"""

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

API_BASE = "https://api.simulationsoccer.com"
PLAYERS_ENDPOINT = f"{API_BASE}/player/getAllPlayers"
PLAYERS_PARAMS = {"active": "true"}

# Note: `active=true` filters *player records*, not user accounts. The response
# still contains players whose `userStatus` is "Inactive" — see the Activity
# view, which is built specifically around that distinction.

REQUEST_TIMEOUT = 20
CACHE_TTL_SECONDS = 600  # 10 minutes; the sidebar refresh button clears early.

# Endpoints the SSL Portal implies should exist but which could not be verified
# from a sandboxed environment. The Admin page probes these live from wherever
# the app is actually running. Anything that answers 200 can be promoted into a
# real loader in data.py.
CANDIDATE_ENDPOINTS = [
    "/team/getAllTeams",
    "/team/getTeams",
    "/organization/getAllOrganizations",
    "/club/getAllClubs",
    "/league/getStandings",
    "/league/getSchedule",
    "/game/getResults",
    "/player/getPlayer",
    "/player/getPlayerHistory",
    "/player/getUpdateHistory",
    "/bank/getTransactions",
    "/nation/getAllNations",
    "/draft/getDraftClass",
    "/openapi.json",
    "/swagger.json",
    "/docs-json",
]

# ---------------------------------------------------------------------------
# Google Sheet (historical leaderboard)
# ---------------------------------------------------------------------------

SPREADSHEET_ID = "1dlJLL85csDV8HXaig8dtZQNgmG9YeAJSS3eeM-nhocA"
LEADERBOARD_GID = "1702210962"

# Preferred path: pin the layout explicitly. If HEADER_ROW is None the loader
# falls back to scanning for a header row, but it reports which path it used so
# a silent format change can't hide.
SHEET_LAYOUT = {
    "header_row": None,          # 0-indexed row containing column headers
    "team_column": None,         # exact header text, e.g. "Team"
    "season_column": None,       # e.g. "Season"
    "value_column": None,        # e.g. "Top XI Avg"
}

# Header labels the fallback scanner will accept, in priority order. Matching is
# case-insensitive and whitespace-normalised, so "Top XI Avg " still matches.
SHEET_VALUE_LABELS = [
    ("Top XI Avg TPE", ["top xi avg", "top xi average", "top 11 avg"]),
    ("Avg TPE", ["avg tpe", "average tpe", "mean tpe"]),
]
SHEET_TEAM_LABELS = ["team", "franchise", "club"]
SHEET_SEASON_LABELS = ["season", "szn"]

# Sheet-name to API-name overrides. This is now a *fallback* only: unmatched
# names are surfaced in the Admin page rather than silently dropped, and fuzzy
# matching handles most spelling drift automatically.
SHEET_NAME_OVERRIDES = {
    "Club Atlètico Buenos Aires": "CA Buenos Aires",
    "Hollywood Football Club": "Hollywood FC",
    "Athletice Clava Romana": "A.C. Romana",
    "Shanghai Dragons": "Shanghai Dragons FC",
    "Xelajú Cósmico Fùtbol Club": "Xelajú Cósmico FC",
    "Tokyo Sports Club": "Tokyo S.C.",
    "Club de Futbol Catalunya": "CF Catalunya",
    "Schwarzwälder Fußballverein": "Schwarzwälder FV",
    "Club Deportivo Tenochtitlan": "CD Tenochtitlan",
    "Liffeyside Celtic Football Club": "Liffeyside Celtic FC",
}

# ---------------------------------------------------------------------------
# Teams, orgs, tiers
# ---------------------------------------------------------------------------

# "Free Agent" arrives from the API as a team with a real roster attached. It is
# not a club and must never appear in league averages or power rankings, but it
# is genuinely useful to browse, so it gets its own view.
FREE_AGENT_TEAM = "Free Agent"
NON_CLUB_TEAMS = {FREE_AGENT_TEAM, "", "None", "none"}

# The API's `affiliate` field. Verified against the previously hardcoded pairs:
# Hollywood FC (1) / F.C. Kaapstad (2) both report organization "Hollywood FC".
AFFILIATE_LABELS = {1: "Major", 2: "Minor"}

# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

# Every player carries a single `position` string. That is the authoritative
# primary position, and it is what the app groups by — so counts and averages
# add up to the squad total exactly once.
POSITION_TO_GROUP = {
    "GK": "Goalkeeper",
    "CD": "Defence", "LD": "Defence", "RD": "Defence",
    "LWB": "Defence", "RWB": "Defence",
    "CDM": "Midfield", "CM": "Midfield", "LM": "Midfield", "RM": "Midfield",
    "CAM": "Attack", "LAM": "Attack", "RAM": "Attack", "ST": "Attack",
}

GROUP_ORDER = ["Goalkeeper", "Defence", "Midfield", "Attack"]

# The 14 positional-familiarity columns. These are *not* mutually exclusive: a
# player can be 20 at ST and 20 at CD simultaneously. They drive the coverage
# matrix and Best XI eligibility, never the headline group counts.
POSITION_COLUMNS = {
    "ST": "pos_st", "LAM": "pos_lam", "CAM": "pos_cam", "RAM": "pos_ram",
    "LM": "pos_lm", "CM": "pos_cm", "RM": "pos_rm", "CDM": "pos_cdm",
    "LWB": "pos_lwb", "RWB": "pos_rwb",
    "LD": "pos_ld", "CD": "pos_cd", "RD": "pos_rd",
    "GK": "pos_gk",
}

# FM familiarity runs 0 / 15 / 20 in this dataset. 15 = "competent", 20 =
# "natural". 15 is the eligibility floor for slotting a player into a position.
FAMILIARITY_THRESHOLD = 15
FAMILIARITY_NATURAL = 20

# ---------------------------------------------------------------------------
# Formations
# ---------------------------------------------------------------------------

# Each slot is (display label, familiarity column). Duplicated labels are fine;
# the Best XI solver treats each entry as a distinct slot to fill.
FORMATIONS = {
    "4-3-3": [
        ("GK", "pos_gk"),
        ("LD", "pos_ld"), ("CD", "pos_cd"), ("CD", "pos_cd"), ("RD", "pos_rd"),
        ("CDM", "pos_cdm"), ("CM", "pos_cm"), ("CM", "pos_cm"),
        ("LAM", "pos_lam"), ("ST", "pos_st"), ("RAM", "pos_ram"),
    ],
    "4-2-3-1": [
        ("GK", "pos_gk"),
        ("LD", "pos_ld"), ("CD", "pos_cd"), ("CD", "pos_cd"), ("RD", "pos_rd"),
        ("CDM", "pos_cdm"), ("CDM", "pos_cdm"),
        ("LAM", "pos_lam"), ("CAM", "pos_cam"), ("RAM", "pos_ram"),
        ("ST", "pos_st"),
    ],
    "4-4-2": [
        ("GK", "pos_gk"),
        ("LD", "pos_ld"), ("CD", "pos_cd"), ("CD", "pos_cd"), ("RD", "pos_rd"),
        ("LM", "pos_lm"), ("CM", "pos_cm"), ("CM", "pos_cm"), ("RM", "pos_rm"),
        ("ST", "pos_st"), ("ST", "pos_st"),
    ],
    "3-5-2": [
        ("GK", "pos_gk"),
        ("CD", "pos_cd"), ("CD", "pos_cd"), ("CD", "pos_cd"),
        ("LWB", "pos_lwb"), ("CM", "pos_cm"), ("CM", "pos_cm"), ("RWB", "pos_rwb"),
        ("CAM", "pos_cam"), ("ST", "pos_st"), ("ST", "pos_st"),
    ],
    "5-3-2": [
        ("GK", "pos_gk"),
        ("LWB", "pos_lwb"), ("CD", "pos_cd"), ("CD", "pos_cd"), ("CD", "pos_cd"),
        ("RWB", "pos_rwb"),
        ("CDM", "pos_cdm"), ("CM", "pos_cm"), ("CM", "pos_cm"),
        ("ST", "pos_st"), ("ST", "pos_st"),
    ],
}
DEFAULT_FORMATION = "4-3-3"

# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------

# Verified against a live getAllPlayers response — all 36 outfield keys exist
# with these exact names (including the spaces).
OUTFIELD_ATTRIBUTES = [
    "acceleration", "agility", "balance", "jumping reach", "natural fitness",
    "pace", "stamina", "strength",
    "corners", "crossing", "dribbling", "finishing", "first touch", "free kick",
    "heading", "long shots", "long throws", "marking", "passing",
    "penalty taking", "tackling", "technique",
    "aggression", "anticipation", "bravery", "composure", "concentration",
    "decisions", "determination", "flair", "leadership", "off the ball",
    "positioning", "teamwork", "vision", "work rate",
]

# The 11 keeper-only attributes the previous version never read.
GK_ATTRIBUTES = [
    "aerial reach", "command of area", "communication", "eccentricity",
    "handling", "kicking", "one on ones", "reflexes", "tendency to rush",
    "tendency to punch", "throwing",
]

# Sit at 20 for essentially every player, so they add nothing to a radar and
# flatten the shape of everything else. Excluded from radars, kept in tables.
CONSTANT_ATTRIBUTES = ["stamina", "natural fitness"]

RADAR_OUTFIELD = [a for a in OUTFIELD_ATTRIBUTES if a not in CONSTANT_ATTRIBUTES]

ATTRIBUTE_GROUPS = {
    "Physical": ["acceleration", "agility", "balance", "jumping reach",
                 "natural fitness", "pace", "stamina", "strength"],
    "Technical": ["corners", "crossing", "dribbling", "finishing", "first touch",
                  "free kick", "heading", "long shots", "long throws", "marking",
                  "passing", "penalty taking", "tackling", "technique"],
    "Mental": ["aggression", "anticipation", "bravery", "composure",
               "concentration", "decisions", "determination", "flair",
               "leadership", "off the ball", "positioning", "teamwork",
               "vision", "work rate"],
}

ATTRIBUTE_MAX = 20

# ---------------------------------------------------------------------------
# Schema guard
# ---------------------------------------------------------------------------

# Missing any of these means the app cannot function; the loader raises a named
# error listing exactly what's absent instead of a bare KeyError deep in a view.
REQUIRED_COLUMNS = [
    "name", "team", "class", "position", "tpe", "bankBalance",
    "organization", "affiliate",
]

# Missing these degrades a feature but not the app; each is reported once.
OPTIONAL_COLUMNS = [
    "timesregressed", "userStatus", "playerStatus", "nationality", "region",
    "minimum salary", "tpeused", "tpebank", "purchasedTPE", "traits",
    "username", "pid", "created", "height", "weight", "left foot", "right foot",
]

# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

# The API returns bare integers for `bankBalance` and `minimum salary` with no
# unit anywhere in the payload. The previous version's "€" was an unverified
# guess. Set CURRENCY_PREFIX to "$", "€" or whatever SSL actually uses and every
# figure in the app updates.
CURRENCY_PREFIX = ""
CURRENCY_SUFFIX = ""
CURRENCY_UNVERIFIED = True  # shows a one-line note in the Finance view

# ---------------------------------------------------------------------------
# Visual system
# ---------------------------------------------------------------------------

# Grounded in the subject: a floodlit pitch at night, plus FM's own red→amber→
# green ramp for the 1-20 attribute scale.
COLORS = {
    "bg": "#0E1A16",         # pitch at night
    "surface": "#16241F",
    "surface_alt": "#1D2F28",
    "line": "#33473F",       # chalk lines
    "text": "#E8E6DF",
    "text_muted": "#93A69C",
    "primary": "#2F9E5E",    # turf
    "primary_dim": "#1F6B40",
    "amber": "#D9A441",
    "red": "#C8503C",
    "blue": "#4C8FBF",       # away-kit blue, used for the B side in H2H
}

# Diverging ramp used for anything on the 1-20 attribute scale or for
# below/above-median comparisons.
RAMP = ["#C8503C", "#D9A441", "#8FBF5A", "#2F9E5E"]

# Qualitative palette for per-team colouring. Assignment is deterministic (see
# charts.assign_team_colors) so a club keeps the same colour on every chart in
# every session. No team colours or crests are exposed by the API, so these are
# ours, not the clubs'.
TEAM_PALETTE = [
    "#2F9E5E", "#4C8FBF", "#D9A441", "#C8503C", "#8E6FC7", "#3FB6A8",
    "#E07B39", "#6FA8DC", "#B5C94F", "#D46A9F", "#7FBF6A", "#C9A227",
    "#5E8CD6", "#A5563F", "#4FA8A0", "#9B7FD4", "#DC8A5A", "#6BBF8E",
    "#B07FC7", "#D4B04A",
]

PLOTLY_TEMPLATE = "ssl_dark"


# ---------------------------------------------------------------------------
# Projection rules (SSL Rulebook)
# ---------------------------------------------------------------------------

# Keyed on CAREER SEASON NUMBER (1-indexed), not on seasons elapsed: a player
# drafted in S13 is in career season 8 during S20. Season 8 is the first that
# regresses. Verified against the S26 regression post to the TPE.
#
# Note the schedule was harsher before ~S22 (10% started a season earlier), so
# historical TPE logs will NOT reconcile against this table. That is expected.
REGRESSION_FIRST_SEASON = 8
REGRESSION_SCHEDULE = {8: 0.10, 9: 0.15, 10: 0.20, 11: 0.25, 12: 0.30, 13: 0.35}
REGRESSION_MAX = 0.40            # career season 14 and beyond
MAX_CAREER_SEASON = 20           # past this a player is assumed gone

# Training camp steps down with career season. Also changed historically
# (was 30 / 20 / 6), so old logs won't match this either.
TRAINING_CAMP_BANDS = [(3, 24), (6, 18), (9, 12)]
TRAINING_CAMP_DEFAULT = 6

# One Activity Check and one Weekly PT per week, 6 TPE each.
WEEKS_PER_SEASON = 10
AC_PER_WEEK = 6
PT_PER_WEEK = 6

# Rookies start at 250 and can do all the normal tasks during their one academy
# season, so they enter the draft meaningfully above 250.
ROOKIE_START_TPE = 250
DEFAULT_DRAFTEE_ENTRY_TPE = 420

# History cache, written by scripts/fetch_history.py via the weekly Action.
CACHE_DIR = "cache"
TPE_HISTORY_CSV = "cache/tpe_by_season.csv"
HISTORY_META_JSON = "cache/history_meta.json"

CURRENT_SEASON_ENDPOINT = f"{API_BASE}/admin/getCurrentSeason"
TPE_HISTORY_ENDPOINT = f"{API_BASE}/player/getTPEhistory"
SCHEDULE_ENDPOINT = f"{API_BASE}/index/schedule"

# Projection defaults, all overridable from the sidebar.
DEFAULT_HORIZON = 5
DEFAULT_RATE_WINDOW = 2          # complete seasons used to measure earning rate
DEFAULT_ATTRITION = 0.12
DEFAULT_DRAFTEES_PER_SEASON = 2
MONTE_CARLO_TRIALS = 300
