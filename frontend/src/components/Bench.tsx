import { useState } from "react";
import { api, type BenchRow, type Info, type Mode } from "../api";
import { Bar, useAsync } from "./common";

export function Bench({ info }: { info: Info | null }) {
  const all = info?.benchmark_conditions ?? [];
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [n, setN] = useState(10);
  const [modes, setModes] = useState<Mode[]>(["mstag", "exp1"]);
  const [rows, setRows] = useState<BenchRow[]>([]);
  const [secs, setSecs] = useState(0);
  const [fp, setFp] = useState<{ images: number; false_decodes: number } | null>(null);
  const { busy, error, run } = useAsync();

  const chosen = sel.size ? [...sel] : all;
  const est = Math.round(chosen.length * modes.length * n * 0.05);

  async function go() {
    const r = await run(() => api.benchmark({ conditions: chosen, n, modes }));
    if (r) {
      setRows(r.rows);
      setSecs(r.seconds);
    }
  }

  const toggle = (c: string) => setSel((s) => {
    const x = new Set(s);
    if (x.has(c)) x.delete(c);
    else x.add(c);
    return x;
  });

  const byCond = new Map<string, Partial<Record<Mode, BenchRow>>>();
  rows.forEach((r) => byCond.set(r.condition, { ...(byCond.get(r.condition) ?? {}), [r.mode]: r }));

  return (
    <div className="grid cols-side">
      <div className="panel">
        <h2>Benchmark</h2>
        <p className="small">
          For every condition, <b>n</b> random IDs are encoded, rendered, distorted with a fresh seed, and passed to the real scanner. A trial counts
          only if the decoded mode, prefix and code all equal the ground truth.
        </p>
        <h3>Conditions ({sel.size || "all"})</h3>
        <div style={{ maxHeight: 300, overflow: "auto", border: "1px solid var(--rule-2)", padding: 6, background: "#fff" }}>
          {all.map((c) => (
            <label key={c} className="row small" style={{ gap: 6 }}>
              <input type="checkbox" checked={sel.has(c)} onChange={() => toggle(c)} /> {c}
            </label>
          ))}
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="mono small">n per condition</span>
          <input type="number" min={1} max={100} value={n} style={{ width: 80 }} onChange={(e) => setN(Number(e.target.value))} />
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {(["mstag", "exp1"] as Mode[]).map((m) => (
            <label key={m} className="row small">
              <input
                type="checkbox"
                checked={modes.includes(m)}
                onChange={(e) => setModes(e.target.checked ? [...modes, m] : modes.filter((x) => x !== m))}
              />
              {m}
            </label>
          ))}
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" onClick={go} disabled={busy || !modes.length}>{busy ? "running…" : `Run (~${est}s)`}</button>
        </div>
        <h3>False-positive check</h3>
        <p className="small">Scans random colourful images and random triangle mosaics with no valid codeword. Any decode is a false positive.</p>
        <button className="btn ghost small" disabled={busy} onClick={() => run(() => api.falsePositive(60)).then((r) => r && setFp(r))}>Scan 60 decoys</button>
        {fp && (
          <div className={"verdict " + (fp.false_decodes ? "bad" : "ok")} style={{ marginTop: 8 }}>
            {fp.false_decodes} false decodes in {fp.images} images
          </div>
        )}
        {error && <div className="err">{error}</div>}
      </div>
      <div className="panel scroll-x">
        {rows.length === 0 ? (
          <p className="lede">Run the benchmark to measure empirical success rates per condition and mode.</p>
        ) : (
          <>
            <div className="small muted mono" style={{ marginBottom: 8 }}>{rows.length} cells · {secs}s</div>
            <table className="data">
              <thead>
                <tr>
                  <th>condition</th>
                  {modes.map((m) => (
                    <th key={m} colSpan={2}>{m}</th>
                  ))}
                  <th>dominant failure</th>
                </tr>
              </thead>
              <tbody>
                {[...byCond.entries()].map(([c, ms]) => {
                  const reasons = Object.values(ms).flatMap((r) => Object.entries(r!.failure_reasons));
                  reasons.sort((a, b) => b[1] - a[1]);
                  return (
                    <tr key={c}>
                      <td>{c}</td>
                      {modes.map((m) => {
                        const r = ms[m];
                        return r ? (
                          [
                            <td key={m + "b"} style={{ width: 110 }}><Bar rate={r.rate} /></td>,
                            <td key={m + "t"}>
                              {r.success}/{r.n}
                              {r.wrong_id > 0 && <span className="badge bad" style={{ marginLeft: 4 }}>{r.wrong_id} wrong</span>}
                              <div className="small muted">{r.median_ms.toFixed(0)} ms</div>
                            </td>,
                          ]
                        ) : (
                          <td key={m} colSpan={2}>—</td>
                        );
                      })}
                      <td className="small">{reasons[0] ? `${reasons[0][0]} (${reasons[0][1]})` : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
