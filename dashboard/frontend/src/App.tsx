import React from "react";
import type { Data } from "plotly.js";
import {
  Activity,
  Database,
  FileSearch,
  FileText,
  Image,
  ListChecks,
  Play,
  RefreshCw,
  Settings2,
  Table2,
  Telescope,
  X,
} from "lucide-react";
import {
  createPsrismRun,
  fetchOverview,
  fetchPsrismRun,
  fetchPsrismRuns,
  fetchPulsarObservations,
  fetchPulsars,
  psrismFileUrl,
  startCatalogUpdate,
  type BandSummary,
  type CatalogOverview,
  type Observation,
  type PsrismRun,
  type PsrismRunFile,
  type PulsarSummary,
} from "@/api/psrdexApi";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Plot from "@/components/Plot";
import "./App.css";

const BAND_COLORS: Record<string, string> = {
  "0b": "#d81b60",
  "1b": "#f97316",
  "2b": "#239b56",
  "3b": "#2f6fb1",
  "0c": "#7c3aed",
  "1c": "#dc2626",
  "2c": "#c77d11",
  "3c": "#0f8f75",
};

const PSRISM_PRODUCTS = [
  ["inspect", "Inspect valid scrunching"],
  ["dspec", "Dynamic spectrum"],
  ["acspec", "Autocorrelation spectrum"],
  ["zoom_acf", "Zoomed ACF"],
  ["sspec", "Secondary spectrum"],
  ["fit_arc", "Secondary-spectrum arc fit"],
  ["intpf", "Integrated profile"],
  ["fit_tau", "Scattering timescale tau"],
  ["fit_alpha", "Scattering spectral index alpha"],
  ["fit_anisotropy", "Anisotropic broadening"],
  ["estimate_refractive", "Refractive estimates"],
];

type PsrismForm = {
  products: string[];
  nsub: string;
  nchan: string;
  nbin: string;
  tauSubbands: string;
  distanceKpc: string;
  velocityKms: string;
  timeParams: string;
};

const DEFAULT_FORM: PsrismForm = {
  products: ["dspec", "intpf"],
  nsub: "",
  nchan: "",
  nbin: "",
  tauSubbands: "4",
  distanceKpc: "",
  velocityKms: "",
  timeParams: "",
};

