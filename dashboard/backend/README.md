# PSRDEX API

FastAPI backend for the React PSRDEX dashboard. It keeps the existing PSRDEX
indexing pipeline as the source of truth and adds HTTP endpoints for catalog
browsing, background catalog refreshes, and controlled PSRISM analysis jobs.

Run locally from this directory:

```bash
pip install -e /home/piyushmarmat/PhD/PSRDEX/psrdex
pip install -e .[dev]
uvicorn psrdex_api.main:app --reload --host 127.0.0.1 --port 8000
```

Useful environment variables:

- `PSRDEX_OUTPUT_DIR`: catalog directory containing `psrdex.sqlite` and CSVs.
- `PSRDEX_DATA_DIR`: archive directory used by `psrdex-update`.
- `PSRDEX_API_CORS_ORIGINS`: comma-separated frontend origins.
- `PSRDEX_PSRISM_BIN`: PSRISM executable, default `psrism`.
