const API_BASE = import.meta.env.VITE_PSRDEX_API_BASE ?? "http://127.0.0.1:8000";

export type BandInfo = {
  id: string;
  label?: string;
  receiver?: string;
  center_mhz?: number | null;
  range_mhz?: string;
  display: string;
};

export type CatalogOverview = {
  pulsars: number;
  files: number;
  total_duration_hours: number;
  bands: BandInfo[];
  last_updated: string | null;
  failures: number;
};

export type PulsarSummary = {
  pulsar: string;
  n_files: number;
  total_duration_hours: number;
  first_mjd: number | null;
  last_mjd: number | null;
  max_snr: number | null;
  bands: string[];
  ra: string | null;
  dec: string | null;
};

export type Observation = {
  row_id: string;
  path: string;
  file_name: string;
  pulsar: string;
  datetime_utc?: string | null;
  observation_time?: string | null;
  mjd?: number | null;
  ra?: string | null;
  dec?: string | null;
  band?: string | null;
  band_display?: string;
  freq_mhz?: number | null;
  bandwidth_mhz?: number | null;
  duration_sec?: number | null;
  period_sec?: number | null;
  dm?: number | null;
  snr?: number | null;
  [key: string]: unknown;
};

export type BandSummary = {
  band: string;
  lane: string;
  receiver: string;
  files: number;
  hours: number;
  max_snr: number | null;
  latest: string | null;
};

export type PulsarObservationsResponse = {
  pulsar: string;
  observations: Observation[];
  band_summary: BandSummary[];
};

export type PsrismRun = {
  run_id: string;
  status: string;
  files?: PsrismRunFile[];
  products?: string[];
  archive_paths?: string[];
  command?: string[];
  started_at?: string;
  log_tail?: string;
  options?: Record<string, unknown>;
};

export type PsrismRunFile = {
  path: string;
  name: string;
  kind: "image" | "table" | "text" | "metadata";
  size_bytes: number;
};

export type PsrismRunRequest = {
  archive_paths: string[];
  products: string[];
  nsub?: number;
  nchan?: number;
  nbin?: number;
  tau_subbands?: number;
  distance_kpc?: number;
  velocity_kms?: number;
  time_params?: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function fetchOverview() {
  return request<CatalogOverview>("/api/catalog/overview");
}

export function fetchPulsars() {
  return request<PulsarSummary[]>("/api/catalog/pulsars");
}

export function fetchPulsarObservations(pulsar: string, bands: string[]) {
  const params = new URLSearchParams();
  bands.forEach((band) => params.append("bands", band));
  const suffix = params.toString() ? `?${params}` : "";
  return request<PulsarObservationsResponse>(
    `/api/catalog/pulsars/${encodeURIComponent(pulsar)}/observations${suffix}`,
  );
}

export function startCatalogUpdate(force = false) {
  return request<{ status: string; log: string }>(`/api/catalog/update?force=${force}`, {
    method: "POST",
  });
}

export function fetchPsrismRuns() {
  return request<PsrismRun[]>("/api/psrism/runs");
}

export function fetchPsrismRun(runId: string) {
  return request<PsrismRun>(`/api/psrism/runs/${encodeURIComponent(runId)}`);
}

export function createPsrismRun(payload: PsrismRunRequest) {
  return request<{ run_id: string; status: string; run_dir: string }>("/api/psrism/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function psrismFileUrl(runId: string, path: string) {
  return `${API_BASE}/api/psrism/runs/${encodeURIComponent(runId)}/files/${path
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}
