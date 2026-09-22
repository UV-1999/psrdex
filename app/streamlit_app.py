from __future__ import annotations

import contextlib
import html
import io
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psrdex.background import maybe_start_background_update  # noqa: E402
from psrdex.config import load_settings  # noqa: E402

try:
    from psrqpy import QueryATNF
except Exception:  # pragma: no cover - app handles missing optional runtime deps.
    QueryATNF = None


ATNF_PARAMS = [
    "PSRJ",
    "P0",
    "P1",
    "DM",
    "DIST",
    "AGE",
    "EDOT",
    "BINARY",
]

PLOT_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    "toImageButtonOptions": {
        "format": "svg",
        "filename": "psrdex-plot",
        "height": 1000,
        "width": 1600,
        "scale": 1,
    },
}

PLOT_FONT = "Segoe UI, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
PLOT_BLUE = "#2f6fb1"
PLOT_ORANGE = "#ff8a1f"
PLOT_SELECTED = "#e11d48"
PLOT_TRANSPARENT = "rgba(0,0,0,0)"
SKY_GRID_COLOR = "#8b95a3"
SKY_TEXT_COLOR = "#8b95a3"
BAND_COLORS = {
    "0b": "#e11d48",
    "1b": "#f97316",
    "2b": "#16a34a",
    "3b": "#2563eb",
    "0c": "#7c3aed",
    "1c": "#dc2626",
    "2c": "#ea580c",
    "3c": "#059669",
}

BAND_INFO = {
    "1b": {
        "label": "lane1b: HBA 129 MHz (117-141 MHz)",
        "short": "lane1b",
        "receiver": "HBA",
        "center_mhz": 129,
        "range_mhz": "117-141 MHz",
    },
    "2b": {
        "label": "lane2b: HBA 153 MHz (141-165 MHz)",
        "short": "lane2b",
        "receiver": "HBA",
        "center_mhz": 153,
        "range_mhz": "141-165 MHz",
    },
    "3b": {
        "label": "lane3b: HBA 177 MHz (165-189 MHz)",
        "short": "lane3b",
        "receiver": "HBA",
        "center_mhz": 177,
        "range_mhz": "165-189 MHz",
    },
    "0b": {
        "label": "lane0b: HBA combined 1b+2b+3b (117-189 MHz)",
        "short": "lane0b",
        "receiver": "HBA",
        "center_mhz": None,
        "range_mhz": "117-189 MHz",
    },
    "1c": {
        "label": "lane1c: LBA 50 MHz (44-56 MHz)",
        "short": "lane1c",
        "receiver": "LBA",
        "center_mhz": 50,
        "range_mhz": "44-56 MHz",
    },
    "2c": {
        "label": "lane2c: LBA 62 MHz (56-68 MHz)",
        "short": "lane2c",
        "receiver": "LBA",
        "center_mhz": 62,
        "range_mhz": "56-68 MHz",
    },
    "3c": {
        "label": "lane3c: LBA 74 MHz (68-80 MHz)",
        "short": "lane3c",
        "receiver": "LBA",
        "center_mhz": 74,
        "range_mhz": "68-80 MHz",
    },
    "0c": {
        "label": "lane0c: LBA combined 1c+2c+3c (44-80 MHz)",
        "short": "lane0c",
        "receiver": "LBA",
        "center_mhz": None,
        "range_mhz": "44-80 MHz",
    },
}


def band_label(band: Any) -> str:
    return BAND_INFO.get(str(band), {}).get("label", str(band))


def band_physical_label(band: Any) -> str:
    info = BAND_INFO.get(str(band))
    if info is None:
        return str(band)
    center = "combined" if info["center_mhz"] is None else f'{info["center_mhz"]} MHz'
    return f'{info["short"]} {center} ({info["range_mhz"]})'


def band_color(band: Any) -> str:
    return BAND_COLORS.get(str(band), PLOT_BLUE)


def band_sort_key(band: Any) -> tuple[int, str]:
    order = {"0b": 0, "1b": 1, "2b": 2, "3b": 3, "0c": 4, "1c": 5, "2c": 6, "3c": 7}
    text = str(band)
    return (order.get(text, 99), text)


def is_pulsar_name(value: Any) -> bool:
    return bool(re.match(r"^J\d{4}[+-]\d+", str(value)))


def page_setup() -> None:
    st.set_page_config(page_title="PSRDEX", page_icon=".", layout="wide")


