import { useEffect, useState } from "react";
import { api, symbolUrl, type ScanEvent, type Stats, type Tag } from "../api";
import { useAsync } from "./common";

const fmtTime = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString() : "—");

function Row({ t, onChange }: { t: Tag; onChange: () => void }) {
  const [url, setUrl] = useState(t.url ?? "");
  const [label, setLabel] = useState(t.label);
  const [open, setOpen] = useState(false);
  const [scans, setScans] = useState<ScanEvent[] | null>(null);
  const { busy, error, run } = useAsync();
  const dirty = url !== (t.url ?? "") || label !== t.label;

  async function save() {
    await run(() => api.patchTag(t.id, url ? { url, label } : { clear_url: true, label }));
    onChange();
  }
  async function toggle() {
    await run(() => api.patchTag(t.id, { enabled: !t.enabled }));
    onChange();
  }
  async function del() {
    if (!confirm(`Delete tag ${t.tag_id}? The printed symbol will then resolve as "unassigned".`)) return;
    await run(() => api.deleteTag(t.id));
    onChange();
  }
  async function history() {
    setOpen(!open);
    if (!open) setScans(await api.tagScans(t.id));
  }

  return (
    <>
      <tr className={t.enabled ? "" : "off"}>
        <td>
          <img src={symbolUrl(t.mode, t.prefix, t.code, "png", { width: 96 })} width={48} alt="" style={{ display: "block" }} />
        </td>
        <td>
          <b>{t.tag_id}</b>
          <div className="small muted">{t.mode} · #{t.id}</div>
        </td>
        <td style={{ minWidth: 220 }}>
          <input type="url" value={url} placeholder="(no destination)" onChange={(e) => setUrl(e.target.value)} />
          <input type="text" value={label} placeholder="label" onChange={(e) => setLabel(e.target.value)} style={{ marginTop: 4 }} />
          {error && <div className="err">{error}</div>}
        </td>
        <td>
          <span className={"badge " + (t.enabled ? "ok" : "mute")}>{t.enabled ? "enabled" : "disabled"}</span>
        </td>
        <td>
          {t.scan_count ?? 0}
          <div className="small muted">{fmtTime(t.last_scan)}</div>
        </td>
        <td>
          <div className="row">
            <button className="btn small" disabled={!dirty || busy} onClick={save}>Save</button>
            <button className="btn small ghost" onClick={toggle} disabled={busy}>{t.enabled ? "Disable" : "Enable"}</button>
            <button className="btn small ghost" onClick={history}>History</button>
            <a className="btn small ghost" href={symbolUrl(t.mode, t.prefix, t.code, "svg", { download: true })}>SVG</a>
            <button className="btn small danger" onClick={del} disabled={busy}>Delete</button>
          </div>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} style={{ background: "var(--paper-2)" }}>
            {!scans ? (
              "loading…"
            ) : scans.length === 0 ? (
              <span className="small muted">No scans recorded yet.</span>
            ) : (
              <table className="data">
                <thead>
                  <tr><th>time</th><th>outcome</th><th>source</th><th>corrections</th><th>user agent</th></tr>
                </thead>
                <tbody>
                  {scans.map((s) => (
                    <tr key={s.id}>
                      <td>{fmtTime(s.ts)}</td>
                      <td>{s.outcome}</td>
                      <td>{s.source}</td>
                      <td>{s.corrected}</td>
                      <td className="small muted">{s.user_agent.slice(0, 60)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function Manager() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<ScanEvent[]>([]);
  const { error, run } = useAsync();

  const load = () =>
    run(async () => {
      const [t, s, r] = await Promise.all([api.tags(), api.stats(), api.scans()]);
      setTags(t);
      setStats(s);
      setRecent(r);
    });
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="grid">
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>E · Tag manager</h2>
          <button className="btn small ghost" onClick={load}>Refresh</button>
        </div>
        {stats && (
          <dl className="kv" style={{ marginTop: 12 }}>
            <dt>tags</dt>
            <dd>{stats.tags} ({stats.enabled_tags} enabled)</dd>
            <dt>scan events</dt>
            <dd>
              {stats.total_scans} · {Object.entries(stats.by_outcome).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}
            </dd>
            <dt>by source</dt>
            <dd>{Object.entries(stats.by_source).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}</dd>
            <dt>per day</dt>
            <dd>{stats.per_day.map((d) => `${d.day}: ${d.n}`).join(" · ") || "—"}</dd>
          </dl>
        )}
        {error && <div className="err">{error}</div>}
      </div>
      <div className="panel scroll-x">
        <p className="small muted" style={{ marginTop: 0 }}>
          Editing a destination changes only the resolver row; the symbol depends on mode + prefix + code alone, so printed tags keep working.
        </p>
        <table className="data">
          <thead>
            <tr><th></th><th>tag id</th><th>destination / label</th><th>status</th><th>scans</th><th>actions</th></tr>
          </thead>
          <tbody>
            {tags.map((t) => (
              <Row key={`${t.id}-${t.updated_at}`} t={t} onChange={load} />
            ))}
            {tags.length === 0 && (
              <tr><td colSpan={6} className="muted">No tags yet — create one in Generate.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="panel scroll-x">
        <h3 style={{ marginTop: 0 }}>Recent scan events (all IDs, including unassigned)</h3>
        <table className="data">
          <thead>
            <tr><th>time</th><th>tag id</th><th>outcome</th><th>source</th><th>corrections</th></tr>
          </thead>
          <tbody>
            {recent.map((s) => (
              <tr key={s.id}>
                <td>{fmtTime(s.ts)}</td>
                <td>{s.tag_id}</td>
                <td>{s.outcome}</td>
                <td>{s.source}</td>
                <td>{s.corrected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
