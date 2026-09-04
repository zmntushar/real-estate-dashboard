"""Plotly chart builders.

One palette per theme, applied everywhere, so the dashboard reads as a single
system in both light and dark. Colour carries meaning: teal for the selected
region, grey for benchmarks, green/red only for direction of change.

The dark palette is not the light one dimmed. Dimming is exactly what makes a
dark theme look washed out, so every accent is re-picked at higher lightness
and chroma to hold its contrast against a dark ground.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go


@dataclass(frozen=True)
class Palette:
    template: str
    primary: str        # the selected region
    primary_fill: str   # area fill under it
    accent: str         # the second series on a dual axis
    bench: tuple[str, ...]
    up: str
    down: str
    neutral: str
    grid: str
    axis: str


LIGHT = Palette(
    template="plotly_white",
    primary="#0e9aa7",
    primary_fill="rgba(14, 154, 167, 0.14)",
    accent="#c07a1e",
    bench=("#6b7c8c", "#8e9ba8", "#a4b0bb"),
    up="#1f9d55",
    down="#d64545",
    neutral="#7d8c9b",
    grid="rgba(120, 138, 156, 0.22)",
    axis="rgba(120, 138, 156, 0.45)",
)

DARK = Palette(
    template="plotly_dark",
    primary="#2ec7d4",
    primary_fill="rgba(46, 199, 212, 0.20)",
    accent="#ffab40",
    bench=("#9fb0c0", "#8fa0b0", "#7d8f9f"),
    up="#3ddc84",
    down="#ff6f6f",
    neutral="#9fb0c0",
    grid="rgba(163, 182, 200, 0.20)",
    axis="rgba(163, 182, 200, 0.38)",
)

_active: Palette = LIGHT


def use_theme(kind: str | None) -> None:
    """Point the chart palette at the theme Streamlit is currently rendering."""
    global _active
    _active = DARK if str(kind or "").lower() == "dark" else LIGHT


def palette() -> Palette:
    return _active


def _layout(p: Palette) -> dict:
    return dict(
        template=p.template,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left",
                    x=0, title_text=""),
        font=dict(size=13),
        # Transparent so the chart sits on the app background in either theme.
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )


def _style(fig: go.Figure, title: str | None = None, y_title: str | None = None,
           y_prefix: str | None = None, y_suffix: str | None = None,
           legend: bool = False) -> go.Figure:
    p = palette()
    fig.update_layout(**_layout(p))
    # A horizontal legend sits just above the plot area, so the title needs its
    # own room in the margin above it or the two collide.
    fig.update_layout(margin=dict(l=10, r=10, t=86 if legend else 48, b=10))
    if title:
        fig.update_layout(title=dict(text=title, x=0, xanchor="left",
                                     yref="container", y=0.97, yanchor="top",
                                     font=dict(size=15)))
    fig.update_xaxes(showgrid=False, zeroline=False, showline=True,
                     linecolor=p.axis, ticks="outside", tickcolor=p.axis)
    fig.update_yaxes(showgrid=True, gridcolor=p.grid, zeroline=False,
                     title_text=y_title, tickprefix=y_prefix, ticksuffix=y_suffix)
    return fig


def price_history(main: pd.Series | None, main_label: str,
                  benchmarks: list[tuple[str, pd.Series]] | None = None,
                  title: str = "Home value history",
                  y_prefix: str = "$") -> go.Figure:
    """Selected region against its containing geographies."""
    p = palette()
    fig = go.Figure()
    for i, (label, s) in enumerate(benchmarks or []):
        if s is None or s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.to_numpy(), name=label, mode="lines",
            line=dict(color=p.bench[i % len(p.bench)], width=1.6, dash="dot"),
            hovertemplate="%{y:,.0f}<extra>" + label + "</extra>"))
    if main is not None and not main.empty:
        fig.add_trace(go.Scatter(
            x=main.index, y=main.to_numpy(), name=main_label, mode="lines",
            line=dict(color=p.primary, width=2.6), fill="tozeroy",
            fillcolor=p.primary_fill,
            hovertemplate="%{y:,.0f}<extra>" + main_label + "</extra>"))
        fig.update_yaxes(range=[0, float(main.max()) * 1.18])
    return _style(fig, title, y_prefix=y_prefix, legend=True)


def yoy_bars(s: pd.Series | None, title: str = "Year-over-year change",
             years: int = 8) -> go.Figure:
    """Signed YoY change - green above zero, red below."""
    p = palette()
    fig = go.Figure()
    if s is not None and not s.empty:
        cutoff = s.index.max() - pd.DateOffset(years=years)
        s = s[s.index >= cutoff]
        colors = [p.up if v >= 0 else p.down for v in s]
        fig.add_trace(go.Bar(
            x=s.index, y=s.to_numpy(), marker_color=colors, name="YoY %",
            hovertemplate="%{y:+.1f}%<extra></extra>"))
        fig.add_hline(y=0, line_width=1, line_color=p.neutral)
    return _style(fig, title, y_suffix="%")


def indexed_comparison(series_map: dict[str, pd.Series], start: pd.Timestamp,
                       title: str = "Growth compared",
                       highlight: str | None = None) -> go.Figure:
    """Multiple regions rebased to 100 at a common start date."""
    p = palette()
    fig = go.Figure()
    bench_i = 0
    for label, s in series_map.items():
        if s is None or s.empty:
            continue
        is_main = (label == highlight)
        fig.add_trace(go.Scatter(
            x=s.index, y=s.to_numpy(), name=label, mode="lines",
            line=dict(color=p.primary if is_main else p.bench[bench_i % len(p.bench)],
                      width=2.6 if is_main else 1.6,
                      dash=None if is_main else "dot"),
            hovertemplate="%{y:,.1f}<extra>" + label + "</extra>"))
        if not is_main:
            bench_i += 1
    fig.add_hline(y=100, line_width=1, line_color=p.neutral, line_dash="dash")
    return _style(fig, f"{title} (indexed to 100 at {start:%b %Y})", legend=True)


def dual_axis(left: pd.Series | None, left_label: str,
              right: pd.Series | None, right_label: str,
              title: str, left_prefix: str = "", right_suffix: str = "") -> go.Figure:
    """Two related supply/demand series that share a time axis."""
    p = palette()
    fig = go.Figure()
    if left is not None and not left.empty:
        fig.add_trace(go.Scatter(
            x=left.index, y=left.to_numpy(), name=left_label, mode="lines",
            line=dict(color=p.primary, width=2.4),
            hovertemplate="%{y:,.0f}<extra>" + left_label + "</extra>"))
    if right is not None and not right.empty:
        fig.add_trace(go.Scatter(
            x=right.index, y=right.to_numpy(), name=right_label, mode="lines",
            yaxis="y2", line=dict(color=p.accent, width=2.0),
            hovertemplate="%{y:,.1f}<extra>" + right_label + "</extra>"))
    fig.update_layout(
        yaxis=dict(title=left_label, tickprefix=left_prefix, gridcolor=p.grid),
        yaxis2=dict(title=right_label, overlaying="y", side="right",
                    showgrid=False, ticksuffix=right_suffix))
    return _style(fig, title, legend=True)


def scanner_scatter(df: pd.DataFrame, x: str, y: str, label_col: str,
                    size_col: str | None = None, x_title: str = "",
                    y_title: str = "", title: str = "") -> go.Figure:
    """Level vs momentum scatter for the national scanner."""
    p = palette()
    fig = go.Figure()
    if df.empty:
        return _style(fig, title)
    colors = [p.up if v >= 0 else p.down for v in df[y]]
    sizes: object = 12
    if size_col and size_col in df:
        raw = pd.to_numeric(df[size_col], errors="coerce").fillna(0.0)
        span = float(raw.max() - raw.min())
        if span > 0:
            sizes = (8 + 22 * ((raw - raw.min()) / span)).to_numpy()
    fig.add_trace(go.Scatter(
        x=df[x], y=df[y], mode="markers", text=df[label_col],
        marker=dict(color=colors, size=sizes, opacity=0.8,
                    line=dict(width=0.5, color=p.grid)),
        hovertemplate="<b>%{text}</b><br>%{x:,.0f}<br>%{y:+.1f}%<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color=p.neutral, line_dash="dash")
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title_text=x_title)
    return _style(fig, title, y_title=y_title, y_suffix="%")


def ranked_bars(df: pd.DataFrame, value_col: str, label_col: str,
                title: str = "", suffix: str = "%") -> go.Figure:
    """Horizontal ranking of regions by a signed metric."""
    p = palette()
    fig = go.Figure()
    if df.empty:
        return _style(fig, title)
    d = df.iloc[::-1]  # plotly draws horizontal bars bottom-up
    colors = [p.up if v >= 0 else p.down for v in d[value_col]]
    fig.add_trace(go.Bar(
        x=d[value_col], y=d[label_col], orientation="h", marker_color=colors,
        hovertemplate="<b>%{y}</b><br>%{x:+.1f}" + suffix + "<extra></extra>"))
    fig.update_layout(height=max(280, 26 * len(d) + 90), hovermode="closest")
    fig.update_yaxes(automargin=True)
    return _style(fig, title)


def simple_line(s: pd.Series | None, title: str, y_prefix: str = "",
                y_suffix: str = "", color: str | None = None,
                fill: bool = False) -> go.Figure:
    p = palette()
    fig = go.Figure()
    if s is not None and not s.empty:
        fig.add_trace(go.Scatter(
            x=s.index, y=s.to_numpy(), mode="lines",
            line=dict(color=color or p.primary, width=2.4),
            fill="tozeroy" if fill else None, fillcolor=p.primary_fill,
            hovertemplate="%{y:,.2f}<extra></extra>", showlegend=False))
    return _style(fig, title, y_prefix=y_prefix or None, y_suffix=y_suffix or None)


def comparison_bars(labels: list[str], values: list[float], title: str,
                    highlight_index: int = 0, suffix: str = "",
                    prefix: str = "") -> go.Figure:
    """One region against its benchmarks for a single indicator."""
    p = palette()
    fig = go.Figure()
    colors = [p.primary if i == highlight_index else p.bench[1]
              for i in range(len(labels))]
    fig.add_trace(go.Bar(
        x=labels, y=values, marker_color=colors,
        hovertemplate="<b>%{x}</b><br>%{y:,.1f}<extra></extra>"))
    fig.update_layout(height=300, hovermode="closest", showlegend=False)
    return _style(fig, title, y_prefix=prefix or None, y_suffix=suffix or None)
