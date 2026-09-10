"""Shared Streamlit helpers: theming, notices, formatting, exports."""

from __future__ import annotations

from string import Template

import pandas as pd
import streamlit as st

import config
from data import Notice

_C = config.COLORS

# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
# Defined at module level and flush against the left margin on purpose.
#
# Streamlit's markdown renderer treats any line indented four or more spaces as
# a code block. An indented <style> block therefore gets applied up to the first
# over-indented line and then printed to the page as literal text. Keeping this
# at zero indentation, and injecting it through st.html (which bypasses the
# markdown parser entirely), rules that out.

_CSS_TEMPLATE = """
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

.stApp { background: $bg; }

/* Scoped deliberately narrowly. A broad selector such as [class*="st-"] also
matches Streamlit's Material icon spans and overrides their icon font, which
makes icons render as their literal ligature names ("check_circle"). */
.stApp, .stApp p, .stApp li, .stApp label, .stApp span, .stApp div,
.stApp input, .stApp textarea, .stApp select, .stApp button {
font-family: 'Inter', system-ui, -apple-system, sans-serif;
}

/* Belt and braces: never let the rule above reach an icon glyph. */
[data-testid="stIconMaterial"],
span[class*="material-symbols"],
.material-symbols-rounded, .material-symbols-outlined {
font-family: 'Material Symbols Rounded', 'Material Symbols Outlined' !important;
font-feature-settings: 'liga';
}

h1, h2, h3 {
font-family: 'Barlow Condensed', 'Inter', sans-serif !important;
letter-spacing: 0.01em;
color: $text !important;
}
h1 { font-size: 2.6rem !important; font-weight: 700 !important; }
h2 { font-size: 1.7rem !important; font-weight: 600 !important; }
h3 { font-size: 1.25rem !important; font-weight: 600 !important; }

.stApp, .stApp p, .stApp li, .stApp label { color: $text; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
color: $muted !important;
}

[data-testid="stMetricValue"] {
font-family: 'Barlow Condensed', sans-serif;
font-size: 2.1rem;
color: $text;
}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p { color: $muted; }

[data-testid="stSidebar"] {
background: $surface;
border-right: 1px solid $line;
}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
[data-testid="stSidebar"] h3 { color: $text; }

.ssl-status {
display: flex; align-items: baseline; gap: 0.6rem;
padding: 0.5rem 0.85rem; margin-bottom: 1rem;
background: $surface;
border-left: 3px solid $primary;
border-radius: 3px;
color: $muted; font-size: 0.85rem;
}
.ssl-status strong { color: $text; font-weight: 600; }

.ssl-insight {
padding: 0.7rem 0.9rem; margin-bottom: 0.5rem;
background: $surface;
border-left: 3px solid $primary_dim;
border-radius: 3px;
}
.ssl-insight .k { color: $muted; font-size: 0.78rem; display: block; }
.ssl-insight .v { color: $text; font-size: 0.98rem; font-weight: 500; }

.ssl-empty {
padding: 2rem 1.5rem; text-align: left;
background: $surface;
border: 1px dashed $line; border-radius: 4px;
color: $muted;
}
.ssl-empty strong {
color: $text; display: block;
font-family: 'Barlow Condensed', sans-serif; font-size: 1.3rem;
margin-bottom: 0.35rem;
}

.stTabs [data-baseweb="tab"] { font-weight: 500; }
hr { border-color: $line; }
"""

# Template rather than .format(): CSS is full of literal { } braces, which
# str.format would try to read as replacement fields.
_CSS = Template(_CSS_TEMPLATE).substitute(
    bg=_C["bg"],
    surface=_C["surface"],
    line=_C["line"],
    text=_C["text"],
    muted=_C["text_muted"],
    primary=_C["primary"],
    primary_dim=_C["primary_dim"],
)


def _raw_html(markup: str) -> None:
    """
    Render raw HTML without going through the markdown parser.

    st.html arrived in Streamlit 1.33; the markdown path is a fallback for older
    installs. Markup is always passed as a single unindented string so that even
    the fallback can't trip the indented-code-block rule.
    """
    if hasattr(st, "html"):
        st.html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)


def inject_css() -> None:
    """
    Typography and surface treatment.

    Barlow Condensed for figures is the vernacular of a scoreboard, which is
    what most of this dashboard is; Inter carries everything read as prose.
    """
    _raw_html("<style>" + _CSS + "</style>")


def render_notices(notices: list[Notice], *, only: set[str] | None = None) -> None:
    """Render loader messages. Nothing here is ever swallowed."""
    for notice in notices:
        if only and notice.level not in only:
            continue
        body = f"**{notice.title}**"
        if notice.detail:
            body += f"\n\n{notice.detail}"
        if notice.level == "error":
            st.error(body, icon=":material/error:")
        elif notice.level == "warning":
            st.warning(body, icon=":material/warning:")
        else:
            st.caption(f"{notice.title} — {notice.detail}" if notice.detail
                       else notice.title)


def empty_state(headline: str, guidance: str) -> None:
    """An empty screen should say what to do next, not just that it's empty."""
    _raw_html(
        f'<div class="ssl-empty"><strong>{headline}</strong>{guidance}</div>'
    )


def status_bar(state: str, detail: str) -> None:
    """The 'data as of' strip under the page title."""
    _raw_html(f'<div class="ssl-status"><strong>{state}</strong>{detail}</div>')


def insight_card(label: str, value: str) -> None:
    _raw_html(
        f'<div class="ssl-insight"><span class="k">{label}</span>'
        f'<span class="v">{value}</span></div>'
    )


def money(value: float) -> str:
    """Format a currency figure using the configured (and unverified) unit."""
    try:
        rendered = f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"
    return f"{config.CURRENCY_PREFIX}{rendered}{config.CURRENCY_SUFFIX}"


def money_compact(value: float) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(num) >= threshold:
            return (f"{config.CURRENCY_PREFIX}{num / threshold:,.1f}{suffix}"
                    f"{config.CURRENCY_SUFFIX}")
    return money(num)


def download(frame: pd.DataFrame, filename: str, label: str = "Download CSV") -> None:
    """Export whatever the user is currently looking at."""
    if frame is None or frame.empty:
        return
    st.download_button(
        label,
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        key=f"dl_{filename}",
    )


def section(title: str, note: str = "") -> None:
    st.subheader(title)
    if note:
        st.caption(note)
