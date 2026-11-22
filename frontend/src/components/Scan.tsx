import { useEffect, useRef, useState } from "react";
import { api, type ScanResult } from "../api";
import { DropZone, ScanDetails, Verdict, useAsync } from "./common";

function Resolution({ r, autoOpen }: { r: ScanResult; autoOpen: boolean }) {
  const res = r.resolution;
  useEffect(() => {
    if (autoOpen && res?.outcome === "resolved" && res.url) window.location.assign(res.url);
  }, [autoOpen, res]);
  if (!r.ok || !res) return null;
  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 style={{ marginTop: 0 }}>Resolver lookup</h3>
      {res.outcome === "resolved" && (
        <div className="row">
          <span className="badge ok">resolved</span>
          <a className="btn" href={res.url!} target="_blank" rel="noreferrer noopener">Open {res.url}</a>
        </div>
      )}
      {res.outcome === "disabled" && (
        <div className="row"><span className="badge warn">disabled</span> Tag #{res.tag?.id} exists but is disabled.</div>
      )}
      {res.outcome === "unassigned" && (
        <div className="row">
          <span className="badge mute">unassigned</span>
          <span className="small">
            Valid symbol, but no destination is stored for {res.tag_id}. (Decoded historical Tags land here — Microsoft's server mapping is gone.)
          </span>
        </div>
      )}
    </div>
  );
}

export function Scan() {
  const [result, setResult] = useState<ScanResult | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [camOn, setCamOn] = useState(false);
  const [camErr, setCamErr] = useState<string | null>(null);
  const [frames, setFrames] = useState(0);
  const [lastReason, setLastReason] = useState("");
  const [autoOpen, setAutoOpen] = useState(false);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const loopRef = useRef(false);
  const { busy, error, run } = useAsync();

  async function scanFile(f: Blob, source: string) {
    setPreview(URL.createObjectURL(f));
    const r = await run(() => api.scan(f, { source }));
    if (r) setResult(r);
  }

  async function startCam() {
    setCamErr(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCamErr(
        window.isSecureContext
          ? "This browser does not expose a camera API."
          : "Camera requires a secure context. Open the app via https:// (see README: npm run dev:https) or http://localhost.",
      );
      return;
    }
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      streamRef.current = s;
      if (videoRef.current) {
        videoRef.current.srcObject = s;
        await videoRef.current.play();
      }
      setCamOn(true);
      setResult(null);
      loopRef.current = true;
      loop();
    } catch (e) {
      setCamErr(`Camera unavailable: ${e instanceof Error ? e.message : e}`);
    }
  }

  function stopCam() {
    loopRef.current = false;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCamOn(false);
  }
  useEffect(() => () => stopCam(), []);

  async function grab(): Promise<Blob | null> {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    const c = document.createElement("canvas");
    const scale = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight));
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height);
    return new Promise((res) => c.toBlob((b) => res(b), "image/jpeg", 0.88));
  }

  async function loop() {
    while (loopRef.current) {
      const blob = await grab();
      if (blob) {
        try {
          const r = await api.scan(blob, { source: "camera", record: false, debug: false });
          setFrames((n) => n + 1);
          if (r.ok) {
            loopRef.current = false;
            setPreview(URL.createObjectURL(blob));
            // re-run on the same frame with debug output + record the scan event
            const full = await api.scan(blob, { source: "camera", record: true, debug: true });
            setResult(full);
            if ("vibrate" in navigator) navigator.vibrate?.(80);
            stopCam();
            return;
          }
          setLastReason(r.reason.split(". ")[0]);
        } catch (e) {
          setLastReason(String(e));
        }
      }
      await new Promise((r) => setTimeout(r, 120));
    }
  }

  return (
    <div className="grid cols-side">
      <div className="panel">
        <h2>B · Scan</h2>
        <h3 style={{ marginTop: 0 }}>Camera</h3>
        <div className="video-wrap" style={{ display: camOn ? "block" : "none" }}>
          <video ref={videoRef} playsInline muted />
          <div className="reticle" />
          <div className="hud">frames {frames} · {lastReason || "searching…"}</div>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {!camOn ? (
            <button className="btn" onClick={startCam}>Start camera</button>
          ) : (
            <button className="btn ghost" onClick={stopCam}>Stop</button>
          )}
          <select style={{ width: 150 }} value={facing} onChange={(e) => setFacing(e.target.value as "environment" | "user")} disabled={camOn}>
            <option value="environment">rear camera</option>
            <option value="user">front / webcam</option>
          </select>
        </div>
        <label className="row small" style={{ marginTop: 8 }}>
          <input type="checkbox" checked={autoOpen} onChange={(e) => setAutoOpen(e.target.checked)} /> open destination automatically
        </label>
        {camErr && <div className="err">{camErr}</div>}
        <div className="note small">
          Frames are sent to the local backend ~5×/s; the first frame that passes Reed–Solomon + checksum is re-analysed with full debug output and
          recorded as a scan event.
        </div>
        <h3>Upload</h3>
        <DropZone onFile={(f) => scanFile(f, "upload")} />
        <label className="btn ghost small" style={{ marginTop: 8 }}>
          Take photo (mobile)
          <input type="file" accept="image/*" capture="environment" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && scanFile(e.target.files[0], "photo")} />
        </label>
        {busy && <div className="small mono" style={{ marginTop: 8 }}>scanning…</div>}
        {error && <div className="err">{error}</div>}
        {preview && (
          <figure style={{ marginTop: 12 }}>
            <img src={preview} alt="input" />
            <figcaption>input</figcaption>
          </figure>
        )}
      </div>
      <div className="panel">
        {!result ? (
          <p className="lede">Point the camera at a tag or upload a photo. The full pipeline — detection, rectification, colour normalisation, cell classification, Reed–Solomon and checksum — is shown here.</p>
        ) : (
          <>
            <Verdict r={result} />
            <Resolution r={result} autoOpen={autoOpen} />
            <ScanDetails r={result} />
          </>
        )}
      </div>
    </div>
  );
}
