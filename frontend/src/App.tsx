import { useEffect, useState } from "react";
import { api, type EncodeInfo, type Info } from "./api";
import { Bench } from "./components/Bench";
import { Embed } from "./components/Embed";
import { Experiment, type Target } from "./components/Experiment";
import { Format } from "./components/Format";
import { Generate } from "./components/Generate";
import { Manager } from "./components/Manager";
import { Scan } from "./components/Scan";

const TABS = [
  ["generate", "Generate"],
  ["scan", "Scan"],
  ["experiment", "Experiment"],
  ["embed", "Embed"],
  ["manager", "Tag manager"],
  ["bench", "Benchmark"],
  ["format", "Format"],
] as const;
type TabId = (typeof TABS)[number][0];

function Mark() {
  return (
    <svg className="mark" viewBox="0 0 40 40" aria-hidden>
      <rect width="40" height="40" fill="#000" />
      <rect y="3" width="40" height="2" fill="#fff" />
      <rect y="20" width="40" height="2" fill="#fff" />
      <rect y="36" width="40" height="2" fill="#fff" />
      <path d="M4 5h10l-5 15z" fill="#ff0" />
      <path d="M9 20h10l-5-15z" fill="#f0f" />
      <path d="M14 5h10l-5 15z" fill="#0ff" />
      <path d="M19 20h10l-5-15z" fill="#ff0" />
      <path d="M4 22h10l-5 14z" fill="#0ff" />
      <path d="M9 36h10l-5-14z" fill="#ff0" />
      <path d="M14 22h10l-5 14z" fill="#f0f" />
      <path d="M24 22h10l-5 14z" fill="#0ff" />
    </svg>
  );
}

function initialTab(): TabId {
  const h = window.location.hash.slice(1);
  return (TABS.find(([id]) => id === h)?.[0] ?? "generate") as TabId;
}

export function App() {
  const [tab, setTab] = useState<TabId>(initialTab);
  const [info, setInfo] = useState<Info | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [target, setTarget] = useState<Target>({ mode: "mstag", prefix: 1, code: 9692, tag_id: "00001_0000009692" });

  useEffect(() => {
    api.info().then((i) => {
      setInfo(i);
      setOnline(true);
    }).catch(() => setOnline(false));
  }, []);
  useEffect(() => {
    window.location.hash = tab;
  }, [tab]);

  const use = (e: EncodeInfo) => {
    setTarget({ mode: e.mode, prefix: e.prefix, code: e.code, tag_id: e.tag_id });
    setTab("experiment");
  };

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <Mark />
          <div>
            <h1>HCCB Lab</h1>
            <div className="sub">a working reconstruction of Microsoft Tag, for experiments in visual codes</div>
          </div>
        </div>
        <div className="status-pill">
          <span><span className={"dot " + (online ? "on" : online === false ? "off" : "")} /> backend {online ? "online" : online === false ? "offline" : "…"}</span>
          <span>{window.isSecureContext ? "secure context · camera OK" : "insecure context · camera blocked"}</span>
          <span>target {target.tag_id}</span>
        </div>
      </header>
      <nav className="tabs">
        {TABS.map(([id, label], i) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            <span className="n">{String.fromCharCode(65 + i)}</span>
            {label}
          </button>
        ))}
      </nav>
      {online === false && (
        <div className="verdict bad">
          <div className="big">Backend unreachable</div>
          <div className="why">Start it with <code>cd backend && uvicorn app:app --port 8000</code> (see README).</div>
        </div>
      )}
      <main>
        {tab === "generate" && <Generate info={info} onUse={use} />}
        {tab === "scan" && <Scan />}
        {tab === "experiment" && <Experiment target={target} />}
        {tab === "embed" && <Embed target={target} />}
        {tab === "manager" && <Manager />}
        {tab === "bench" && <Bench info={info} />}
        {tab === "format" && <Format />}
      </main>
    </div>
  );
}