@st.cache_data(show_spinner=False)
def load_observations(output_dir: str) -> pd.DataFrame:
    path = Path(output_dir) / "observations.csv"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    for column in [
        "mjd",
        "freq_mhz",
        "bandwidth_mhz",
        "duration_sec",
        "period_sec",
        "dm",
        "snr",
        "total_snr",
    ]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "datetime_utc" in df:
        df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], errors="coerce", utc=True)
    if "band" in df:
        df["band_label"] = df["band"].map(band_label)
    df["row_id"] = np.arange(len(df)).astype(str)
    return df


@st.cache_data(show_spinner=False, ttl=86400)
def load_atnf(pulsars: tuple[str, ...]) -> pd.DataFrame:
    atnf_pulsars = tuple(pulsar for pulsar in pulsars if re.match(r"^J\d{4}[+-]\d+", pulsar))
    if QueryATNF is None or not atnf_pulsars:
        return pd.DataFrame()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            query = QueryATNF(params=ATNF_PARAMS, psrs=list(atnf_pulsars))
            table = query.pandas
    except Exception:
        return pd.DataFrame()
    if table is None:
        return pd.DataFrame()

    df = table.copy()
    for column in df.columns:
        df[column] = df[column].map(scalar_display_value)
    if "PSRJ" in df:
        df["PSRJ"] = df["PSRJ"].astype(str)
    for column in ["P0", "P1", "DM", "DIST", "AGE", "EDOT"]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def scalar_display_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "to_string"):
        try:
            rendered = value.to_string(sep=":", precision=8)
            if not isinstance(rendered, (list, tuple, np.ndarray)):
                return str(rendered)
            value = rendered
        except Exception:
            pass

    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        flattened = flatten_for_display(value)
        if len(flattened) <= 4:
            return ":".join(flattened)
        return ", ".join(flattened)

    return str(value).replace("\n", " ")


def metadata_display_value(value: Any) -> str:
    value = scalar_display_value(value)
    if value is None:
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S UTC")
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value).replace("\n", " ")


def flatten_for_display(value: Any) -> list[str]:
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        flattened: list[str] = []
        for item in value:
            flattened.extend(flatten_for_display(item))
        return flattened
    text = str(value).strip()
    return [text] if text else []


def latest_catalog_label(output_dir: Path, observations: pd.DataFrame) -> str:
    if "processed_at_utc" in observations and observations["processed_at_utc"].notna().any():
        processed = pd.to_datetime(observations["processed_at_utc"], errors="coerce", utc=True)
        if processed.notna().any():
            return processed.max().strftime("%Y-%m-%d %H:%M UTC")

    catalog = output_dir / "observations.csv"
    if catalog.exists():
        modified = pd.Timestamp(catalog.stat().st_mtime, unit="s", tz="UTC")
        return modified.strftime("%Y-%m-%d %H:%M UTC")
    return "not available"


def format_compact_number(value: int | float) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}"
    return f"{int(value):,}"


def observation_date_range(observations: pd.DataFrame) -> str:
    if "datetime_utc" not in observations or observations["datetime_utc"].dropna().empty:
        return "unknown"
    dates = observations["datetime_utc"].dropna()
    return f"{dates.min().strftime('%Y-%m-%d')} to {dates.max().strftime('%Y-%m-%d')}"


def archive_extension(glob_pattern: str) -> str:
    match = re.search(r"\.([A-Za-z0-9]+)$", glob_pattern)
    return f".{match.group(1)}" if match else glob_pattern


def render_archive_overview(observations: pd.DataFrame, settings: Any) -> None:
    total_hours = observations["duration_sec"].fillna(0).sum() / 3600 if "duration_sec" in observations else 0
    exposure_years = total_hours / (24 * 365.25)
    dates = observations["datetime_utc"].dropna() if "datetime_utc" in observations else pd.Series(dtype="datetime64[ns]")
    since = dates.min().strftime("%Y") if not dates.empty else "unknown"

    with st.container(border=True):
        st.markdown(
            "POLFAR pulsar archive index for low-frequency observations from the "
            "[LOFAR](https://www.lofar.org/) network, maintained for the "
            "[Janusz Gil Institute of Astronomy](https://ia.uz.zgora.pl/) at the "
            "[University of Zielona Gora](https://www.uz.zgora.pl/). "
            "Author: Piyush Marmat."
        )

        columns = st.columns([1, 1, 1, 4])
        columns[0].metric("Pulsars", format_compact_number(observations["pulsar"].nunique()))
        with columns[1]:
            st.metric("Files", format_compact_number(len(observations)))
            st.write(f"Kopernik:{settings.data_dir}")
            st.write(f"extension: {archive_extension(settings.glob_pattern)}")
        with columns[2]:
            st.metric("Exposure", f"{total_hours:,.1f} h")
            st.write(f"{exposure_years:,.3f} yr | since {since}")

        st.write("POLFAR observing lanes")
        st.plotly_chart(band_plan_figure(), width="stretch", theme="streamlit", config=PLOT_CONFIG)


