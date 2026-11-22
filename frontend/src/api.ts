export type Mode = "mstag" | "exp1";

export interface ModeInfo {
  name: string;
  status: string;
  prefix_max: number;
  code_max: number;
  summary: string;
}

export interface Info {
  modes: Record<Mode, ModeInfo>;
  palette: Record<string, string>;
  blend_modes: string[];
  benchmark_conditions: string[];
  db: string;
}

export interface Tag {
  id: number;
  mode: Mode;
  prefix: number;
  code: number;
  tag_id: string;
  label: string;
  url: string | null;
  enabled: boolean;
  created_at: number;
  updated_at: number;
  scan_count?: number;
  last_scan?: number | null;
}

export interface EncodeInfo {
  mode: Mode;
  prefix: number;
  code: number;
  tag_id: string;
  cells: number[];
  colors: string[];
  payload_hex: string;
  ecc_hex: string;
  whitened_hex: string;
  checksum: number | null;
  details: Record<string, unknown>;
  svg: string;
  registered?: Tag | null;
}

export interface Resolution {
  outcome: "resolved" | "disabled" | "unassigned";
  url: string | null;
  tag: Tag | null;
  tag_id: string;
}

export interface ScanResult {
  ok: boolean;
  mode: Mode | null;
  prefix: number | null;
  code: number | null;
  tag_id: string | null;
  checksum_ok: boolean | null;
  corrected_symbols: number;
  erasures: number;
  strategy: string;
  orientation: Record<string, unknown> | null;
  quad: number[][] | null;
  cells: number[] | null;
  confidence: number[] | null;
  reason: string;
  log: string[];
  candidates: number;
  attempts: number;
  elapsed_ms: number;
  debug: { mask?: string; detection?: string; warped?: string; cells?: string; palette_refs?: number[][] };
  resolution?: Resolution;
  // experiment / embed extras
  recovered?: boolean;
  wrong_id?: boolean;
  expected?: { tag_id: string };
  original_image?: string;
  modified_image?: string;
  composite?: string;
  sweep?: { key: string; results: { value: number; recovered: boolean; wrong_id: boolean; reason: string; corrections: number }[] };
}

export interface BenchRow {
  condition: string;
  mode: Mode;
  n: number;
  success: number;
  wrong_id: number;
  rate: number;
  median_ms: number;
  failure_reasons: Record<string, number>;
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  info: () => fetch("/api/info").then((r) => handle<Info>(r)),
  encode: (mode: Mode, prefix: number, code: number) =>
    fetch("/api/encode", json("POST", { mode, prefix, code })).then((r) => handle<EncodeInfo>(r)),
  tags: () => fetch("/api/tags").then((r) => handle<Tag[]>(r)),
  createTag: (body: { url?: string | null; mode: Mode; prefix: number; code?: number | null; label?: string }) =>
    fetch("/api/tags", json("POST", body)).then((r) => handle<Tag & { symbol: EncodeInfo }>(r)),
  patchTag: (id: number, body: { url?: string | null; label?: string; enabled?: boolean; clear_url?: boolean }) =>
    fetch(`/api/tags/${id}`, json("PATCH", body)).then((r) => handle<Tag>(r)),
  deleteTag: (id: number) => fetch(`/api/tags/${id}`, { method: "DELETE" }).then((r) => handle<unknown>(r)),
  tagScans: (id: number) => fetch(`/api/tags/${id}/scans`).then((r) => handle<ScanEvent[]>(r)),
  scans: () => fetch(`/api/scans?limit=100`).then((r) => handle<ScanEvent[]>(r)),
  stats: () => fetch("/api/stats").then((r) => handle<Stats>(r)),
  scan: (file: Blob, opts: { source?: string; record?: boolean; debug?: boolean } = {}) => {
    const fd = new FormData();
    fd.append("file", file, "image.jpg");
    fd.append("source", opts.source ?? "upload");
    fd.append("record", String(opts.record ?? true));
    fd.append("debug", String(opts.debug ?? true));
    return fetch("/api/scan", { method: "POST", body: fd }).then((r) => handle<ScanResult>(r));
  },
  experiment: (mode: Mode, prefix: number, code: number, params: Record<string, unknown>) =>
    fetch("/api/experiment", json("POST", { mode, prefix, code, params })).then((r) => handle<ScanResult>(r)),
  embed: (file: Blob, mode: Mode, prefix: number, code: number, params: Record<string, unknown>, sweep = "") => {
    const fd = new FormData();
    fd.append("file", file, "art.jpg");
    fd.append("mode", mode);
    fd.append("prefix", String(prefix));
    fd.append("code", String(code));
    fd.append("params", JSON.stringify(params));
    fd.append("sweep", sweep);
    return fetch("/api/embed", { method: "POST", body: fd }).then((r) => handle<ScanResult>(r));
  },
  benchmark: (body: { conditions?: string[] | null; n: number; modes: Mode[]; seed?: number }) =>
    fetch("/api/benchmark", json("POST", body)).then((r) => handle<{ rows: BenchRow[]; seconds: number }>(r)),
  falsePositive: (n: number) =>
    fetch(`/api/false-positive?n=${n}`, { method: "POST" }).then((r) =>
      handle<{ images: number; false_decodes: number; claims: unknown[] }>(r),
    ),
};

export interface ScanEvent {
  id: number;
  ts: number;
  mode: Mode;
  prefix: number;
  code: number;
  tag_id: string;
  tag_row: number | null;
  outcome: string;
  source: string;
  corrected: number;
  user_agent: string;
}

export interface Stats {
  total_scans: number;
  by_outcome: Record<string, number>;
  by_source: Record<string, number>;
  per_day: { day: string; n: number }[];
  tags: number;
  enabled_tags: number;
}

export function symbolUrl(mode: Mode, prefix: number, code: number, ext: "png" | "svg", q: Record<string, string | number | boolean> = {}) {
  const qs = new URLSearchParams(Object.entries(q).map(([k, v]) => [k, String(v)])).toString();
  return `/api/symbol/${mode}/${prefix}/${code}.${ext}${qs ? "?" + qs : ""}`;
}
