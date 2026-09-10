"""
Visual system for the SSL Team Tracker.

One template, registered once and applied globally via px.defaults, plus a
deterministic team-to-colour map so a club is the same colour on every chart in
every session. The previous version mixed viridis, ad-hoc blue/red and Plotly
defaults with no relationship between them.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

import config

_C = config.COLORS


def install_template() -> None:
    """Register and activate the SSL template. Safe to call repeatedly."""
    template = go.layout.Template()
    template.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=_C["surface"],
        font=dict(family="Inter, system-ui, sans-serif", color=_C["text"], size=13),
        title=dict(
            font=dict(family="Barlow Condensed, Inter, sans-serif", size=22),
            x=0, xanchor="left", pad=dict(b=12),
        ),
        colorway=config.TEAM_PALETTE,
        xaxis=dict(
            gridcolor=_C["line"], zerolinecolor=_C["line"],
            linecolor=_C["line"], tickfont=dict(color=_C["text_muted"]),
            title=dict(font=dict(color=_C["text_muted"], size=12)),
        ),
        yaxis=dict(
            gridcolor=_C["line"], zerolinecolor=_C["line"],
            linecolor=_C["line"], tickfont=dict(color=_C["text_muted"]),
            title=dict(font=dict(color=_C["text_muted"], size=12)),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", font=dict(color=_C["text_muted"], size=12),
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
        ),
        polar=dict(
            bgcolor=_C["surface"],
            radialaxis=dict(gridcolor=_C["line"], linecolor=_C["line"],
                            tickfont=dict(color=_C["text_muted"], size=10)),
            angularaxis=dict(gridcolor=_C["line"], linecolor=_C["line"],
                             tickfont=dict(color=_C["text_muted"], size=10)),
        ),
        margin=dict(l=10, r=10, t=50, b=10),
        hoverlabel=dict(
            bgcolor=_C["surface_alt"], bordercolor=_C["line"],
            font=dict(color=_C["text"], family="Inter, sans-serif"),
        ),
        colorscale=dict(sequential=[[i / 3, c] for i, c in enumerate(config.RAMP)]),
    )
    pio.templates[config.PLOTLY_TEMPLATE] = template
    pio.templates.default = config.PLOTLY_TEMPLATE
    px.defaults.template = config.PLOTLY_TEMPLATE


def assign_team_colors(teams: list[str]) -> dict[str, str]:
    """
    Stable colour per team.

    Sorted alphabetically then indexed into the palette, so the mapping only
    changes when the league's membership changes — not when a filter does.
    """
    ordered = sorted({str(t) for t in teams})
    palette = config.TEAM_PALETTE
    return {team: palette[i % len(palette)] for i, team in enumerate(ordered)}


def tpe_distribution(
    df: pd.DataFrame, group_col: str, color_map: dict[str, str], title: str
) -> go.Figure:
    """Per-player TPE strip plot, entities ordered by mean."""
    order = (
        df.groupby(group_col)["tpe"].mean().sort_values(ascending=False).index.tolist()
    )
    hover = [c for c in ("name", "position", "class", "team") if c in df.columns]
    fig = px.strip(
        df, x=group_col, y="tpe", color=group_col,
        hover_data=hover, title=title,
        category_orders={group_col: order},
        color_discrete_map=color_map,
        labels={group_col: "", "tpe": "TPE"},
    )
    fig.update_traces(marker=dict(size=8, opacity=0.75), jitter=0.55)
    fig.update_layout(showlegend=False, xaxis_tickangle=-40, height=520)
    return fig


def ranked_bar(
    frame: pd.DataFrame, x: str, y: str, color_map: dict[str, str],
    title: str, value_format: str = "{:,.0f}",
) -> go.Figure:
    """Horizontal ranked bar — reads better than vertical for long club names."""
    ordered = frame.sort_values(y, ascending=True)
    fig = px.bar(
        ordered, x=y, y=x, orientation="h", color=x,
        color_discrete_map=color_map, title=title,
        labels={x: "", y: y},
        text=[value_format.format(v) for v in ordered[y]],
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        showlegend=False,
        height=max(320, 26 * len(ordered) + 120),
    )
    return fig


def quadrant(
    frame: pd.DataFrame, x: str, y: str, label: str,
    color_map: dict[str, str], title: str,
) -> go.Figure:
    """Age-vs-quality scatter with median crosshairs."""
    fig = px.scatter(
        frame, x=x, y=y, text=label, color=label,
        color_discrete_map=color_map, title=title,
        labels={x: "Mean draft class (older to the right)", y: y},
    )
    fig.update_xaxes(autorange="reversed")
    fig.add_hline(y=frame[y].median(), line_dash="dot", line_color=_C["line"])
    fig.add_vline(x=frame[x].median(), line_dash="dot", line_color=_C["line"])
    fig.update_traces(
        textposition="top center", marker=dict(size=13),
        textfont=dict(size=11, color=_C["text_muted"]),
    )
    fig.update_layout(showlegend=False, height=580)
    return fig


def radar(
    series: list[tuple[str, pd.Series, str]], title: str, max_value: int | None = None
) -> go.Figure:
    """
    Attribute radar. `series` is a list of (name, values indexed by attribute,
    hex colour).
    """
    fig = go.Figure()
    for name, values, color in series:
        if values is None or len(values) == 0:
            continue
        fig.add_trace(go.Scatterpolar(
            r=values.values.tolist() + [values.values.tolist()[0]],
            theta=values.index.tolist() + [values.index.tolist()[0]],
            fill="toself", name=name,
            line=dict(color=color, width=2),
            fillcolor=_hex_to_rgba(color, 0.18),
        ))
    fig.update_layout(
        title=title,
        polar=dict(radialaxis=dict(
            visible=True, range=[0, max_value or config.ATTRIBUTE_MAX],
        )),
        height=560,
        showlegend=len(series) > 1,
    )
    return fig


def group_comparison(
    frame: pd.DataFrame, entity_a: str, entity_b: str, metric_label: str
) -> go.Figure:
    """Grouped bars comparing two entities across position groups."""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=entity_a, x=frame["Group"], y=frame[entity_a],
        marker_color=_C["primary"],
    ))
    fig.add_trace(go.Bar(
        name=entity_b, x=frame["Group"], y=frame[entity_b],
        marker_color=_C["blue"],
    ))
    fig.update_layout(
        barmode="group", title=f"{metric_label} TPE by position group", height=400,
    )
    return fig


def history_lines(
    frame: pd.DataFrame, color_map: dict[str, str], value_label: str
) -> go.Figure:
    fig = px.line(
        frame, x="season", y="value", color="team", markers=True,
        color_discrete_map=color_map,
        title=f"{value_label} by season",
        labels={"season": "Season", "value": value_label, "team": ""},
    )
    fig.update_layout(hovermode="x unified", height=520)
    return fig


def coverage_heatmap(frame: pd.DataFrame, title: str) -> go.Figure:
    """
    Positional coverage as a heatmap.

    Drawn in Plotly rather than a pandas Styler gradient: the Styler route
    quietly requires matplotlib, and it wouldn't share this template's colours.
    """
    positions = [p for p in config.POSITION_COLUMNS if p in frame.columns]
    entities = frame["Entity"].astype(str).tolist()
    values = frame[positions].to_numpy()

    fig = go.Figure(go.Heatmap(
        z=values,
        x=positions,
        y=entities,
        colorscale=[[i / (len(config.RAMP) - 1), c]
                    for i, c in enumerate(config.RAMP)],
        text=values,
        texttemplate="%{text}",
        textfont=dict(size=11),
        hovertemplate="%{y} · %{x}: %{z} player(s)<extra></extra>",
        showscale=False,
        xgap=2, ygap=2,
    ))
    fig.update_layout(
        title=title,
        height=max(260, 32 * len(entities) + 140),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def attribute_color(value: float) -> str:
    """FM-style colour for a 1-20 attribute value."""
    if value >= 16:
        return config.RAMP[3]
    if value >= 13:
        return config.RAMP[2]
    if value >= 9:
        return config.RAMP[1]
    return config.RAMP[0]
