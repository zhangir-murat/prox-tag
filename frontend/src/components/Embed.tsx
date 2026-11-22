import { useEffect, useRef, useState } from "react";
import { api, type ScanResult } from "../api";
import { DropZone, Field, ScanDetails, Seg, Slider, Verdict, useAsync } from "./common";
import type { Target } from "./Experiment";

const BLENDS = ["normal", "multiply", "screen", "overlay", "soft-light", "luminosity", "color"];

function demoArtwork(): Promise<Blob> {
  // procedural "poster" so the tab works without an upload
  const c = document.createElement("canvas");
  c.width = 1200;
  c.height = 800;
  const g = c.getContext("2d")!;
  const grad = g.createLinearGradient(0, 0, 1200, 800);
  grad.addColorStop(0, "#1d3557");
  grad.addColorStop(0.5, "#e76f51");
  grad.addColorStop(1, "#f4a261");
  g.fillStyle = grad;
  g.fillRect(0, 0, 1200, 800);
  for (let i = 0; i < 60; i++) {
    g.fillStyle = `hsla(${(i * 37) % 360},70%,60%,0.35)`;
    g.beginPath();
    g.arc((i * 211) % 1200, (i * 137) % 800, 20 + ((i * 53) % 120), 0, Math.PI * 2);
    g.fill();
  }
  g.fillStyle = "#fff";
  g.font = "bold 96px IBM Plex Sans, sans-serif";
  g.fillText("SUMMER SERIES", 60, 140);
  return new Promise((res) => c.toBlob((b) => res(b!), "image/jpeg", 0.92));
}

export function Embed({ target }: { target: Target }) {
  const [art, setArt] = useState<Blob | null>(null);
  const [artUrl, setArtUrl] = useState<string | null>(null);
  const [p, setP] = useState({ cx: 0.78, cy: 0.7, scale: 0.22, rotation: 0, opacity: 1, frame_opacity: 1, blend: "normal", quiet_zone: true });
  const [res, setRes] = useState<ScanResult | null>(null);
  const [auto, setAuto] = useState(true);
  const [sweepKey, setSweepKey] = useState("opacity");
  const { busy, error, run } = useAsync();
  const timer = useRef<number>();

  useEffect(() => {
    demoArtwork().then((b) => {
      setArt(b);
      setArtUrl(URL.createObjectURL(b));
    });
  }, []);

  async function test(sweep = "") {
    if (!art) return;
    const r = await run(() => api.embed(art, target.mode, target.prefix, target.code, p, sweep));
    if (r) setRes(r);
  }

  useEffect(() => {
    if (!auto || !art) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => test(), 400);
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, art, auto, target]);

  const set = (k: string, v: unknown) => setP((o) => ({ ...o, [k]: v }));
  const sweepVals: Record<string, string> = {
    opacity: "0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0",
    frame_opacity: "0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0",
    scale: "0.04,0.06,0.08,0.1,0.13,0.16,0.2,0.25,0.3,0.4",
    rotation: "0,15,30,45,60,75,90,120,150,180",
  };

  return (
    <div className="grid cols-side">
      <div className="panel">
        <h2>D · Image embedding</h2>
        <div className="small mono" style={{ marginBottom: 10 }}>
          target <b>{target.tag_id}</b>
        </div>
        <DropZone
          label="Drop a photo / poster / artwork (or keep the demo poster)"
          onFile={(f) => {
            setArt(f);
            setArtUrl(URL.createObjectURL(f));
          }}
        />
        {artUrl && <img src={artUrl} className="full" style={{ marginTop: 8, maxHeight: 120, objectFit: "contain" }} alt="artwork" />}
        <h3>Placement</h3>
        <Slider label="Centre x" value={p.cx} min={0} max={1} step={0.005} onChange={(v) => set("cx", v)} />
        <Slider label="Centre y" value={p.cy} min={0} max={1} step={0.005} onChange={(v) => set("cy", v)} />
        <Slider label="Scale (width fraction)" value={p.scale} min={0.03} max={0.9} step={0.005} onChange={(v) => set("scale", v)} />
        <Slider label="Rotation" value={p.rotation} min={-180} max={180} step={1} fmt={(v) => `${v}°`} onChange={(v) => set("rotation", v)} />
        <h3>Appearance</h3>
        <Slider label="Opacity (whole tag)" value={p.opacity} min={0} max={1} step={0.01} onChange={(v) => set("opacity", v)} />
        <Slider label="Frame + separator opacity" value={p.frame_opacity} min={0} max={1} step={0.01} onChange={(v) => set("frame_opacity", v)} />
        <Field label="Blend mode">
          <select value={p.blend} onChange={(e) => set("blend", e.target.value)}>
            {BLENDS.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </Field>
        <Field label="White quiet zone">
          <Seg value={p.quiet_zone ? "on" : "off"} onChange={(v) => set("quiet_zone", v === "on")} options={[{ v: "on", label: "keep" }, { v: "off", label: "remove" }]} />
        </Field>
        <div className="row">
          <button className="btn" onClick={() => test()} disabled={busy || !art}>Test Decoding</button>
          <label className="row small">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> live
          </label>
        </div>
        <h3>Threshold sweep</h3>
        <div className="row">
          <select style={{ width: 170 }} value={sweepKey} onChange={(e) => setSweepKey(e.target.value)}>
            {Object.keys(sweepVals).map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
          <button className="btn small" disabled={busy || !art} onClick={() => test(`${sweepKey}:${sweepVals[sweepKey]}`)}>Run sweep</button>
        </div>
        {error && <div className="err">{error}</div>}
        <div className="note small">Transparency and blending are never assumed to be safe: every setting is verified by running the scanner on the composited image.</div>
      </div>
      <div className="panel">
        {!res ? (
          <p className="lede">Loading demo artwork…</p>
        ) : (
          <>
            <Verdict r={res} expectId={res.expected?.tag_id} />
            {res.sweep && (
              <div style={{ marginBottom: 14 }}>
                <h3 style={{ marginTop: 0 }}>Sweep: {res.sweep.key}</h3>
                <div className="sweep">
                  {res.sweep.results.map((s, i) => (
                    <div key={i} title={s.reason || `${s.corrections} corrections`}>
                      <i style={{ background: s.recovered ? "var(--ok)" : s.wrong_id ? "#000" : "var(--bad)" }} />
                      {s.value}
                    </div>
                  ))}
                </div>
                <div className="small muted">green = ID recovered · red = not recovered · black = wrong ID</div>
              </div>
            )}
            <figure style={{ marginBottom: 14 }}>
              <img src={res.composite} alt="composite" />
              <figcaption>composite (scanner input)</figcaption>
            </figure>
            <ScanDetails r={res} />
          </>
        )}
      </div>
    </div>
  );
}