function App() {
  const [overview, setOverview] = React.useState<CatalogOverview | null>(null);
  const [pulsars, setPulsars] = React.useState<PulsarSummary[]>([]);
  const [selectedPulsar, setSelectedPulsar] = React.useState("");
  const [observations, setObservations] = React.useState<Observation[]>([]);
  const [bandSummary, setBandSummary] = React.useState<BandSummary[]>([]);
  const [activeBands, setActiveBands] = React.useState<string[]>([]);
  const [selectedRows, setSelectedRows] = React.useState<string[]>([]);
  const [runs, setRuns] = React.useState<PsrismRun[]>([]);
  const [activeRun, setActiveRun] = React.useState<PsrismRun | null>(null);
  const [analysisOpen, setAnalysisOpen] = React.useState(false);
  const [form, setForm] = React.useState<PsrismForm>(DEFAULT_FORM);
  const [status, setStatus] = React.useState("Loading catalog...");
  const selectedObservation = observations.find((row) => row.row_id === selectedRows[0]) ?? null;
  const selectedArchives = observations
    .filter((row) => selectedRows.includes(row.row_id))
    .map((row) => row.path);

  const loadCatalog = React.useCallback(async () => {
    setStatus("Loading catalog...");
    const [overviewData, pulsarData, runData] = await Promise.all([
      fetchOverview(),
      fetchPulsars(),
      fetchPsrismRuns(),
    ]);
    setOverview(overviewData);
    setPulsars(pulsarData);
    setRuns(runData);
    setSelectedPulsar((current) => current || pulsarData[0]?.pulsar || "");
    if (!activeRun && runData[0]) setActiveRun(runData[0]);
    setStatus("Catalog ready");
  }, [activeRun]);

  const refreshRuns = React.useCallback(async () => {
    const runData = await fetchPsrismRuns();
    setRuns(runData);
    setActiveRun((current) => {
      if (!current) return runData[0] ?? null;
      return runData.find((run) => run.run_id === current.run_id) ?? current;
    });
  }, []);

  React.useEffect(() => {
    loadCatalog().catch((error) => setStatus(error.message));
  }, [loadCatalog]);

  React.useEffect(() => {
    if (!selectedPulsar) return;
    fetchPulsarObservations(selectedPulsar, activeBands)
      .then((data) => {
        setObservations(data.observations);
        setBandSummary(data.band_summary);
        const available = Array.from(
          new Set(data.observations.map((row) => String(row.band ?? "")).filter(Boolean)),
        );
        setActiveBands((current) => (current.length ? current : available));
        setSelectedRows([]);
      })
      .catch((error) => setStatus(error.message));
  }, [selectedPulsar, activeBands.join("|")]);

  React.useEffect(() => {
    if (!activeRun?.run_id) return;
    const timer = window.setInterval(() => {
      fetchPsrismRun(activeRun.run_id)
        .then(setActiveRun)
        .catch(() => undefined);
      refreshRuns().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [activeRun?.run_id, refreshRuns]);

  async function runUpdate() {
    const result = await startCatalogUpdate(false);
    setStatus(`Catalog update ${result.status}; log: ${result.log}`);
  }

  async function launchPsrism() {
    if (!selectedArchives.length) return;
    const result = await createPsrismRun({
      archive_paths: selectedArchives,
      products: form.products,
      nsub: positiveNumber(form.nsub),
      nchan: positiveNumber(form.nchan),
      nbin: positiveNumber(form.nbin),
      tau_subbands: positiveNumber(form.tauSubbands),
      distance_kpc: positiveNumber(form.distanceKpc),
      velocity_kms: positiveNumber(form.velocityKms),
      time_params: form.timeParams || undefined,
    });
    const detail = await fetchPsrismRun(result.run_id);
    setActiveRun(detail);
    setAnalysisOpen(false);
    setStatus(`PSRISM run ${result.run_id} started`);
    await refreshRuns();
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">POLFAR archive dashboard</p>
          <h1>PSRDEX</h1>
          <p className="subtitle">Indexing tool for pulsars with controlled PSRISM analysis launches.</p>
        </div>
        <div className="topbar-actions">
          <span className="status-pill">{status}</span>
          <Button variant="outline" onClick={loadCatalog}>
            <RefreshCw /> Reload
          </Button>
          <Button onClick={runUpdate}>
            <Database /> Update
          </Button>
        </div>
      </header>

      <section className="metrics-grid">
        <Metric icon={<Telescope />} label="Pulsars" value={overview?.pulsars} />
        <Metric icon={<FileSearch />} label="Indexed files" value={overview?.files} />
        <Metric icon={<Activity />} label="Observing hours" value={overview?.total_duration_hours?.toFixed(1)} />
        <Metric icon={<Database />} label="Failures" value={overview?.failures} />
      </section>

      <section className="dashboard-grid">
        <Card className="panel">
          <CardHeader>
            <CardTitle>Catalog Browser</CardTitle>
          </CardHeader>
          <CardContent className="panel-content">
            <Label htmlFor="pulsar">Pulsar</Label>
            <select
              id="pulsar"
              value={selectedPulsar}
              onChange={(event) => {
                setActiveBands([]);
                setSelectedPulsar(event.target.value);
              }}
            >
              {pulsars.map((pulsar) => (
                <option key={pulsar.pulsar} value={pulsar.pulsar}>
                  {pulsar.pulsar} - {pulsar.n_files} files
                </option>
              ))}
            </select>
            <BandFilters observations={observations} activeBands={activeBands} setActiveBands={setActiveBands} />
            <LaneTable rows={bandSummary} />
          </CardContent>
        </Card>

        <Card className="panel timeline-panel">
          <CardHeader>
            <CardTitle>Observation SNR</CardTitle>
          </CardHeader>
          <CardContent>
            <Timeline observations={observations} setSelectedRows={setSelectedRows} />
          </CardContent>
        </Card>
      </section>

      <section className="detail-grid">
        <Card className="panel">
          <CardHeader>
            <CardTitle>Selected Observation</CardTitle>
          </CardHeader>
          <CardContent>
            <ObservationDetails observation={selectedObservation} />
          </CardContent>
        </Card>

        <Card className="panel">
          <CardHeader>
            <CardTitle>PSRISM Controls</CardTitle>
          </CardHeader>
          <CardContent className="panel-content">
            <div className="analysis-summary">
              <strong>{selectedArchives.length}</strong>
              <span>selected archive{selectedArchives.length === 1 ? "" : "s"} for analysis</span>
            </div>
            <div className="button-row">
              <Button variant="outline" onClick={() => setSelectedRows(observations.map((row) => row.row_id))}>
                <ListChecks /> Select visible
              </Button>
              <Button disabled={!selectedArchives.length} onClick={() => setAnalysisOpen(true)}>
                <Settings2 /> Configure PSRISM
              </Button>
            </div>
            <ObservationPicker observations={observations} selectedRows={selectedRows} setSelectedRows={setSelectedRows} />
          </CardContent>
        </Card>
      </section>

      <section className="results-grid">
        <RunBrowser
          runs={runs}
          activeRun={activeRun}
          setActiveRun={async (runId) => setActiveRun(await fetchPsrismRun(runId))}
          refreshRuns={refreshRuns}
        />
        <RunResults run={activeRun} />
      </section>

      {analysisOpen && (
        <PsrismDialog
          form={form}
          setForm={setForm}
          selectedArchives={selectedArchives}
          onClose={() => setAnalysisOpen(false)}
          onLaunch={launchPsrism}
        />
      )}
    </main>
  );
}

function positiveNumber(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value?: string | number }) {
  return (
    <Card className="metric-card">
      <div className="metric-icon">{icon}</div>
      <div>
        <p>{label}</p>
        <strong>{value ?? "..."}</strong>
      </div>
    </Card>
  );
}

function BandFilters({
  observations,
  activeBands,
  setActiveBands,
}: {
  observations: Observation[];
  activeBands: string[];
  setActiveBands: React.Dispatch<React.SetStateAction<string[]>>;
}) {
  const bands = Array.from(new Set(observations.map((row) => String(row.band ?? "")).filter(Boolean))).sort();
  return (
    <div className="band-filter">
      {bands.map((band) => (
        <label key={band} className="check-row">
          <input
            type="checkbox"
            checked={activeBands.includes(band)}
            onChange={(event) =>
              setActiveBands((current) =>
                event.target.checked ? [...current, band] : current.filter((item) => item !== band),
              )
            }
          />
          <span className="band-dot" style={{ backgroundColor: BAND_COLORS[band] ?? "#64748b" }} />
          {band}
        </label>
      ))}
    </div>
  );
}

function Timeline({
  observations,
  setSelectedRows,
}: {
  observations: Observation[];
  setSelectedRows: React.Dispatch<React.SetStateAction<string[]>>;
}) {
  const bands = Array.from(new Set(observations.map((row) => String(row.band ?? "")).filter(Boolean)));
  const traces = bands.map((band) => {
    const rows = observations.filter((row) => String(row.band) === band);
    return {
      type: "scatter",
      mode: "markers",
      name: band,
      x: rows.map((row) => row.observation_time),
      y: rows.map((row) => row.snr ?? 0),
      customdata: rows.map((row) => row.row_id),
      marker: { color: BAND_COLORS[band] ?? "#64748b", size: 12, opacity: 0.78 },
    };
  });
  return (
    <Plot
      data={traces as Data[]}
      layout={{
        autosize: true,
        height: 390,
        margin: { l: 58, r: 20, t: 12, b: 58 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Segoe UI, sans-serif", color: "#1f2937" },
        xaxis: { title: { text: "Observation time" }, gridcolor: "#d8dee8" },
        yaxis: { title: { text: "Total SNR" }, gridcolor: "#d8dee8" },
        showlegend: true,
      }}
      config={{ responsive: true, displaylogo: false }}
      useResizeHandler
      className="plot"
      onClick={(event) => {
        const rowId = event.points[0]?.customdata;
        if (typeof rowId === "string") {
          setSelectedRows((current) =>
            current.includes(rowId) ? current.filter((item) => item !== rowId) : [...current, rowId],
          );
        }
      }}
    />
  );
}

function LaneTable({ rows }: { rows: BandSummary[] }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Lane</th>
          <th>Files</th>
          <th>Hours</th>
          <th>Max SNR</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.band}>
            <td>{row.lane}</td>
            <td>{row.files}</td>
            <td>{row.hours.toFixed(2)}</td>
            <td>{row.max_snr?.toFixed(2) ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ObservationDetails({ observation }: { observation: Observation | null }) {
  const fields = ["file_name", "snr", "dm", "period_sec", "mjd", "datetime_utc", "ra", "dec", "freq_mhz", "bandwidth_mhz", "duration_sec", "path"];
  if (!observation) return <p className="empty-state">Select a point or a table row to pin observation metadata.</p>;
  return (
    <dl className="metadata-list">
      {fields.map((field) => (
        <React.Fragment key={field}>
          <dt>{field.replaceAll("_", " ")}</dt>
          <dd>{String(observation[field] ?? "")}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function ObservationPicker({
  observations,
  selectedRows,
  setSelectedRows,
}: {
  observations: Observation[];
  selectedRows: string[];
  setSelectedRows: React.Dispatch<React.SetStateAction<string[]>>;
}) {
  return (
    <div className="observation-picker">
      <table className="data-table compact-table">
        <thead>
          <tr>
            <th>Use</th>
            <th>UTC</th>
            <th>Band</th>
            <th>SNR</th>
          </tr>
        </thead>
        <tbody>
          {observations.slice(0, 80).map((row) => (
            <tr key={row.row_id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedRows.includes(row.row_id)}
                  onChange={(event) =>
                    setSelectedRows((current) =>
                      event.target.checked
                        ? [...current, row.row_id]
                        : current.filter((item) => item !== row.row_id),
                    )
                  }
                />
              </td>
              <td>{shortDate(row.observation_time)}</td>
              <td>{row.band}</td>
              <td>{typeof row.snr === "number" ? row.snr.toFixed(2) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PsrismDialog({
  form,
  setForm,
  selectedArchives,
  onClose,
  onLaunch,
}: {
  form: PsrismForm;
  setForm: React.Dispatch<React.SetStateAction<PsrismForm>>;
  selectedArchives: string[];
  onClose: () => void;
  onLaunch: () => void;
}) {
  const update = (patch: Partial<PsrismForm>) => setForm((current) => ({ ...current, ...patch }));
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="analysis-dialog" role="dialog" aria-modal="true" aria-labelledby="psrism-dialog-title">
        <header className="dialog-header">
          <div>
            <p className="eyebrow">PSRISM job setup</p>
            <h2 id="psrism-dialog-title">Configure Archive Analysis</h2>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close PSRISM setup">
            <X />
          </Button>
        </header>

        <div className="dialog-grid">
          <section>
            <h3>Products</h3>
            <div className="product-grid dialog-products">
              {PSRISM_PRODUCTS.map(([id, label]) => (
                <label key={id} className="check-row">
                  <input
                    type="checkbox"
                    checked={form.products.includes(id)}
                    onChange={(event) =>
                      update({
                        products: event.target.checked
                          ? [...form.products, id]
                          : form.products.filter((item) => item !== id),
                      })
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          </section>

          <section>
            <h3>Parameters</h3>
            <div className="form-grid">
              <Field label="nsub" value={form.nsub} onChange={(value) => update({ nsub: value })} />
              <Field label="nchan" value={form.nchan} onChange={(value) => update({ nchan: value })} />
              <Field label="nbin" value={form.nbin} onChange={(value) => update({ nbin: value })} />
              <Field label="tau subbands" value={form.tauSubbands} onChange={(value) => update({ tauSubbands: value })} />
              <Field label="distance kpc" value={form.distanceKpc} onChange={(value) => update({ distanceKpc: value })} />
              <Field label="velocity km/s" value={form.velocityKms} onChange={(value) => update({ velocityKms: value })} />
            </div>
            <Label htmlFor="time-params">Time-series parameters</Label>
            <select id="time-params" value={form.timeParams} onChange={(event) => update({ timeParams: event.target.value })}>
              <option value="">None</option>
              <option value="dm">DM</option>
              <option value="tau">Tau</option>
              <option value="alpha">Alpha</option>
              <option value="dnu_d">Decorrelation bandwidth</option>
              <option value="dt_d">Diffractive timescale</option>
              <option value="t_r">Refractive timescale</option>
              <option value="all">All</option>
            </select>
          </section>
        </div>

        <section>
          <h3>Selected Archives</h3>
          <div className="archive-list">
            {selectedArchives.map((path) => (
              <code key={path}>{path}</code>
            ))}
          </div>
        </section>

        <footer className="dialog-footer">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!selectedArchives.length || !form.products.length} onClick={onLaunch}>
            <Play /> Launch PSRISM
          </Button>
        </footer>
      </div>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const id = label.replaceAll(" ", "-");
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="number" min="1" value={value} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function RunBrowser({
  runs,
  activeRun,
  setActiveRun,
  refreshRuns,
}: {
  runs: PsrismRun[];
  activeRun: PsrismRun | null;
  setActiveRun: (runId: string) => void;
  refreshRuns: () => void;
}) {
  return (
    <Card className="panel">
      <CardHeader>
        <CardTitle>PSRISM Runs</CardTitle>
      </CardHeader>
      <CardContent className="panel-content">
        <Button variant="outline" onClick={refreshRuns}>
          <RefreshCw /> Refresh runs
        </Button>
        <div className="run-list">
          {runs.slice(0, 12).map((run) => (
            <button
              key={run.run_id}
              className={`run-row ${activeRun?.run_id === run.run_id ? "is-active" : ""}`}
              onClick={() => setActiveRun(run.run_id)}
            >
              <strong>{run.run_id}</strong>
              <span>{run.status}</span>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function RunResults({ run }: { run: PsrismRun | null }) {
  if (!run) {
    return (
      <Card className="panel">
        <CardHeader>
          <CardTitle>PSRISM Products</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="empty-state">Launch or select a PSRISM run to inspect generated plots and logs.</p>
        </CardContent>
      </Card>
    );
  }
  const files = run.files ?? [];
  const images = files.filter((file) => file.kind === "image");
  const tables = files.filter((file) => file.kind === "table");
  const textFiles = files.filter((file) => file.kind === "text");
  return (
    <Card className="panel results-panel">
      <CardHeader>
        <CardTitle>PSRISM Products: {run.run_id}</CardTitle>
      </CardHeader>
      <CardContent className="panel-content">
        <div className="run-meta">
          <span>Status: <strong>{run.status}</strong></span>
          <span>{run.command?.join(" ")}</span>
        </div>
        {images.length > 0 ? (
          <div className="plot-gallery">
            {images.map((file) => (
              <figure key={file.path} className="product-image">
                <img src={psrismFileUrl(run.run_id, file.path)} alt={file.name} />
                <figcaption><Image /> {file.path}</figcaption>
              </figure>
            ))}
          </div>
        ) : (
          <p className="empty-state">No plot images found yet. Running jobs refresh automatically.</p>
        )}
        <FileLinks title="Tables" icon={<Table2 />} runId={run.run_id} files={tables} />
        <FileLinks title="Logs and text" icon={<FileText />} runId={run.run_id} files={textFiles} />
        {run.log_tail && (
          <pre className="log-panel">{run.log_tail}</pre>
        )}
      </CardContent>
    </Card>
  );
}

function FileLinks({
  title,
  icon,
  runId,
  files,
}: {
  title: string;
  icon: React.ReactNode;
  runId: string;
  files: PsrismRunFile[];
}) {
  if (!files.length) return null;
  return (
    <section>
      <h3 className="file-section-title">{icon} {title}</h3>
      <div className="file-link-grid">
        {files.map((file) => (
          <a key={file.path} href={psrismFileUrl(runId, file.path)} target="_blank" rel="noreferrer">
            {file.path}
          </a>
        ))}
      </div>
    </section>
  );
}

function shortDate(value: string | null | undefined) {
  if (!value) return "";
  return value.replace("T", " ").replace("Z", "").slice(0, 19);
}

export default App;
