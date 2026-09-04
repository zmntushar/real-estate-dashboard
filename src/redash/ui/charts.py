"""Plotly chart builders.

One palette, one template, applied everywhere so the dashboard reads as a
single system. Colour carries meaning: teal for the selected region, grey for
benchmarks, green/red only for direction of change.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

PRIMARY = "#0e9aa7"
PRIMARY_FILL = "rgba(14, 154, 167, 0.14)"
BENCH = ["#8c9bab", "#b6c0cb", "#d3dae1"]
UP = "#1f9d55"
DOWN = "#d64545"
NEUTRAL = "#8c9bab"
GRID = "rgba(140, 155, 171, 0.22)"

_LAYOUT = dict(
    template="plotly_white",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                title_text=""),
    font=dict(size=13),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)


def _style(fig: go.Figure, title: str | None = None, y_title: str | None = None,
           y_prefix: str | None = None, y_suffix: str | None = None,
           legend: bool = False) -> go.Figure:
    fig.update_layout(**_LAYOUT)
    # A horizontal legend sits just above the plot area, so the title needs its
    # own room in the margin above it or the two collide.
    top = 86 if legend else 48
    fig.update_layout(margin=dict(l=10, r=10, t=top, b=10))
    if title:
        fig.update_layout(title=dict(text=title, x=0, xanchor="left",
                                     yref="container", y=0.97, yanchor="top",
                                     font=dict(size=15)))
    fig.update_xaxes(showgrid=False, zeroline=False, showline=True,
                     linecolor=GRID, ticks="outside", tickcolor=GRID)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False,
                     title_text=y_title, tickprefix=y_prefix, ticksuffix=y_suffix)
    return fig


def price_history(main: pd.Series, main_label: str,
                  benchmarks: list[tuple[str, pd.Series]] | None = None,
                  title: str = "Home value history",
                  y_prefix: str = "$") -> go.Figure:
    """Selected region against its containing geographies."""
    fig = go.Figure()
    for i, (label, s) in enumerate(benchmarks or []):
        if s is None or s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.to_numpy(), name=label, mode="lines",
            line=dict(color=BENCH[i % len(BENCH)], width=1.6, dash="dot"),
            hovertemplate="%{y:,.0f}<extra>" + label + "</extra>"))
    if main is not None and not main.empty:
        fig.add_trace(go.Scatter(
            x=main.index, y=main.to_numpy(), name=main_label, mode="lines",
            line=dict(color=PRIMARY, width=2.6), fill="tozeroy",
            fillcolor=PRIMARY_FILL,
            hovertemplate="%{y:,.0f}<extra>" + main_label + "</extra>"))
        fig.update_yaxes(range=[0, float(main.max()) * 1.18])
    return _style(fig, title, y_prefix=y_prefix, legend=True)


def yoy_bars(s: pd.Series, title: str = "Year-over-year change",
             years: int = 8) -> go.Figure:
    """Signed YoY change - green above zero, red below."""
    fig = go.Figure()
    if s is not None and not s.empty:
        cutoff = s.index.max() - pd.DateOffset(years=years)
        s = s[s.index >= cutoff]
        colors = [UP if v >= 0 else DOWN for v in s]
        fig.add_trace(go.Bar(
            x=s.index, y=s.to_numpy(), marker_color=colors, name="YoY %",
            hovertemplate="%{y:+.1f}%<extra></extra>"))
        fig.add_hline(y=0, line_width=1, line_color=NEUTRAL)
    return _style(fig, title, y_suffix="%")


def indexed_comparison(series_map: dict[str, pd.Series], start: pd.Timestamp,
                       title: str = "Growth compared",
                       highlight: str | None = None) -> go.Figure:
    """Multiple regions rebased to 100 at a common start date."""
    fig = go.Figure()
    bench_i = 0
    for label, s in series_map.items():
        if s is None or s.empty:
            continue
        is_main = (label == highlight)
        fig.add_trace(go.Scatter(
            x=s.index, y=s.to_numpy(), name=label, mode="lines",
            line=dict(color=PRIMARY if is_main else BENCH[bench_i % len(BENCH)],
                      width=2.6 if is_main else 1.6,
                      dash=None if is_main else "dot"),
            hovertemplate="%{y:,.1f}<extra>" + label + "</extra>"))
        if not is_main:
            bench_i += 1
    fig.add_hline(y=100, line_width=1, line_color=NEUTRAL, line_dash="dash")
    return _style(fig, f"{title} (indexed to 100 at {start:%b %Y})",
                  legend=True)


def dual_axis(left: pd.Series, left_label: str, right: pd.Series, right_label: str,
              title: str, left_prefix: str = "", right_suffix: str = "") -> go.Figure:
    """Two related supply/demand series that share a time axis."""
    fig = go.Figure()
    if left is not None and not left.empty:
        fig.add_trace(go.Scatter(
            x=left.index, y=left.to_numpy(), name=left_label, mode="lines",
            line=dict(color=PRIMARY, width=2.4),
            hovertemplate="%{y:,.0f}<extra>" + left_label + "</extra>"))
    if right is not None and not right.empty:
        fig.add_trace(go.Scatter(
            x=right.index, y=right.to_numpy(), name=right_label, mode="lines",
            yaxis="y2", line=dict(color="#c98b2e", width=2.0),
            hovertemplate="%{y:,.1f}<extra>" + right_label + "</extra>"))
    fig.update_layout(
        yaxis=dict(title=left_label, tickprefix=left_prefix),
        yaxis2=dict(title=right_label, overlaying="y", side="right",
                    showgrid=False, ticksuffix=right_suffix))
    return _style(fig, title, legend=True)


def scanner_scatter(df: pd.DataFrame, x: str, y: str, label_col: str,
                    size_col: str | None = None, x_title: str = "",
                    y_title: str = "", title: str = "") -> go.Figure:
    """Level vs momentum scatter for the national scanner."""
    fig = go.Figure()
    if df.empty:
        return _style(fig, title)
    colors = [UP if v >= 0 else DOWN for v in df[y]]
    sizes = 12
    if size_col and size_col in df:
        raw = pd.to_numeric(df[size_col], errors="coerce").fillna(0.0)
        span = float(raw.max() - raw.min())
        if span > 0:
            sizes = (8 + 22 * ((raw - raw.min()) / span)).to_numpy()
    fig.add_trace(go.Scatter(
        x=df[x], y=df[y], mode="markers", text=df[label_col],
        marker=dict(color=colors, size=sizes, opacity=0.75,
                    line=dict(width=0.5, color="white")),
        hovertemplate="<b>%{text}</b><br>%{x:,.0f}<br>%{y:+.1f}%<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color=NEUTRAL, line_dash="dash")
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title_text=x_title)
    return _style(fig, title, y_title=y_title, y_suffix="%")


def ranked_bars(df: pd.DataFrame, value_col: str, label_col: str,
                title: str = "", suffix: str = "%") -> go.Figure:
    """Horizontal ranking of regions by a signed metric."""
    fig = go.Figure()
    if df.empty:
        return _style(fig, title)
    d = df.iloc[::-1]  # plotly draws horizontal bars bottom-up
    colors = [UP if v >= 0 else DOWN for v in d[value_col]]
    fig.add_trace(go.Bar(
        x=d[value_col], y=d[label_col], orientation="h", marker_color=colors,
        hovertemplate="<b>%{y}</b><br>%{x:+.1f}" + suffix + "<extra></extra>"))
    fig.update_layout(height=max(280, 26 * len(d) + 90), hovermode="closest")
    fig.update_yaxes(automargin=True)
    return _style(fig, title)


def simple_line(s: pd.Series, title: str, y_prefix: str = "", y_suffix: str = "",
                color: str = PRIMARY, fill: bool = False) -> go.Figure:
    fig = go.Figure()
    if s is not None and not s.empty:
        fig.add_trace(go.Scatter(
            x=s.index, y=s.to_numpy(), mode="lines",
            line=dict(color=color, width=2.4),
            fill="tozeroy" if fill else None, fillcolor=PRIMARY_FILL,
            hovertemplate="%{y:,.2f}<extra></extra>", showlegend=False))
    return _style(fig, title, y_prefix=y_prefix or None, y_suffix=y_suffix or None)


def comparison_bars(labels: list[str], values: list[float], title: str,
                    highlight_index: int = 0, suffix: str = "",
                    prefix: str = "") -> go.Figure:
    """One region against its benchmarks for a single indicator."""
    fig = go.Figure()
    colors = [PRIMARY if i == highlight_index else NEUTRAL for i in range(len(labels))]
    fig.add_trace(go.Bar(
        x=labels, y=values, marker_color=colors,
        hovertemplate="<b>%{x}</b><br>%{y:,.1f}<extra></extra>"))
    fig.update_layout(height=300, hovermode="closest", showlegend=False)
    return _style(fig, title, y_prefix=prefix or None, y_suffix=suffix or None)
