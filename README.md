# PSRDEX

PSRDEX is an incremental metadata pipeline and Streamlit browser for pulsar
observation archives. It is designed for a shared server where pulsar archive
files keep arriving in a fixed data directory and researchers need a lightweight
web interface for exploring what has already been observed.

The project has two parts:

- `psrdex-update`: a background-friendly command that scans the archive tree,
  extracts metadata from new or changed files using PSRCHIVE `vap`, stores the
  result in SQLite, and exports clean CSV catalogs.
- `app/streamlit_app.py`: a Streamlit application that reads those CSVs, joins
  local observations with ATNF metadata via `psrqpy`, and provides interactive
  plots and per-pulsar summaries. By default, the app also starts an incremental
  update in the background when it launches, then immediately displays whatever
  CSV data already exists.

## Repository Layout

```text
app/streamlit_app.py        Streamlit pulsar browser
src/psrdex/                 Incremental pipeline package
systemd/                    Example service/timer units
tests/                      Small unit tests for core parsing logic
```

## Install

Create a virtual environment on the server:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The pipeline also expects PSRCHIVE's `vap` command to be available on `PATH`.
For profile-derived SNR, it uses the PSRCHIVE Python bindings when available
and falls back to PSRCHIVE's `pdv` command.

## Configuration

Configuration is controlled through environment variables.

```bash
export PSRDEX_DATA_DIR=/QNAP/LOFAR/PL611
export PSRDEX_OUTPUT_DIR=/home/pmarmat/psrdex_catalog
export PSRDEX_GLOB="*.nop"
export PSRDEX_MAX_WORKERS=8
export PSRDEX_VAP_BIN=vap
export PSRDEX_PDV_BIN=pdv
```

These are also the built-in server defaults. The archive directory is only
scanned/read; PSRDEX writes its SQLite state, logs, and CSV catalogs under
`/home/pmarmat/psrdex_catalog`.

For telescope-frame plots in the Streamlit app, also set the observing site:

```bash
export PSRDEX_TELESCOPE_LAT_DEG=52.0
export PSRDEX_TELESCOPE_LON_DEG=17.0
export PSRDEX_TELESCOPE_HEIGHT_M=100
```

Use the actual station coordinates for scientific use.

## Frequency Lanes

PSRDEX displays the observing band using the local lane convention:

```text
HBA: 117-189 MHz
lane1b: 129 MHz, 117-141 MHz
lane2b: 153 MHz, 141-165 MHz
lane3b: 177 MHz, 165-189 MHz
lane0b: combined 1b+2b+3b

LBA: 44-80 MHz
lane1c: 50 MHz, 44-56 MHz
lane2c: 62 MHz, 56-68 MHz
lane3c: 74 MHz, 68-80 MHz
lane0c: combined 1c+2c+3c
```

## Run The Incremental Update

```bash
psrdex-update update
```

Useful variants:

```bash
psrdex-update update --dry-run
psrdex-update update --workers 4
psrdex-update update --retry-failures
psrdex-update update --force
psrdex-update export
psrdex-update status
```

The first run will process every matching archive file. Later runs process only
files that are new or whose size/mtime changed. SQLite is used as the canonical
state store, and CSVs are exported from SQLite after each successful update.

Default outputs under `PSRDEX_OUTPUT_DIR`:

```text
psrdex.sqlite              Canonical manifest and observation database
observations.csv           All processed observations
pulsar_summary.csv         One summary row per pulsar
pulsars/<PSRJ>.csv         One CSV per pulsar
failures.csv               Files that could not be processed
background_update.log      Output from app-triggered background updates
```

## Run The Streamlit App

```bash
streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

Users on the same LAN can open:

```text
http://<server-hostname-or-ip>:8501
```

When the app starts, it launches one non-blocking incremental update unless
another update is already running. Existing CSV files are loaded immediately, so
the dashboard remains usable while the first full scan is still processing.

To disable app-triggered background updates and rely only on cron/systemd:

```bash
export PSRDEX_APP_BACKGROUND_UPDATE=0
```

The app uses a one-hour cooldown between app-triggered scans to avoid repeated
updates from ordinary Streamlit reruns. To change it:

```bash
export PSRDEX_APP_UPDATE_COOLDOWN_SEC=3600
```

## First Server Test

On the server:

```bash
cd /home/pmarmat/psrdex
source .venv/bin/activate
pip install -e ".[dev]"
streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

Then watch the background update from another shell:

```bash
tail -f /home/pmarmat/psrdex_catalog/background_update.log
```

CSV outputs will appear here as processing completes:

```text
/home/pmarmat/psrdex_catalog/observations.csv
/home/pmarmat/psrdex_catalog/pulsars/
/home/pmarmat/psrdex_catalog/pulsar_summary.csv
```

The first run will take the longest because it must process the existing archive.
After that, only new or changed files are extracted.

## Weekly Scheduling

Example systemd units are provided in `systemd/`. Copy them to the appropriate
systemd user or system directory and edit the paths/environment values before
enabling them.

For a user-level weekly update:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/psrdex-update.service ~/.config/systemd/user/
cp systemd/psrdex-update.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now psrdex-update.timer
```

For the web app, adapt `systemd/psrdex-streamlit.service` and enable it through
systemd on the server.

## Notes

- Failed files are recorded and skipped on future runs unless their fingerprint
  changes or `--retry-failures` is used.
- The extractor records archive metadata available from `vap`. SNR is computed
  from the integrated pulse profile, not from the archive header: the profile is
  split into 10 phase-bin segments, the segment with the lowest mean power is
  treated as off-pulse, and SNR is `(I_max - mu_off) / sigma_off`. If an old
  catalog was built before this SNR extraction was enabled, run
  `psrdex-update update --force` to backfill it.
- Per-pulsar CSVs are exported from SQLite, so modified files replace their old
  metadata cleanly instead of causing duplicate rows.
