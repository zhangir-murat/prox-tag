import { useRef, useState, type ReactNode } from "react";
import type { ScanResult } from "../api";

export const PALETTE = ["#FFFF00", "#FF00FF", "#000000", "#00FFFF"];
export const PALETTE_NAMES = ["Y", "M", "K", "C"];

export function Field(props: { label: string; value?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span>
        {props.label}
        {props.value !== undefined && <em>{props.value}</em>}
      </span>
      {props.children}
    </label>
  );
}

export function Slider(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  fmt?: (v: number) => string;
}) {
  return (
    <Field label={props.label} value={props.fmt ? props.fmt(props.value) : props.value}>
      <input
        type="range"
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.value}
        onChange={(e) => props.onChange(parseFloat(e.target.value))}
      />
    </Field>
  );
}

export function Seg<T extends string>(props: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="seg">
      {props.options.map((o) => (
        <button key={o.v} type="button" className={o.v === props.value ? "on" : ""} onClick={() => props.onChange(o.v)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function DropZone(props: { onFile: (f: File) => void; label?: string; accept?: string }) {
  const [over, setOver] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div
      className={"drop" + (over ? " over" : "")}
      onClick={() => ref.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) props.onFile(f);
      }}
    >
      {props.label ?? "Drop an image here or click to choose (PNG / JPEG)"}
      <input
        ref={ref}
        type="file"
        accept={props.accept ?? "image/*"}
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) props.onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

export function Verdict({ r, expectId }: { r: ScanResult; expectId?: string }) {
  if (r.ok && (r.recovered ?? true)) {
    const corr = r.corrected_symbols + r.erasures;
    return (
      <div className="verdict ok">
        <div className="big">✓ {r.tag_id}</div>
        <div className="why">
          {r.mode === "mstag" ? "MS Tag (RE) mode" : "Experimental v1 mode"} · checksum/ECC verified ·{" "}
          {corr ? `${r.corrected_symbols} symbol correction(s), ${r.erasures} erasure(s) via ${r.strategy}` : "no corrections needed"} ·{" "}
          {r.elapsed_ms} ms
        </div>
      </div>
    );
  }
  if (r.ok && r.recovered === false) {
    return (
      <div className="verdict bad">
        <div className="big">✗ WRONG ID {r.tag_id}</div>
        <div className="why">Decoder accepted a codeword that differs from the expected {expectId}. This is a miscorrection — please record it.</div>
      </div>
    );
  }
  return (
    <div className="verdict bad">
      <div className="big">✗ Not recovered</div>
      <div className="why">{r.reason || "unknown failure"}</div>
    </div>
  );
}

export function ScanDetails({ r }: { r: ScanResult }) {
  return (
    <div>
      <div className="imgs">
        {r.debug.detection && (
          <figure>
            <img src={r.debug.detection} alt="detection overlay" />
            <figcaption>1 · detected frame (orange dot = corner 0)</figcaption>
          </figure>
        )}
        {r.debug.mask && (
          <figure>
            <img src={r.debug.mask} alt="dark mask" />
            <figcaption>2 · dark-region mask</figcaption>
          </figure>
        )}
        {r.debug.warped && (
          <figure>
            <img src={r.debug.warped} alt="rectified" />
            <figcaption>3 · perspective-rectified</figcaption>
          </figure>
        )}
      </div>
      {r.debug.cells && (
        <figure className="cells" style={{ marginTop: 10 }}>
          <img src={r.debug.cells} alt="cells" />
          <figcaption>4 · normalised samples (left) → classified palette (right); red rings = low-confidence cells</figcaption>
        </figure>
      )}
      <h3>Measurements</h3>
      <dl className="kv">
        <dt>candidates</dt>
        <dd>{r.candidates} quadrilateral(s), {r.attempts} decode attempt(s)</dd>
        {r.orientation && (
          <>
            <dt>orientation</dt>
            <dd>
              {String(r.orientation.rotation_deg)}° {r.orientation.mirrored ? "mirrored" : ""} · structure score{" "}
              {String(r.orientation.structure_score)} · palette ref {String(r.orientation.palette_reference)}
            </dd>
          </>
        )}
        {r.confidence && (
          <>
            <dt>colour confidence</dt>
            <dd>
              min {Math.min(...r.confidence).toFixed(2)} · median{" "}
              {[...r.confidence].sort((a, b) => a - b)[25].toFixed(2)} · {r.confidence.filter((c) => c < 0.15).length} ambiguous
            </dd>
          </>
        )}
        {r.debug.palette_refs && (
          <>
            <dt>palette refs</dt>
            <dd className="row">
              {r.debug.palette_refs.map((c, i) => (
                <span key={i} title={c.join(", ")} className="row" style={{ gap: 4 }}>
                  <i
                    style={{
                      width: 14,
                      height: 14,
                      display: "inline-block",
                      border: "1px solid #999",
                      background: `rgb(${c.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255)).join(",")})`,
                    }}
                  />
                  {PALETTE_NAMES[i]}
                </span>
              ))}
            </dd>
          </>
        )}
        <dt>time</dt>
        <dd>{r.elapsed_ms} ms</dd>
      </dl>
      <h3>Pipeline log</h3>
      <div className="log">{r.log.join("\n")}</div>
    </div>
  );
}

export function useAsync() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run, setError };
}

export function Bar({ rate }: { rate: number }) {
  const cls = rate >= 0.95 ? "good" : rate >= 0.5 ? "mid" : "low";
  return (
    <div className={"bar " + cls} title={(rate * 100).toFixed(0) + "%"}>
      <i style={{ width: `${rate * 100}%` }} />
    </div>
  );
}
