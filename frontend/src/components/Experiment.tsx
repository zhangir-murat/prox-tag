import { useEffect, useRef, useState } from "react";
import { api, type Mode, type ScanResult } from "../api";
import { Field, ScanDetails, Slider, Verdict, useAsync } from "./common";

export interface Target {
  mode: Mode;
  prefix: number;
  code: number;
  tag_id: string;
}

const DEFAULTS = {
  canvas: 800,
  size: 0.5,
  rotation: 0,
  perspective: 0,
  perspective_dir: 0,
  blur: 0,
  motion_blur: 0,
  brightness: 0,
  contrast: 1,
  saturation: 1,
  hue_shift: 0,
  gamma: 1,
  jpeg_quality: 0,
  noise: 0,
  occlusion: 0,
  occlusion_x: 0.5,
  occlusion_y: 0.5,
  background: "plain",
  background_complexity: 0.5,
  seed: 1,
};
type Params = typeof DEFAULTS;
type NumKey = Exclude<keyof Params, "background">;

const SLIDERS: { k: NumKey; label: string; min: number; max: number; step: number; fmt?: (v: number) => string }[] = [
  { k: "size", label: "Barcode size (fraction of frame)", min: 0.04, max: 0.95, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { k: "rotation", label: "Rotation", min: -180, max: 180, step: 1, fmt: (v) => `${v}°` },
  { k: "perspective", label: "Perspective distortion", min: 0, max: 0.7, step: 0.01 },
  { k: "perspective_dir", label: "Perspective direction", min: 0, max: 360, step: 5, fmt: (v) => `${v}°` },
  { k: "blur", label: "Gaussian blur σ", min: 0, max: 12, step: 0.25, fmt: (v) => `${v}px` },
  { k: "motion_blur", label: "Motion blur length", min: 0, max: 40, step: 1, fmt: (v) => `${v}px` },
  { k: "brightness", label: "Brightness", min: -0.8, max: 0.8, step: 0.01 },
  { k: "contrast", label: "Contrast", min: 0.05, max: 2.5, step: 0.01 },
  { k: "saturation", label: "Saturation", min: 0, max: 2, step: 0.01 },
  { k: "hue_shift", label: "Hue shift", min: -180, max: 180, step: 1, fmt: (v) => `${v}°` },
  { k: "gamma", label: "Gamma (tone curve)", min: 0.3, max: 3, step: 0.05 },
  { k: "jpeg_quality", label: "JPEG quality (0 = lossless)", min: 0, max: 100, step: 1 },
  { k: "noise", label: "Sensor noise σ", min: 0, max: 0.5, step: 0.005 },
  { k: "occlusion", label: "Occlusion (area of frame)", min: 0, max: 0.4, step: 0.005, fmt: (v) => `${(v * 100).toFixed(1)}%` },
  { k: "occlusion_x", label: "Occluder x", min: 0, max: 1, step: 0.01 },
  { k: "occlusion_y", label: "Occluder y", min: 0, max: 1, step: 0.01 },
  { k: "background_complexity", label: "Background complexity", min: 0, max: 1, step: 0.01 },
  { k: "seed", label: "Random seed", min: 1, max: 999, step: 1 },
];

export function Experiment({ target }: { target: Target }) {
  const [p, setP] = useState<Params>(DEFAULTS);
  const [res, setRes] = useState<ScanResult | null>(null);
  const [auto, setAuto] = useState(false);
  const [sweepKey, setSweepKey] = useState<NumKey>("blur");
  const [sweep, setSweep] = useState<{ v: number; ok: boolean; wrong: boolean }[]>([]);
  const [sweeping, setSweeping] = useState(false);
  const { busy, error, run } = useAsync();
  const timer = useRef<number>();

  const set = (k: keyof Params, v: number | string) => setP((old) => ({ ...old, [k]: v }));

  async function test() {
    const r = await run(() => api.experiment(target.mode, target.prefix, target.code, p));
    if (r) setRes(r);
  }

  useEffect(() => {
    if (!auto) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(test, 350);
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, auto, target]);

  async function runSweep() {
    const spec = SLIDERS.find((s) => s.k === sweepKey)!;
    const steps = 16;
    const out: { v: number; ok: boolean; wrong: boolean }[] = [];
    setSweeping(true);
    setSweep([]);
    for (let i = 0; i < steps; i++) {
      const v = +(spec.min + ((spec.max - spec.min) * i) / (steps - 1)).toFixed(4);
      try {
        const r = await api.experiment(target.mode, target.prefix, target.code, { ...p, [sweepKey]: v });
        out.push({ v, ok: !!r.recovered, wrong: !!r.wrong_id });
      } catch {
        out.push({ v, ok: false, wrong: false });
      }
      setSweep([...out]);
    }
    setSweeping(false);
  }

  return (
    <div className="grid cols-side">
      <div className="panel">
        <h2>C · Experiment</h2>
        <div className="small mono" style={{ marginBottom: 10 }}>
          target <b>{target.tag_id}</b> ({target.mode})
        </div>
        <Field label="Background">
          <select value={p.background} onChange={(e) => set("background", e.target.value)}>
            {["plain", "gradient", "texture", "clutter"].map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </Field>
        {SLIDERS.map((s) => (
          <Slider key={s.k} label={s.label} value={p[s.k]} min={s.min} max={s.max} step={s.step} fmt={s.fmt} onChange={(v) => set(s.k, v)} />
        ))}
        <div className="row">
          <button className="btn" onClick={test} disabled={busy}>Test Decoding</button>
          <button className="btn ghost" onClick={() => setP(DEFAULTS)}>Reset</button>
        </div>
        <label className="row small" style={{ marginTop: 8 }}>
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> re-test automatically on every change
        </label>
        {error && <div className="err">{error}</div>}
        <h3>Parameter sweep</h3>
        <div className="row">
          <select style={{ width: 200 }} value={sweepKey} onChange={(e) => setSweepKey(e.target.value as NumKey)}>
            {SLIDERS.filter((s) => s.k !== "seed").map((s) => (
              <option key={s.k} value={s.k}>{s.label}</option>
            ))}
          </select>
          <button className="btn small" onClick={runSweep} disabled={sweeping}>{sweeping ? "running…" : "Sweep 16 steps"}</button>
        </div>
        {sweep.length > 0 && (
          <div className="sweep" style={{ marginTop: 10 }}>
            {sweep.map((s, i) => (
              <div key={i} title={`${s.v}: ${s.ok ? "recovered" : s.wrong ? "WRONG ID" : "failed"}`}>
                <i style={{ background: s.ok ? "var(--ok)" : s.wrong ? "#000" : "var(--bad)" }} />
                {s.v}
              </div>
            ))}
          </div>
        )}
        <div className="note small">Each sweep step is a real scan of a newly rendered and distorted image; other parameters stay as set above.</div>
      </div>
      <div className="panel">
        {!res ? (
          <p className="lede">Adjust the distortions and press <b>Test Decoding</b>. The modified image is passed to the same scanner as a real photo; nothing knows where the tag was placed.</p>
        ) : (
          <>
            <Verdict r={res} expectId={res.expected?.tag_id} />
            <div className="grid cols-2" style={{ marginBottom: 14 }}>
              <figure>
                <img src={res.original_image} alt="original" />
                <figcaption>original symbol</figcaption>
              </figure>
              <figure>
                <img src={res.modified_image} alt="modified" />
                <figcaption>modified image (scanner input)</figcaption>
              </figure>
            </div>
            <ScanDetails r={res} />
          </>
        )}
      </div>
    </div>
  );
}