def band_edges_mhz(band: str) -> tuple[float, float]:
    info = BAND_INFO[band]
    match = re.match(r"(\d+)-(\d+) MHz", str(info["range_mhz"]))
    if match is None:
        return (math.nan, math.nan)
    return (float(match.group(1)), float(match.group(2)))


def band_plan_figure() -> go.Figure:
    fig = go.Figure()
    subbands = ["1c", "2c", "3c", "1b", "2b", "3b"]
    text_colors = {
        "1c": "#ffffff",
        "2c": "#ffffff",
        "3c": "#ffffff",
        "1b": "#ffffff",
        "2b": "#ffffff",
        "3b": "#ffffff",
    }
    y_labels = {
        "1c": "lane0c / LBA",
        "2c": "lane0c / LBA",
        "3c": "lane0c / LBA",
        "1b": "lane0b / HBA",
        "2b": "lane0b / HBA",
        "3b": "lane0b / HBA",
    }
    for band in subbands:
        low, high = band_edges_mhz(band)
        info = BAND_INFO[band]
        center = f'{info["center_mhz"]} MHz'
        fig.add_trace(
            go.Bar(
                x=[high - low],
                y=[y_labels[band]],
                base=[low],
                orientation="h",
                marker=dict(color=band_color(band), line=dict(width=0)),
                text=[f'{info["short"]}<br>{center}'],
                textposition="inside",
                textfont=dict(color=text_colors[band], size=11),
                insidetextanchor="middle",
                hovertemplate=f'{info["label"]}<extra></extra>',
                width=0.58,
                showlegend=False,
            )
        )

    fig.update_layout(
        height=275,
        barmode="overlay",
        bargap=0.24,
        paper_bgcolor=PLOT_TRANSPARENT,
        plot_bgcolor=PLOT_TRANSPARENT,
        margin=dict(l=95, r=24, t=12, b=56),
        xaxis=dict(
            title="Frequency (MHz)",
            range=[40, 193],
            tickmode="array",
            tickvals=[44, 56, 68, 80, 117, 141, 165, 189],
            showgrid=True,
            zeroline=False,
            showline=True,
            linecolor=SKY_GRID_COLOR,
            linewidth=2,
            ticks="outside",
            ticklen=6,
        ),
        yaxis=dict(
            title="",
            categoryorder="array",
            categoryarray=["lane0b / HBA", "lane0c / LBA"],
            fixedrange=True,
        ),
        font=dict(family=PLOT_FONT, size=12),
    )
    return fig


def section_header(eyebrow: str, title: str, metadata: str | None = None) -> None:
    st.divider()
    if title:
        st.subheader(title)
    if metadata:
        st.write(metadata)


def apply_plot_style(fig: go.Figure, *, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=PLOT_TRANSPARENT,
        plot_bgcolor=PLOT_TRANSPARENT,
        font=dict(family=PLOT_FONT, size=13),
        margin=dict(l=50, r=24, t=50, b=46),
        hoverlabel=dict(font=dict(family=PLOT_FONT, size=12)),
        modebar=dict(activecolor=PLOT_BLUE),
    )
    fig.update_xaxes(
        showgrid=True,
        zeroline=False,
        tickfont=dict(size=12),
        title=dict(font=dict(size=14)),
    )
    fig.update_yaxes(
        showgrid=True,
        zeroline=False,
        tickfont=dict(size=12),
        title=dict(font=dict(size=14)),
    )
    return fig


def re_split_angle(text: str) -> list[str]:
    cleaned = (
        text.replace("h", ":")
        .replace("m", ":")
        .replace("s", "")
        .replace("d", ":")
        .replace("'", ":")
        .replace('"', "")
    )
    parts = [part for part in cleaned.replace(" ", ":").split(":") if part]
    try:
        for part in parts:
            float(part)
    except ValueError:
        return []
    return parts


def sexagesimal_to_degrees(value: Any, *, is_ra: bool) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        number = float(text)
        return number * 15 if is_ra and abs(number) <= 24 else number
    except ValueError:
        pass

    parts = re_split_angle(text)
    if not parts:
        return None
    sign = -1 if parts[0].startswith("-") else 1
    first = abs(float(parts[0]))
    minutes = float(parts[1]) if len(parts) > 1 else 0.0
    seconds = float(parts[2]) if len(parts) > 2 else 0.0
    degrees = first + minutes / 60 + seconds / 3600
    if is_ra:
        degrees *= 15
        sign = 1
    return sign * degrees


