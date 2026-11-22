import { useEffect, useState } from "react";
import { api, symbolUrl, type EncodeInfo, type Info, type Mode, type Tag } from "../api";
import { mstagCells, parseTagId } from "../codec";
import { Field, PALETTE, PALETTE_NAMES, Seg, useAsync } from "./common";

export function Generate({ info, onUse }: { info: Info | null; onUse: (e: EncodeInfo) => void }) {
  const [input, setInput] = useState("https://example.com/hello");
  const [mode, setMode] = useState<Mode>("mstag");
  const [prefix, setPrefix] = useState(1);
  const [label, setLabel] = useState("");
  const [enc, setEnc] = useState<EncodeInfo | null>(null);
  const [tag, setTag] = useState<Tag | null>(null);
  const [mm, setMm] = useState(25);
  const [dpi, setDpi] = useState(600);
  const { busy, error, run } = useAsync();

  const isUrl = /^https?:\/\//i.test(input.trim());
  const parsedId = parseTagId(input);
  const numeric = /^\d+$/.test(input.trim());
  const mi = info?.modes[mode];

  async function go() {
    await run(async () => {
      if (isUrl) {
        const t = await api.createTag({ url: input.trim(), mode, prefix, label });
        setTag(t);
        setEnc(t.symbol);
      } else if (parsedId) {
        setMode(parsedId.mode);
        setPrefix(parsedId.prefix);
        const e = await api.encode(parsedId.mode, parsedId.prefix, parsedId.code);
        setEnc(e);
        setTag(e.registered ?? null);
      } else if (numeric) {
        const e = await api.encode(mode, prefix, Number(input.trim()));
        setEnc(e);
        setTag(e.registered ?? null);
      } else {
        throw new Error("Enter an http(s) URL, a numeric code, or a tag id like 00001_0000009692");
      }
    });
  }

  async function register() {
    if (!enc) return;
    await run(async () => {
      const t = await api.createTag({ mode: enc.mode, prefix: enc.prefix, code: enc.code, url: null, label });
      setTag(t);
    });
  }

  // client-side cross-check of the server encoder (MS Tag mode)
  const [xcheck, setXcheck] = useState<string>("");
  useEffect(() => {
    if (!enc || enc.mode !== "mstag") return setXcheck("");
    try {
      const same = mstagCells(enc.prefix, enc.code).join() === enc.cells.join();
      setXcheck(same ? "TS encoder agrees with server ✓" : "TS encoder DISAGREES with server ✗");
    } catch (e) {
      setXcheck(String(e));
    }
  }, [enc]);

  return (
    <div className="grid cols-side">
      <div className="panel">
        <h2>A · Generate</h2>
        <Field label="URL, numeric code, or tag id">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go()}
            placeholder="https://… or 9692 or 00001_0000009692"
          />
        </Field>
        <div className="note small">
          {isUrl
            ? "URL → a fresh random 32-bit code is allocated and stored in the local resolver."
            : parsedId
              ? `Tag id → ${parsedId.mode} prefix ${parsedId.prefix} code ${parsedId.code}`
              : numeric
                ? "Numeric code → encoded directly (register it afterwards to attach a destination)."
                : "Waiting for a URL or numeric ID."}
        </div>
        <Field label="Encoding mode">
          <Seg
            value={mode}
            onChange={setMode}
            options={[
              { v: "mstag", label: "MS Tag (RE)" },
              { v: "exp1", label: "Experimental v1" },
            ]}
          />
        </Field>
        {mi && (
          <div className={"verdict " + (mode === "mstag" ? "warn" : "ok")} style={{ padding: "8px 10px" }}>
            <div className="small mono" style={{ fontWeight: 600 }}>{mi.status}</div>
            <div className="small">{mi.summary}</div>
          </div>
        )}
        <Field label={`Prefix (0–${mi?.prefix_max ?? "…"})`}>
          <input type="number" min={0} max={mi?.prefix_max} value={prefix} onChange={(e) => setPrefix(Number(e.target.value))} />
        </Field>
        <Field label="Label (optional)">
          <input type="text" value={label} onChange={(e) => setLabel(e.target.value)} />
        </Field>
        <button className="btn" onClick={go} disabled={busy}>
          {isUrl ? "Create tag" : "Encode"}
        </button>
        {error && <div className="err">{error}</div>}
      </div>

      <div className="panel">
        {!enc ? (
          <p className="lede">Enter a URL or an identifier to generate a symbol. Every symbol is derived deterministically from its mode, prefix and code.</p>
        ) : (
          <div className="grid cols-2">
            <div>
              <div className="tagview" dangerouslySetInnerHTML={{ __html: enc.svg }} />
              <h3>Export</h3>
              <div className="row">
                <a className="btn small" href={symbolUrl(enc.mode, enc.prefix, enc.code, "svg", { download: true })}>SVG</a>
                <a className="btn small" href={symbolUrl(enc.mode, enc.prefix, enc.code, "png", { width: 1200, download: true })}>PNG 1200px</a>
                <a className="btn small ghost" href={symbolUrl(enc.mode, enc.prefix, enc.code, "png", { width: 300, download: true })}>PNG 300px</a>
              </div>
              <h3>Print size</h3>
              <div className="row">
                <input type="number" style={{ width: 90 }} value={mm} min={8} max={500} onChange={(e) => setMm(Number(e.target.value))} />
                <span className="mono small">mm wide @</span>
                <select style={{ width: 100 }} value={dpi} onChange={(e) => setDpi(Number(e.target.value))}>
                  {[150, 300, 600, 1200].map((d) => (
                    <option key={d} value={d}>{d} dpi</option>
                  ))}
                </select>
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <a className="btn small" href={symbolUrl(enc.mode, enc.prefix, enc.code, "svg", { width_mm: mm, download: true })}>SVG {mm} mm</a>
                <a className="btn small" href={symbolUrl(enc.mode, enc.prefix, enc.code, "png", { width_mm: mm, dpi, download: true })}>
                  PNG {Math.round((mm / 25.4) * dpi)}px
                </a>
              </div>
              <div className="note small">
                Microsoft recommended ≥ 3/4 in (≈19 mm) for printed Tags (MSR HCCB page: smallest capacity readable at 3/4"). Test your own
                printer + phone combination with the Scan tab.
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn ghost small" onClick={() => onUse(enc)}>Use in Experiment / Embed →</button>
              </div>
            </div>
            <div>
              <dl className="kv">
                <dt>tag id</dt>
                <dd style={{ fontWeight: 600 }}>{enc.tag_id}</dd>
                <dt>mode</dt>
                <dd>{enc.mode}</dd>
                <dt>prefix</dt>
                <dd>{enc.prefix} (0x{enc.prefix.toString(16)})</dd>
                <dt>code</dt>
                <dd>{enc.code} (0x{enc.code.toString(16).padStart(8, "0")})</dd>
                {enc.checksum !== null && (
                  <>
                    <dt>CRC16-X25</dt>
                    <dd>0x{enc.checksum.toString(16).padStart(4, "0")}</dd>
                  </>
                )}
                <dt>resolver</dt>
                <dd>
                  {tag ? (
                    <>
                      #{tag.id} → {tag.url ?? <span className="muted">no destination</span>} {tag.enabled ? "" : "(disabled)"}
                    </>
                  ) : (
                    <>
                      not registered{" "}
                      <button className="btn small ghost" onClick={register} disabled={busy}>register</button>
                    </>
                  )}
                </dd>
              </dl>
              <h3>Bytes</h3>
              <div className="hex">
                <div><span className="muted">payload </span><span className="d">{enc.payload_hex}</span></div>
                <div><span className="muted">ecc     </span><span className="p">{enc.ecc_hex}</span></div>
                <div><span className="muted">whitened</span> {enc.whitened_hex}</div>
              </div>
              <div className="small muted mono" style={{ marginTop: 6 }}>{String(enc.details.layout ?? "")}</div>
              {xcheck && <div className="small mono" style={{ marginTop: 6 }}>{xcheck}</div>}
              <h3>Cells (row-major, 0 = top-left)</h3>
              <div className="cellmap">
                {enc.cells.map((c, i) => (
                  <div
                    key={i}
                    title={`cell ${i}: ${enc.colors[i]}`}
                    style={{
                      background: PALETTE[c],
                      color: c === 2 ? "#fff" : "#000",
                      outline: i >= 44 ? "2px solid var(--ink-3)" : undefined,
                    }}
                  >
                    {i}:{PALETTE_NAMES[c]}
                  </div>
                ))}
              </div>
              <div className="small muted" style={{ marginTop: 6 }}>Outlined: 44–45 mode filler, 46–49 calibration (Y M K C).</div>
              {enc.details.data_symbols_gf32 !== undefined && (
                <>
                  <h3>GF(32) symbols</h3>
                  <div className="hex">
                    data {JSON.stringify(enc.details.data_symbols_gf32)}
                    <br />
                    parity <span className="p">{JSON.stringify(enc.details.parity_symbols_gf32)}</span>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
