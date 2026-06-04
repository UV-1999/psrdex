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

try:
    import astropy.units as u
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
    from astropy.time import Time
except Exception:  # pragma: no cover - app handles missing optional runtime deps.
    AltAz = None
    EarthLocation = None
    SkyCoord = None
    Time = None
    get_sun = None
    u = None


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


def page_setup() -> None:
    st.set_page_config(page_title="PSRDEX", page_icon=".", layout="wide")
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
        div[data-testid="stMetric"] { background: #f8f9fb; border: 1px solid #e4e7ec; padding: 0.75rem; }
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
    ]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "datetime_utc" in df:
        df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], errors="coerce", utc=True)
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


def local_positions(observations: pd.DataFrame, atnf: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=["pulsar", "ra_deg", "dec_deg", "n_files", "duration_hours"])

    summary = (
        observations.groupby("pulsar", dropna=False)
        .agg(
            n_files=("path", "count"),
            duration_hours=("duration_sec", lambda values: pd.to_numeric(values, errors="coerce").sum() / 3600),
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


def ppdot_figure(atnf: pd.DataFrame, selected: str | None) -> go.Figure:
    fig = go.Figure()
    if not atnf.empty and {"PSRJ", "P0", "P1"}.issubset(atnf.columns):
        df = atnf.dropna(subset=["P0", "P1"]).copy()
        fig = px.scatter(
            df,
            x="P0",
            y="P1",
            hover_name="PSRJ",
            custom_data=["PSRJ"],
            log_x=True,
            log_y=True,
            color=df["PSRJ"].eq(selected).map({True: "Selected", False: "Local"}),
            color_discrete_map={"Selected": "#d62728", "Local": "#2f6f9f"},
            labels={"P0": "Period P (s)", "P1": "Pdot (s/s)", "color": ""},
        )
    fig.update_layout(
        height=460,
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def sky_figure(positions: pd.DataFrame, selected: str | None) -> go.Figure:
    fig = go.Figure()
    if not positions.empty:
        ra = np.deg2rad(positions["ra_deg"].to_numpy())
        dec = np.deg2rad(positions["dec_deg"].to_numpy())
        x = np.cos(dec) * np.cos(ra)
        y = np.cos(dec) * np.sin(ra)
        z = np.sin(dec)
        colors = np.where(positions["pulsar"].to_numpy() == selected, "#d62728", "#2f6f9f")

        fig.add_trace(
            go.Scatter3d(
                x=x,
                y=y,
                z=z,
                mode="markers",
                marker=dict(size=6, color=colors, opacity=0.9),
                text=positions["pulsar"],
                customdata=positions[["pulsar", "n_files", "duration_hours"]].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "files=%{customdata[1]}<br>"
                    "hours=%{customdata[2]:.2f}<extra></extra>"
                ),
            )
        )

        theta = np.linspace(0, 2 * np.pi, 72)
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
    fig.update_layout(
        height=460,
        margin=dict(l=0, r=0, t=20, b=0),
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectmode="cube",
        ),
        showlegend=False,
    )
    return fig


def selected_from_plot(event: Any) -> str | None:
    try:
        points = event.selection.points
    except AttributeError:
        if isinstance(event, dict):
            points = event.get("selection", {}).get("points", [])
        else:
            points = []
    if not points:
        return None
    point = points[0]
    if isinstance(point, dict):
        customdata = point.get("customdata")
    else:
        customdata = getattr(point, "customdata", None)
    if isinstance(customdata, (list, tuple, np.ndarray)) and len(customdata):
        return str(customdata[0])
    return None


def format_hours(seconds: float | int | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "0.00"
    return f"{float(seconds) / 3600:.2f}"


def sun_separation_plot(selected_df: pd.DataFrame, pulsar_row: pd.Series | None) -> go.Figure:
    fig = go.Figure()
    if (
        selected_df.empty
        or pulsar_row is None
        or SkyCoord is None
        or Time is None
        or get_sun is None
        or u is None
    ):
        return fig

    ra_deg = sexagesimal_to_degrees(pulsar_row.get("ra_source"), is_ra=True)
    dec_deg = sexagesimal_to_degrees(pulsar_row.get("dec_source"), is_ra=False)
    times = selected_df["datetime_utc"].dropna()
    if ra_deg is None or dec_deg is None or times.empty:
        return fig

    try:
        skycoord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
        astropy_time = Time(times.dt.to_pydatetime())
        sun = get_sun(astropy_time)
        separation = skycoord.separation(sun).deg
    except Exception:
        return fig

    fig.add_trace(
        go.Scatter(
            x=times,
            y=separation,
            mode="markers+lines",
            marker=dict(color="#2f6f9f", size=7),
        )
    )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Observation UTC",
        yaxis_title="Sun separation (deg)",
    )
    return fig


def telescope_track_plot(selected_df: pd.DataFrame, pulsar_row: pd.Series | None) -> go.Figure:
    settings = load_settings()
    fig = go.Figure()
    if (
        selected_df.empty
        or pulsar_row is None
        or SkyCoord is None
        or EarthLocation is None
        or AltAz is None
        or Time is None
        or u is None
        or settings.telescope_lat_deg is None
        or settings.telescope_lon_deg is None
    ):
        return fig

    ra_deg = sexagesimal_to_degrees(pulsar_row.get("ra_source"), is_ra=True)
    dec_deg = sexagesimal_to_degrees(pulsar_row.get("dec_source"), is_ra=False)
    times = selected_df["datetime_utc"].dropna()
    if ra_deg is None or dec_deg is None or times.empty:
        return fig

    try:
        location = EarthLocation(
            lat=settings.telescope_lat_deg * u.deg,
            lon=settings.telescope_lon_deg * u.deg,
            height=(settings.telescope_height_m or 0) * u.m,
        )
        skycoord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
        frame = AltAz(obstime=Time(times.dt.to_pydatetime()), location=location)
        altaz = skycoord.transform_to(frame)
    except Exception:
        return fig

    fig.add_trace(
        go.Scatter(
            x=altaz.az.deg,
            y=altaz.alt.deg,
            mode="markers",
            marker=dict(
                color=times.astype("int64"),
                colorscale="Viridis",
                size=8,
                colorbar=dict(title="UTC"),
            ),
            text=times.astype(str),
            hovertemplate="az=%{x:.2f}<br>alt=%{y:.2f}<br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Azimuth (deg)",
        yaxis_title="Altitude (deg)",
    )
    return fig


def render_selected_pulsar(
    pulsar: str,
    observations: pd.DataFrame,
    positions: pd.DataFrame,
    atnf: pd.DataFrame,
) -> None:
    selected_df = observations[observations["pulsar"] == pulsar].copy()
    selected_df = selected_df.sort_values("mjd") if "mjd" in selected_df else selected_df
    position_rows = positions[positions["pulsar"] == pulsar]
    pulsar_row = position_rows.iloc[0] if not position_rows.empty else None

    total_seconds = selected_df["duration_sec"].fillna(0).sum() if "duration_sec" in selected_df else 0
    bands = sorted(str(band) for band in selected_df["band"].dropna().unique()) if "band" in selected_df else []
    first_date = selected_df["datetime_utc"].dropna().min() if "datetime_utc" in selected_df else None
    last_date = selected_df["datetime_utc"].dropna().max() if "datetime_utc" in selected_df else None

    st.subheader(pulsar)
    metric_cols = st.columns(4)
    metric_cols[0].metric("Files", f"{len(selected_df):,}")
    metric_cols[1].metric("Hours", format_hours(total_seconds))
    metric_cols[2].metric("Bands", ", ".join(bands) if bands else "unknown")
    metric_cols[3].metric(
        "Date Range",
        " - ".join(
            [
                first_date.strftime("%Y-%m-%d") if pd.notna(first_date) else "?",
                last_date.strftime("%Y-%m-%d") if pd.notna(last_date) else "?",
            ]
        ),
    )

    band_table = pd.DataFrame()
    if not selected_df.empty and "band" in selected_df:
        band_table = (
            selected_df.groupby("band", dropna=False)
            .agg(
                files=("path", "count"),
                hours=("duration_sec", lambda values: pd.to_numeric(values, errors="coerce").sum() / 3600),
                first_mjd=("mjd", "min"),
                last_mjd=("mjd", "max"),
            )
            .reset_index()
            .sort_values("band")
        )

    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("#### Band Coverage")
        st.dataframe(band_table, use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### ATNF Metadata")
        atnf_row = (
            atnf[atnf["PSRJ"] == pulsar].iloc[0].to_frame("value")
            if not atnf.empty and "PSRJ" in atnf and (atnf["PSRJ"] == pulsar).any()
            else pd.DataFrame()
        )
        st.dataframe(atnf_row, use_container_width=True)

    plot_cols = st.columns(2)
    with plot_cols[0]:
        st.markdown("#### Sun Separation")
        fig = sun_separation_plot(selected_df, pulsar_row)
        if fig.data:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sun-separation data are unavailable for this selection.")
    with plot_cols[1]:
        st.markdown("#### Telescope Track")
        fig = telescope_track_plot(selected_df, pulsar_row)
        if fig.data:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Telescope track data need valid coordinates and observation times.")

    if "snr" in selected_df and selected_df["snr"].notna().any():
        st.markdown("#### SNR")
        snr_fig = px.scatter(
            selected_df.dropna(subset=["snr"]),
            x="datetime_utc",
            y="snr",
            color="band",
            hover_data=["file_name", "freq_mhz", "bandwidth_mhz"],
            labels={"datetime_utc": "Observation UTC", "snr": "SNR"},
        )
        snr_fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(snr_fig, use_container_width=True)

    st.markdown("#### Files")
    file_columns = [
        column
        for column in [
            "datetime_utc",
            "band",
            "duration_sec",
            "freq_mhz",
            "bandwidth_mhz",
            "mjd",
            "dm",
            "period_sec",
            "file_name",
            "path",
        ]
        if column in selected_df
    ]
    st.dataframe(selected_df[file_columns], use_container_width=True, hide_index=True)


def main() -> None:
    page_setup()
    settings = load_settings()
    output_dir = Path(os.getenv("PSRDEX_OUTPUT_DIR", str(settings.output_dir))).expanduser().resolve()
    update_state = maybe_start_background_update(
        settings,
        output_dir,
        pythonpath_prefix=SRC,
        cwd=ROOT,
    )

    observations = load_observations(str(output_dir))
    st.title("PSRDEX")

    if observations.empty:
        st.warning(f"No catalog found at {output_dir / 'observations.csv'}")
        st.caption(f"Update {update_state}. Log: {output_dir / 'background_update.log'}")
        return

    pulsars = tuple(sorted(observations["pulsar"].dropna().astype(str).unique()))
    atnf = load_atnf(pulsars)
    positions = local_positions(observations, atnf)

    with st.sidebar:
        st.header("Catalog")
        st.metric("Pulsars", f"{len(pulsars):,}")
        st.metric("Files", f"{len(observations):,}")
        total_hours = observations["duration_sec"].fillna(0).sum() / 3600
        st.metric("Hours", f"{total_hours:.1f}")
        st.caption(f"Update {update_state}")
        selected = st.selectbox("Pulsar", pulsars, index=0 if pulsars else None)
        bands = sorted(str(band) for band in observations["band"].dropna().unique())
        active_bands = st.multiselect("Bands", bands, default=bands)

    filtered = observations[observations["band"].astype(str).isin(active_bands)] if active_bands else observations
    filtered_pulsars = tuple(sorted(filtered["pulsar"].dropna().astype(str).unique()))
    filtered_atnf = atnf[atnf["PSRJ"].isin(filtered_pulsars)] if not atnf.empty and "PSRJ" in atnf else atnf
    filtered_positions = local_positions(filtered, filtered_atnf)

    top_left, top_right = st.columns(2)
    with top_left:
        st.markdown("#### P-Pdot")
        pp_event = st.plotly_chart(
            ppdot_figure(filtered_atnf, selected),
            use_container_width=True,
            key="ppdot",
            on_select="rerun",
            selection_mode="points",
        )
    with top_right:
        st.markdown("#### Sky")
        sky_event = st.plotly_chart(
            sky_figure(filtered_positions, selected),
            use_container_width=True,
            key="sky",
            on_select="rerun",
            selection_mode="points",
        )

    plot_selected = selected_from_plot(pp_event) or selected_from_plot(sky_event)
    if plot_selected in pulsars:
        selected = plot_selected

    render_selected_pulsar(selected, observations, positions, atnf)


if __name__ == "__main__":
    main()
