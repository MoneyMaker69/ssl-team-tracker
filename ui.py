"""Shared Streamlit helpers: theming, notices, formatting, exports."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import Notice

_C = config.COLORS


def inject_css() -> None:
    """
    Typography and surface treatment.

    Barlow Condensed for figures is the vernacular of a scoreboard, which is
    what most of this dashboard is; Inter carries everything that has to be read
    as prose.
    """
    st.markdown(
        f"""
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
          .stApp {{ background: {_C['bg']}; }}
          html, body, [class*="st-"] {{
              font-family: 'Inter', system-ui, sans-serif;
          }}
          h1, h2, h3 {{
              font-family: 'Barlow Condensed', 'Inter', sans-serif !important;
              letter-spacing: 0.01em;
              color: {_C['text']} !important;
          }}
          h1 {{ font-size: 2.6rem !important; font-weight: 700 !important; }}
          h2 {{ font-size: 1.7rem !important; font-weight: 600 !important; }}
          h3 {{ font-size: 1.25rem !important; font-weight: 600 !important; }}

          [data-testid="stMetricValue"] {{
              font-family: 'Barlow Condensed', sans-serif;
              font-size: 2.1rem;
              color: {_C['text']};
          }}
          [data-testid="stMetricLabel"] {{ color: {_C['text_muted']}; }}

          [data-testid="stSidebar"] {{
              background: {_C['surface']};
              border-right: 1px solid {_C['line']};
          }}

          .ssl-status {{
              display: flex; align-items: baseline; gap: 0.6rem;
              padding: 0.5rem 0.85rem; margin-bottom: 1rem;
              background: {_C['surface']};
              border-left: 3px solid {_C['primary']};
              border-radius: 3px;
              color: {_C['text_muted']}; font-size: 0.85rem;
          }}
          .ssl-status strong {{ color: {_C['text']}; font-weight: 600; }}

          .ssl-insight {{
              padding: 0.7rem 0.9rem; margin-bottom: 0.5rem;
              background: {_C['surface']};
              border-left: 3px solid {_C['primary_dim']};
              border-radius: 3px;
          }}
          .ssl-insight .k {{
              color: {_C['text_muted']}; font-size: 0.78rem; display: block;
          }}
          .ssl-insight .v {{
              color: {_C['text']}; font-size: 0.98rem; font-weight: 500;
          }}

          .ssl-empty {{
              padding: 2rem 1.5rem; text-align: left;
              background: {_C['surface']};
              border: 1px dashed {_C['line']}; border-radius: 4px;
              color: {_C['text_muted']};
          }}
          .ssl-empty strong {{ color: {_C['text']}; display: block;
              font-family: 'Barlow Condensed', sans-serif; font-size: 1.3rem;
              margin-bottom: 0.35rem; }}

          .stTabs [data-baseweb="tab"] {{ font-weight: 500; }}
          hr {{ border-color: {_C['line']}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    st.markdown(
        f'<div class="ssl-empty"><strong>{headline}</strong>{guidance}</div>',
        unsafe_allow_html=True,
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


def insight_card(label: str, value: str) -> None:
    st.markdown(
        f'<div class="ssl-insight"><span class="k">{label}</span>'
        f'<span class="v">{value}</span></div>',
        unsafe_allow_html=True,
    )


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
