from __future__ import annotations

import math
import os
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
    "RAJ",
    "DECJ",
    "P0",
    "P1",
    "DM",
    "DIST",
    "AGE",
    "EDOT",
    "BINARY",
]

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


def band_sort_key(band: Any) -> tuple[int, str]:
    order = {"0b": 0, "1b": 1, "2b": 2, "3b": 3, "0c": 4, "1c": 5, "2c": 6, "3c": 7}
    text = str(band)
    return (order.get(text, 99), text)


def page_setup() -> None:
    st.set_page_config(page_title="PSRDEX", page_icon=".", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1480px;
            padding-top: 1.5rem;
            padding-bottom: 2.5rem;
        }
        h1 {
            margin-bottom: 0.15rem;
        }
        .psrdex-subtitle {
            color: #475467;
            font-size: 1.05rem;
            margin-bottom: 0.2rem;
        }
        .psrdex-updated {
            color: #667085;
            font-size: 0.9rem;
            margin-bottom: 1.25rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    if QueryATNF is None or not pulsars:
        return pd.DataFrame()
    try:
        query = QueryATNF(params=ATNF_PARAMS, psrs=list(pulsars))
        table = query.pandas
    except Exception:
        return pd.DataFrame()
    if table is None:
        return pd.DataFrame()

    df = table.copy()
    if "PSRJ" in df:
        df["PSRJ"] = df["PSRJ"].astype(str)
    for column in ["P0", "P1", "DM", "DIST", "AGE", "EDOT"]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


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
        [float(part) for part in parts]
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


def ppdot_figure(atnf: pd.DataFrame) -> go.Figure:
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
            color_discrete_sequence=["#2f6f9f"],
            labels={"P0": "Period P (s)", "P1": "Pdot (s/s)"},
        )
    fig.update_layout(
        title="P-Pdot Diagram",
        height=440,
        margin=dict(l=10, r=10, t=48, b=10),
        showlegend=False,
    )
    return fig


def sky_figure(positions: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    theta = np.linspace(0, 2 * np.pi, 160)
    fig.add_trace(
        go.Scatter3d(
            x=np.cos(theta),
            y=np.sin(theta),
            z=np.zeros_like(theta),
            mode="lines",
            line=dict(color="#101828", width=3),
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
                line=dict(color="#d0d5dd", width=1),
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
                marker=dict(size=5, color="#2f6f9f", opacity=0.88),
                customdata=positions[["pulsar", "n_files", "duration_hours"]].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "files=%{customdata[1]}<br>"
                    "hours=%{customdata[2]:.2f}<extra></extra>"
                ),
                showlegend=False,
            )
        )

    fig.update_layout(
        title="Equatorial Sky",
        height=440,
        margin=dict(l=0, r=0, t=48, b=0),
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectmode="cube",
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
    band: str,
) -> tuple[pd.DataFrame, str | None]:
    df = observations[observations["pulsar"].astype(str) == pulsar].copy()
    if band != "All bands" and "band" in df:
        df = df[df["band"].astype(str) == band]
    y_column = snr_column(df)
    if y_column is None:
        df["snr_for_plot"] = np.nan
    else:
        df["snr_for_plot"] = pd.to_numeric(df[y_column], errors="coerce")
    return df.sort_values("datetime_utc"), y_column


def observation_figure(df: pd.DataFrame, y_column: str | None) -> go.Figure:
    plot_df = df.dropna(subset=["datetime_utc"]).copy()
    if y_column is None:
        plot_df["snr_for_plot"] = 0.0

    fig = px.scatter(
        plot_df,
        x="datetime_utc",
        y="snr_for_plot",
        color="band_label" if "band_label" in plot_df else None,
        custom_data=["row_id"],
        hover_data=[
            column
            for column in ["file_name", "band_label", "freq_mhz", "bandwidth_mhz", "dm", "period_sec"]
            if column in plot_df
        ],
        labels={"datetime_utc": "Time", "snr_for_plot": "Total SNR"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_traces(marker=dict(size=9, opacity=0.9))
    fig.update_layout(
        title="Observations",
        height=430,
        margin=dict(l=10, r=10, t=48, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    if y_column is None:
        fig.add_annotation(
            text="SNR is not available in the current catalog",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color="#667085", size=14),
        )
    return fig


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
                values.append((label, value))

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
            ("ATNF RAJ", "RAJ"),
            ("ATNF DECJ", "DECJ"),
            ("ATNF Distance", "DIST"),
            ("ATNF Age", "AGE"),
        ]:
            if column in atnf_row.index and pd.notna(atnf_row[column]):
                values.append((label, atnf_row[column]))

    return pd.DataFrame(values, columns=["field", "value"])


def main() -> None:
    page_setup()
    settings = load_settings()
    output_dir = Path(os.getenv("PSRDEX_OUTPUT_DIR", str(settings.output_dir))).expanduser().resolve()
    maybe_start_background_update(settings, output_dir, pythonpath_prefix=SRC, cwd=ROOT)

    observations = load_observations(str(output_dir))

    st.title("PSRDEX")
    st.markdown('<div class="psrdex-subtitle">Indexing tool for pulsars</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="psrdex-updated">Last updated: {latest_catalog_label(output_dir, observations)}</div>',
        unsafe_allow_html=True,
    )

    if observations.empty:
        st.warning(f"No catalog found at {output_dir / 'observations.csv'}")
        return

    pulsars = tuple(sorted(observations["pulsar"].dropna().astype(str).unique()))
    atnf = load_atnf(pulsars)
    positions = local_positions(observations, atnf)

    plot_left, plot_right = st.columns(2)
    with plot_left:
        st.plotly_chart(ppdot_figure(atnf), width="stretch")
    with plot_right:
        st.plotly_chart(sky_figure(positions), width="stretch")

    selector_left, selector_right = st.columns([2, 1])
    with selector_left:
        selected_pulsar = st.selectbox("Pulsar", pulsars, index=0)
    available_bands = ["All bands"]
    if "band" in observations:
        available_bands += sorted(
            observations["band"].dropna().astype(str).unique(),
            key=band_sort_key,
        )
    with selector_right:
        selected_band = st.selectbox(
            "Frequency band",
            available_bands,
            index=0,
            format_func=lambda value: value if value == "All bands" else band_label(value),
        )

    selected_df, y_column = filtered_observations(observations, selected_pulsar, selected_band)
    event = st.plotly_chart(
        observation_figure(selected_df, y_column),
        width="stretch",
        key="observation_snr",
        on_select="rerun",
        selection_mode="points",
    )

    row = selected_observation(selected_df, event)
    st.dataframe(metadata_table(row, atnf), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