def local_positions(observations: pd.DataFrame, atnf: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=["pulsar", "ra_deg", "dec_deg", "n_files", "duration_hours"])

    summary = (
        observations.groupby("pulsar", dropna=False)
        .agg(
            n_files=("row_id", "count"),
            duration_hours=(
                "duration_sec",
                lambda values: pd.to_numeric(values, errors="coerce").sum() / 3600,
            ),
            ra=("ra", "first"),
            dec=("dec", "first"),
        )
        .reset_index()
    )

    if not atnf.empty and {"PSRJ", "RAJ", "DECJ"}.issubset(atnf.columns):
        summary = summary.merge(
            atnf[["PSRJ", "RAJ", "DECJ"]].drop_duplicates("PSRJ"),
            left_on="pulsar",
            right_on="PSRJ",
            how="left",
        )
        summary["ra_source"] = summary["RAJ"].fillna(summary["ra"])
        summary["dec_source"] = summary["DECJ"].fillna(summary["dec"])
    else:
        summary["ra_source"] = summary["ra"]
        summary["dec_source"] = summary["dec"]

    summary["ra_deg"] = summary["ra_source"].map(lambda value: sexagesimal_to_degrees(value, is_ra=True))
    summary["dec_deg"] = summary["dec_source"].map(lambda value: sexagesimal_to_degrees(value, is_ra=False))
    return summary.dropna(subset=["ra_deg", "dec_deg"])


def ppdot_figure(atnf: pd.DataFrame, selected_pulsar: str) -> go.Figure:
    fig = go.Figure()
    if not atnf.empty and {"PSRJ", "P0", "P1"}.issubset(atnf.columns):
        df = atnf.dropna(subset=["P0", "P1"]).copy()
        fig = px.scatter(
            df,
            x="P0",
            y="P1",
            hover_name="PSRJ",
            log_x=True,
            log_y=True,
            color_discrete_sequence=[PLOT_BLUE],
            labels={"P0": "Period P (s)", "P1": "Pdot (s/s)"},
        )
        selected = df[df["PSRJ"].astype(str) == selected_pulsar]
        if not selected.empty:
            fig.add_trace(
                go.Scatter(
                    x=selected["P0"],
                    y=selected["P1"],
                    mode="markers",
                    marker=dict(
                        color=PLOT_SELECTED,
                        size=17,
                        symbol="star",
                        line=dict(color="#111827", width=1.4),
                    ),
                    hovertemplate=f"<b>{html.escape(selected_pulsar)}</b><extra></extra>",
                    showlegend=False,
                )
            )
    else:
        fig.add_annotation(
            text="ATNF P/Pdot unavailable",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14),
        )
    fig.update_layout(title="P-Pdot Diagram", showlegend=False)
    return apply_plot_style(fig, height=440)


