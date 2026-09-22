# PSRDEX React

PSRDEX is a browser dashboard for a local pulsar archive. It indexes
PSRCHIVE-readable observation files into a searchable catalog, lets a researcher
inspect archive coverage and observation quality by pulsar, and provides a
controlled GUI for launching PSRISM interstellar-medium analysis jobs.

This repository is the React/FastAPI refactor of the original Streamlit PSRDEX
prototype. The older Streamlit project at `/home/piyushmarmat/PhD/PSRDEX/psrdex` is left
intact and remains the source of the existing indexing package and
`psrdex-update` command.

## What PSRDEX Does

PSRDEX has two layers:

- **Catalog indexing:** the existing PSRDEX backend scans a pulsar archive
  directory, extracts metadata from observation files, stores the results in
  SQLite, and exports CSV catalogs.
- **Dashboard and analysis launcher:** this React application reads the catalog
  through a FastAPI backend, presents a dashboard for browsing pulsars and
  observations, and launches PSRISM through a safe set of whitelisted options.

The dashboard is meant to answer practical archive questions quickly:

- Which pulsars are present in the local archive?
- How many observations exist for each pulsar?
- Which observing lanes/bands are available?
- What are the observing epochs, durations, SNR values, DM, period, frequency,
  bandwidth, RA/DEC, and source archive paths?
- Which selected archives should be passed into deeper PSRISM analysis?
- What plots, tables, and logs did a PSRISM run produce?

## Available Features

### PSRDEX Catalog Features

- Reads the existing PSRDEX catalog from `$PSRDEX_OUTPUT_DIR`.
- Uses the SQLite catalog when available, with CSV fallback.
- Shows catalog-level metrics:
  - number of pulsars;
  - number of indexed files;
  - total observing hours;
  - failed extraction count.
- Browses pulsars from a searchable selector.
- Displays per-pulsar observation timelines with total SNR on the y-axis.
- Colors observations by LOFAR-style observing lane.
- Filters observations by lane/band.
- Shows lane summary tables with file count, exposure hours, maximum SNR, and
  latest observation.
- Shows persistent metadata for selected observations.
- Can trigger `psrdex-update` from the API for a background catalog refresh.

### React Dashboard Features

- Vite React frontend adapted from the PulsarPReSPIDAR React template.
- FastAPI backend that exposes dashboard-ready JSON endpoints.
- Plotly-based observation timeline.
- Observation selection from both the timeline and a table.
- Multi-archive selection for PSRISM jobs.
- Modal PSRISM configuration window with product and parameter controls.
- PSRISM run history panel.
- Run-status polling.
- Dashboard display of generated PSRISM files:
  - PNG/JPEG plot thumbnails;
  - CSV output links;
  - text/log output links;
  - terminal log tail.

### PSRISM Integration Features

PSRISM is a command-line Python package for pulsar interstellar-medium analysis
from PSRCHIVE-readable archive files. PSRDEX does not reimplement PSRISM; it
calls the installed `psrism` command from the backend and writes every run into
`$PSRDEX_OUTPUT_DIR/psrism_runs/`.

The GUI currently exposes these PSRISM product choices:

- Inspect valid scrunching targets with `--inspect`.
- Dynamic spectrum with `--dspec`.
- Autocorrelation spectrum with `--acspec`.
- Zoomed autocorrelation spectrum with `--zoom-acf`.
- Secondary spectrum with `--sspec`.
- Secondary-spectrum parabolic arc fitting with `--fit-arc`.
- Integrated profile with `--intpf`.
- Scattering timescale fitting with `--fit-tau`.
- Scattering spectral index fitting with `--fit-alpha`.
- Anisotropic pulse-broadening fitting with `--fit-anisotropy`.
- Refractive scintillation estimates with `--estimate-refractive`.

The GUI currently exposes these PSRISM numeric/options inputs:

- `nsub`;
- `nchan`;
- `nbin`;
- `tau subbands`;
- distance in kpc;
- velocity in km/s;
- time-series parameter mode: `dm`, `tau`, `alpha`, `dnu_d`, `dt_d`, `t_r`, or
  `all`.

For single selected observations, PSRDEX launches PSRISM on the selected archive
path. For multiple selected observations, the backend creates a per-run
`selected_archives/` directory containing symlinks or copies to the exact files
selected in the dashboard, then runs PSRISM on that controlled directory.

## Important Directories

```text
psrdex-react/
  backend/                 FastAPI API for catalog browsing and PSRISM jobs
  frontend/                Vite React dashboard

$PSRDEX_OUTPUT_DIR/
  psrdex.sqlite            Existing PSRDEX catalog database
  observations.csv         Exported observation catalog
  pulsar_summary.csv       Exported per-pulsar summary
  failures.csv             Failed extraction records
  psrism_runs/             Dashboard-launched PSRISM runs
```

## Local Development

Backend:

```bash
cd /home/piyushmarmat/PhD/PSRDEX/dashboard/backend
pip install -e /home/piyushmarmat/PhD/PSRDEX/psrdex
pip install -e .[dev]
PSRDEX_OUTPUT_DIR=/home/piyushmarmat/PhD/PSRDEX/catalog \
  uvicorn psrdex_api.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd /home/piyushmarmat/PhD/PSRDEX/dashboard/frontend
npm install
VITE_PSRDEX_API_BASE=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1
```

Then open:

```text
http://127.0.0.1:5173/
```

## Useful API Endpoints

```text
GET  /api/health
GET  /api/catalog/overview
GET  /api/catalog/pulsars
GET  /api/catalog/pulsars/{pulsar}/observations
POST /api/catalog/update
GET  /api/psrism/runs
GET  /api/psrism/runs/{run_id}
GET  /api/psrism/runs/{run_id}/files/{relative_path}
POST /api/psrism/runs
```

## Safety Model

The PSRISM integration is intentionally not arbitrary shell access. The frontend
sends structured options to FastAPI, and the backend converts them into a
whitelisted `psrism` command. Original archive files are not modified. Generated
plots, CSVs, and logs stay under the run directory in
`$PSRDEX_OUTPUT_DIR/psrism_runs/`.

## Verification

Backend tests:

```bash
cd /home/piyushmarmat/PhD/PSRDEX/dashboard/backend
/home/piyushmarmat/PhD/PSRDEX/psrdex/.venv/bin/python -m pytest
```

Backend lint:

```bash
/home/piyushmarmat/PhD/PSRDEX/psrdex/.venv/bin/python -m ruff check src tests
```

Frontend build:

```bash
cd /home/piyushmarmat/PhD/PSRDEX/dashboard/frontend
npm run build
```