def sky_figure(positions: pd.DataFrame, selected_pulsar: str) -> go.Figure:
    fig = go.Figure()

    surface_theta = np.linspace(0, 2 * np.pi, 72)
    surface_phi = np.linspace(0, np.pi, 36)
    theta_grid, phi_grid = np.meshgrid(surface_theta, surface_phi)
    sphere_x = np.sin(phi_grid) * np.cos(theta_grid)
    sphere_y = np.sin(phi_grid) * np.sin(theta_grid)
    sphere_z = np.cos(phi_grid)
    fig.add_trace(
        go.Surface(
            x=sphere_x,
            y=sphere_y,
            z=sphere_z,
            surfacecolor=np.zeros_like(sphere_x),
            colorscale=[[0, "#c7ced8"], [1, "#c7ced8"]],
            opacity=0.34,
            showscale=False,
            hoverinfo="skip",
            lighting=dict(ambient=0.78, diffuse=0.52, roughness=0.9, specular=0.08),
            showlegend=False,
        )
    )

    theta = np.linspace(0, 2 * np.pi, 160)
    for axis_x, axis_y, axis_z in [
        ([-1.08, 1.08], [0, 0], [0, 0]),
        ([0, 0], [-1.08, 1.08], [0, 0]),
        ([0, 0], [0, 0], [-1.08, 1.08]),
    ]:
        fig.add_trace(
            go.Scatter3d(
                x=axis_x,
                y=axis_y,
                z=axis_z,
                mode="lines",
                line=dict(color=SKY_GRID_COLOR, width=3),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Scatter3d(
            x=np.cos(theta),
            y=np.sin(theta),
            z=np.zeros_like(theta),
            mode="lines",
            line=dict(color=SKY_GRID_COLOR, width=4),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    for longitude in np.linspace(0, np.pi, 6, endpoint=False):
        fig.add_trace(
            go.Scatter3d(
                x=np.cos(longitude) * np.cos(theta),
                y=np.sin(longitude) * np.cos(theta),
                z=np.sin(theta),
                mode="lines",
                line=dict(color=SKY_GRID_COLOR, width=1.6),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    for z_level in np.linspace(-0.75, 0.75, 5):
        radius = math.sqrt(1 - z_level**2)
        fig.add_trace(
            go.Scatter3d(
                x=radius * np.cos(theta),
                y=radius * np.sin(theta),
                z=np.full_like(theta, z_level),
                mode="lines",
                line=dict(color=SKY_GRID_COLOR, width=1.6),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    ra_label_angles = np.deg2rad([0, 90, 180, 270])
    ra_label_text = ["RA 0h", "RA 6h", "RA 12h", "RA 18h"]
    fig.add_trace(
        go.Scatter3d(
            x=1.16 * np.cos(ra_label_angles),
            y=1.16 * np.sin(ra_label_angles),
            z=np.zeros_like(ra_label_angles),
            mode="text",
            text=ra_label_text,
            textfont=dict(color=SKY_TEXT_COLOR, size=11),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    dec_levels = [-60, -30, 0, 30, 60]
    fig.add_trace(
        go.Scatter3d(
            x=[-1.18] * len(dec_levels),
            y=[0] * len(dec_levels),
            z=[math.sin(math.radians(dec)) for dec in dec_levels],
            mode="text",
            text=[f"DEC {dec:+d}°" for dec in dec_levels],
            textfont=dict(color=SKY_TEXT_COLOR, size=10),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    if not positions.empty:
        ra = np.deg2rad(positions["ra_deg"].to_numpy())
        dec = np.deg2rad(positions["dec_deg"].to_numpy())
        fig.add_trace(
            go.Scatter3d(
                x=np.cos(dec) * np.cos(ra),
                y=np.cos(dec) * np.sin(ra),
                z=np.sin(dec),
                mode="markers",
                marker=dict(size=5, color=PLOT_BLUE, opacity=0.72, line=dict(color=SKY_GRID_COLOR, width=0.8)),
                customdata=positions[["pulsar", "n_files", "duration_hours"]].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "files=%{customdata[1]}<br>"
                    "hours=%{customdata[2]:.2f}<extra></extra>"
                ),
                showlegend=False,
            )
        )
        selected = positions[positions["pulsar"].astype(str) == selected_pulsar]
        if not selected.empty:
            selected_ra = math.radians(float(selected.iloc[0]["ra_deg"]))
            selected_dec = math.radians(float(selected.iloc[0]["dec_deg"]))
            fig.add_trace(
                go.Scatter3d(
                    x=[math.cos(selected_dec) * math.cos(selected_ra)],
                    y=[math.cos(selected_dec) * math.sin(selected_ra)],
                    z=[math.sin(selected_dec)],
                    mode="markers+text",
                    marker=dict(size=10, color=PLOT_SELECTED, opacity=1.0, line=dict(color=SKY_GRID_COLOR, width=1.4)),
                    text=[selected_pulsar],
                    textposition="top center",
                    textfont=dict(color=SKY_TEXT_COLOR, size=11),
                    hovertemplate=f"<b>{html.escape(selected_pulsar)}</b><extra></extra>",
                    showlegend=False,
                )
            )

    fig.update_layout(
        title="Equatorial Sky",
        height=440,
        paper_bgcolor=PLOT_TRANSPARENT,
        font=dict(family=PLOT_FONT, size=13),
        margin=dict(l=0, r=0, t=48, b=0),
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectmode="cube",
            bgcolor=PLOT_TRANSPARENT,
        ),
        showlegend=False,
    )
    return fig


def snr_column(df: pd.DataFrame) -> str | None:
    for column in ["total_snr", "snr", "SNR", "total_SNR"]:
        if column in df and pd.to_numeric(df[column], errors="coerce").notna().any():
            return column
    return None


def filtered_observations(
    observations: pd.DataFrame,
    pulsar: str,
    bands: list[str],
) -> tuple[pd.DataFrame, str | None]:
    df = observations[observations["pulsar"].astype(str) == pulsar].copy()
    if "band" in df:
        df = df[df["band"].astype(str).isin(bands)]
    y_column = snr_column(df)
    if y_column is None:
        df["snr_for_plot"] = np.nan
    else:
        df["snr_for_plot"] = pd.to_numeric(df[y_column], errors="coerce")
    df["observation_time"] = observation_time_series(df)
    if "observation_time" in df:
        df = df.sort_values("observation_time")
    return df, y_column


def observation_time_series(df: pd.DataFrame) -> pd.Series:
    result = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
    if "datetime_utc" in df:
        result = pd.to_datetime(df["datetime_utc"], errors="coerce", utc=True)
    if "mjd" in df:
        mjd = pd.to_numeric(df["mjd"], errors="coerce")
        mjd_time = pd.to_datetime(mjd, unit="D", origin="1858-11-17", errors="coerce", utc=True)
        result = result.fillna(mjd_time)
    if "file_name" in df:
        filename_time = pd.to_datetime(
            df["file_name"].astype(str).str.extract(r"(\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2})", expand=False),
            format="%Y-%m-%d_%H:%M:%S",
            errors="coerce",
            utc=True,
        )
        result = result.fillna(filename_time)
    return result


def available_bands_for_pulsar(observations: pd.DataFrame, pulsar: str) -> list[str]:
    if "band" not in observations:
        return []
    df = observations[observations["pulsar"].astype(str) == pulsar]
    return sorted(df["band"].dropna().astype(str).unique(), key=band_sort_key)


def band_checkbox_key(pulsar: str, band: str) -> str:
    return f"band-filter::{pulsar}::{band}"


def active_band_values(available_bands: list[str], pulsar: str) -> list[str]:
    return [
        band
        for band in available_bands
        if st.session_state.get(band_checkbox_key(pulsar, band), True)
    ]


def compact_band_label(band: str) -> str:
    info = BAND_INFO.get(band)
    if info is None:
        return band
    if info["center_mhz"] is None:
        return f'{info["short"]} {info["receiver"]} combined'
    return f'{info["short"]} {info["receiver"]} {info["center_mhz"]} MHz'


def render_band_controls(available_bands: list[str], pulsar: str, selected_df: pd.DataFrame) -> None:
    st.write("Frequency lanes")
    if not available_bands:
        st.info("No frequency lane metadata found for this pulsar.")
        return

    columns = st.columns(min(4, len(available_bands)))
    for index, band in enumerate(available_bands):
        key = band_checkbox_key(pulsar, band)
        with columns[index % len(columns)]:
            st.checkbox(compact_band_label(band), value=st.session_state.get(key, True), key=key)

    summary = band_summary_table(selected_df)
    if summary.empty:
        st.info("No observations in the selected lanes.")
    else:
        st.dataframe(summary, width="stretch", hide_index=True)


def band_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "band" not in df:
        return pd.DataFrame(columns=["lane", "receiver", "files", "hours", "max_snr", "latest"])

    snr_values = pd.to_numeric(df["snr_for_plot"], errors="coerce") if "snr_for_plot" in df else pd.Series(dtype=float)
    rows: list[dict[str, Any]] = []
    for band in sorted(df["band"].dropna().astype(str).unique(), key=band_sort_key):
        lane = df[df["band"].astype(str) == band]
        info = BAND_INFO.get(band, {})
        lane_snr = pd.to_numeric(lane["snr_for_plot"], errors="coerce") if "snr_for_plot" in lane else snr_values.iloc[0:0]
        duration_hours = pd.to_numeric(lane.get("duration_sec", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() / 3600
        last_seen = ""
        if "observation_time" in lane and lane["observation_time"].notna().any():
            last_seen = lane["observation_time"].max().strftime("%Y-%m-%d")
        rows.append(
            {
                "lane": band_label(band),
                "receiver": str(info.get("receiver", "")),
                "files": len(lane),
                "hours": round(duration_hours, 2),
                "max_snr": metadata_display_value(lane_snr.max()) if lane_snr.notna().any() else "",
                "latest": last_seen,
            }
        )

    return pd.DataFrame(rows)


def observation_figure(df: pd.DataFrame, y_column: str | None) -> go.Figure:
    plot_df = df.dropna(subset=["observation_time"]).copy()
    if y_column is None:
        plot_df["snr_for_plot"] = 0.0
    if "band" in plot_df:
        plot_df["band_key"] = plot_df["band"].astype(str)

    fig = px.scatter(
        plot_df,
        x="observation_time",
        y="snr_for_plot",
        color="band_key" if "band_key" in plot_df else None,
        custom_data=["row_id"],
        hover_data=None,
        labels={"observation_time": "Time", "snr_for_plot": "Total SNR"},
        color_discrete_map={band: band_color(band) for band in plot_df["band_key"].unique()} if "band_key" in plot_df else None,
        category_orders={"band_key": sorted(plot_df["band_key"].unique(), key=band_sort_key)} if "band_key" in plot_df else None,
    )
    fig.update_traces(
        marker=dict(size=14, opacity=0.62, line=dict(color="#111827", width=0.6)),
        hoverinfo="none",
        hovertemplate=None,
        selected=dict(marker=dict(size=19, opacity=0.95)),
        unselected=dict(marker=dict(opacity=0.28)),
    )
    fig.update_layout(
        title="Observation SNR",
        showlegend=False,
    )
    if plot_df.empty:
        fig.add_annotation(
            text="No observations in the selected lanes",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14),
        )
    elif y_column is None:
        fig.add_annotation(
            text="SNR is not available in the current catalog",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14),
        )
    return apply_plot_style(fig, height=430)


def selected_row_id(event: Any) -> str | None:
    try:
        points = event.selection.points
    except AttributeError:
        points = event.get("selection", {}).get("points", []) if isinstance(event, dict) else []
    if not points:
        return None
    point = points[0]
    customdata = point.get("customdata") if isinstance(point, dict) else getattr(point, "customdata", None)
    if isinstance(customdata, (list, tuple, np.ndarray)) and len(customdata):
        return str(customdata[0])
    return None


def selected_observation(df: pd.DataFrame, event: Any) -> pd.Series | None:
    row_id = selected_row_id(event)
    if row_id is not None:
        matched = df[df["row_id"].astype(str) == row_id]
        if not matched.empty:
            return matched.iloc[0]
    if not df.empty:
        return df.sort_values("datetime_utc").iloc[-1]
    return None


def metadata_table(row: pd.Series | None, atnf: pd.DataFrame) -> pd.DataFrame:
    if row is None:
        return pd.DataFrame(columns=["field", "value"])

    values: list[tuple[str, Any]] = []
    for label, column in [
        ("Pulsar", "pulsar"),
        ("File name", "file_name"),
        ("Datetime UTC", "datetime_utc"),
        ("RA", "ra"),
        ("DEC", "dec"),
        ("Frequency band", "band_label"),
        ("Total SNR", "snr_for_plot"),
        ("DM", "dm"),
        ("Period", "period_sec"),
        ("MJD", "mjd"),
        ("Frequency MHz", "freq_mhz"),
        ("Bandwidth MHz", "bandwidth_mhz"),
        ("Duration sec", "duration_sec"),
        ("Path", "path"),
    ]:
        if column in row.index:
            value = row[column]
            if pd.notna(value):
                values.append((label, metadata_display_value(value)))

    band = str(row.get("band")) if "band" in row.index else ""
    info = BAND_INFO.get(band)
    if info is not None:
        values.extend(
            [
                ("Receiver", info["receiver"]),
                ("Lane", info["short"]),
                ("Lane range", info["range_mhz"]),
            ]
        )
        if info["center_mhz"] is not None:
            values.append(("Lane center", f"{info['center_mhz']} MHz"))

    pulsar = str(row.get("pulsar"))
    if not atnf.empty and "PSRJ" in atnf and (atnf["PSRJ"] == pulsar).any():
        atnf_row = atnf[atnf["PSRJ"] == pulsar].iloc[0]
        for label, column in [
            ("ATNF DM", "DM"),
            ("ATNF Period P0", "P0"),
            ("ATNF Pdot P1", "P1"),
            ("ATNF Distance", "DIST"),
            ("ATNF Age", "AGE"),
        ]:
            if column in atnf_row.index and pd.notna(atnf_row[column]):
                values.append((label, metadata_display_value(atnf_row[column])))

    return pd.DataFrame(values, columns=["field", "value"])


def render_pulsar_summary(pulsar: str, pulsar_rows: pd.DataFrame, selected_df: pd.DataFrame) -> None:
    hours = pd.to_numeric(pulsar_rows.get("duration_sec", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() / 3600
    bands = sorted(pulsar_rows.get("band", pd.Series(dtype=str)).dropna().astype(str).unique(), key=band_sort_key)
    plotted_snr = pd.to_numeric(selected_df.get("snr_for_plot", pd.Series(dtype=float)), errors="coerce")
    best_snr = metadata_display_value(plotted_snr.max()) if plotted_snr.notna().any() else "n/a"
    band_note = " | ".join(band_physical_label(band) for band in bands) if bands else "unknown"

    with st.container(border=True):
        columns = st.columns(4)
        columns[0].metric("Source", pulsar)
        columns[1].metric("Files", f"{len(pulsar_rows):,}", f"{hours:,.1f} h")
        columns[2].metric("Bands", f"{len(bands):,}")
        columns[2].caption(band_note)
        columns[3].metric("Best SNR", best_snr)


def render_selected_file_summary(row: pd.Series | None, selected_from_plot: bool) -> None:
    if row is None:
        st.info("No observation selected.")
        return
    status = "selected point" if selected_from_plot else "latest observation"
    st.write(status)
    st.write(metadata_display_value(row.get("file_name", "")))


def render_analysis_panel(row: pd.Series | None, selected_count: int) -> None:
    with st.container(border=True):
        st.write("PSRISM bridge")
        if row is None:
            st.write("No archive selected")
        else:
            st.write(metadata_display_value(row.get("file_name", "")))
            st.write(metadata_display_value(row.get("band_label", "")))
        state = "waiting" if row is None else "single-file ready"
        if selected_count > 1:
            state = f"{selected_count} epochs staged"
        st.write(state)
        options = [
            "Dynamic spectrum (--dspec)",
            "ACF (--acspec --zoom-acf)",
            "Secondary spectrum (--sspec --fit-arc)",
            "Integrated profile (--intpf)",
            "Tau scaling (--fit-alpha)",
            "Refractive estimates (--estimate-refractive)",
        ]
        columns = st.columns(3)
        for index, option in enumerate(options):
            columns[index % 3].checkbox(option, value=False, disabled=True, key=f"psrism_preview_{index}")


def main() -> None:
    page_setup()
    settings = load_settings()
    output_dir = Path(os.getenv("PSRDEX_OUTPUT_DIR", str(settings.output_dir))).expanduser().resolve()
    maybe_start_background_update(settings, output_dir, pythonpath_prefix=SRC, cwd=ROOT)

    observations = load_observations(str(output_dir))

    st.title("PSRDEX")
    st.write("Indexing tool for pulsars")
    st.write(f"Last updated: {latest_catalog_label(output_dir, observations)}")

    if observations.empty:
        st.warning(f"No catalog found at {output_dir / 'observations.csv'}")
        return

    observations = observations[observations["pulsar"].map(is_pulsar_name)].copy()
    if observations.empty:
        st.warning("No J-name pulsars were found in the current catalog.")
        return

    pulsars = tuple(sorted(observations["pulsar"].dropna().astype(str).unique()))
    if "selected_pulsar" not in st.session_state or st.session_state["selected_pulsar"] not in pulsars:
        st.session_state["selected_pulsar"] = pulsars[0]
    selected_pulsar = str(st.session_state["selected_pulsar"])

    atnf = load_atnf(pulsars)
    positions = local_positions(observations, atnf)
    render_archive_overview(observations, settings)

    st.divider()
    plot_left, plot_right = st.columns(2)
    with plot_left:
        with st.container(border=True):
            st.plotly_chart(ppdot_figure(atnf, selected_pulsar), width="stretch", theme="streamlit", config=PLOT_CONFIG)
    with plot_right:
        with st.container(border=True):
            st.plotly_chart(sky_figure(positions, selected_pulsar), width="stretch", theme="streamlit", config=PLOT_CONFIG)

    st.selectbox("Pulsar", pulsars, key="selected_pulsar")
    selected_pulsar = str(st.session_state["selected_pulsar"])
    pulsar_rows = observations[observations["pulsar"].astype(str) == selected_pulsar]

    available_bands = available_bands_for_pulsar(observations, selected_pulsar)
    selected_bands = active_band_values(available_bands, selected_pulsar)
    selected_df, y_column = filtered_observations(observations, selected_pulsar, selected_bands)
    render_pulsar_summary(selected_pulsar, pulsar_rows, selected_df)

    observation_col, metadata_col = st.columns([1.55, 1])
    with observation_col:
        with st.container(border=True):
            event = st.plotly_chart(
                observation_figure(selected_df, y_column),
                width="stretch",
                theme="streamlit",
                key="observation_snr",
                on_select="rerun",
                selection_mode="points",
                config=PLOT_CONFIG,
            )
            render_band_controls(available_bands, selected_pulsar, selected_df)

    selected_from_plot = selected_row_id(event) is not None
    row = selected_observation(selected_df, event)
    with metadata_col:
        with st.container(border=True):
            st.write("Observation metadata")
            render_selected_file_summary(row, selected_from_plot)
            st.dataframe(metadata_table(row, atnf), width="stretch", hide_index=True)

    section_header("Analysis bridge", "PSRISM Run Staging", "Whitelisted analysis products for the selected archive")
    render_analysis_panel(row, 1 if row is not None else 0)


if __name__ == "__main__":
    main()
