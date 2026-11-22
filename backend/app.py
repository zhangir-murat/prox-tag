"""HCCB Lab - FastAPI server.

Run:  uvicorn app:app --reload --port 8000   (from backend/)
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hccb import benchmark, codec, detect, distort, embed, render
from hccb.resolver import Resolver, ResolverError

DB_PATH = os.environ.get("HCCB_DB", str(Path(__file__).parent / "data" / "hccb_lab.sqlite3"))
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
resolver = Resolver(DB_PATH)

app = FastAPI(title="HCCB Lab", version="0.1.0")
MAX_UPLOAD = 15 * 1024 * 1024


@app.exception_handler(ResolverError)
async def _resolver_err(_req, exc: ResolverError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(ValueError)
async def _value_err(_req, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def _png_b64(bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", bgr)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _jpg_b64(bgr: np.ndarray, q: int = 90) -> str:
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _encode_info(e: codec.EncodeResult) -> dict:
    return {
        "mode": e.mode,
        "prefix": e.prefix,
        "code": e.code,
        "tag_id": e.tag_id,
        "cells": e.cells,
        "colors": [codec.PALETTE_NAMES[c] for c in e.cells],
        "payload_hex": e.payload.hex(),
        "ecc_hex": e.ecc_bytes.hex(),
        "whitened_hex": e.whitened.hex(),
        "checksum": e.checksum,
        "details": e.details,
        "svg": render.render_svg(e.cells, title=e.tag_id),
    }


def _decode_upload(data: bytes) -> np.ndarray:
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "image too large (15 MB max)")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not read image (PNG/JPEG/WebP expected)")
    return img


def _scan_payload(r: detect.ScanResult) -> dict:
    d = r.to_dict()
    return d


# ------------------------------------------------------------------ info

MODE_INFO = {
    "mstag": {
        "name": "MS Tag (reverse-engineered)",
        "status": "UNVERIFIED historical compatibility",
        "prefix_max": 0xFFFF,
        "code_max": 0xFFFFFFFF,
        "summary": "5x10 cells, CRC16-X25 + RS(17,13) over GF(32) (x^5+x^2+1), XOR whitening, LSB-first packing. "
                   "Format per third-party UN_HCCB reverse engineering; not validated against original Microsoft Tag images.",
    },
    "exp1": {
        "name": "Experimental Tag Mode v1",
        "status": "HCCB Lab's own scheme - not Microsoft compatible",
        "prefix_max": 0xFF,
        "code_max": 0xFFFFFFFF,
        "summary": "Same geometry/palette. 8-bit prefix + 32-bit code protected by byte-aligned RS(11,5) over GF(256); "
                   "each cell maps to exactly one RS symbol; corrects 3 byte errors or 6 erasures.",
    },
}


@app.get("/api/info")
def info():
    return {"modes": MODE_INFO, "palette": {codec.PALETTE_NAMES[k]: v for k, v in codec.PALETTE_HEX.items()},
            "blend_modes": embed.BLEND_MODES, "benchmark_conditions": list(benchmark.CONDITIONS),
            "db": DB_PATH}


# ---------------------------------------------------------------- encode

class EncodeReq(BaseModel):
    mode: str = "mstag"
    prefix: int = 1
    code: int


@app.post("/api/encode")
def encode_ep(req: EncodeReq):
    e = codec.encode(req.mode, req.prefix, req.code)
    out = _encode_info(e)
    out["registered"] = resolver.get(req.mode, req.prefix, req.code)
    return out


@app.get("/api/symbol/{mode}/{prefix}/{code}.{ext}")
def symbol_file(mode: str, prefix: int, code: int, ext: str, width: int = 1200, width_mm: float | None = None,
                dpi: int | None = None, quiet: bool = True, download: bool = False):
    e = codec.encode(mode, prefix, code)
    name = f"hccb_{e.tag_id}"
    headers = {"Content-Disposition": f'attachment; filename="{name}.{ext}"'} if download else {}
    if ext == "svg":
        return Response(render.render_svg(e.cells, width_mm=width_mm, quiet_zone=quiet, title=e.tag_id),
                        media_type="image/svg+xml", headers=headers)
    if ext == "png":
        if width_mm and dpi:
            width = int(round(width_mm / 25.4 * dpi))
        width = max(64, min(width, 8000))
        rgb = render.render_rgb(e.cells, width, quiet_zone=quiet)
        return Response(render.encode_png(rgb, dpi), media_type="image/png", headers=headers)
    raise HTTPException(404, "ext must be svg or png")


# ------------------------------------------------------------------ tags

class TagCreate(BaseModel):
    url: str | None = None
    mode: str = "mstag"
    prefix: int = 1
    code: int | None = None
    label: str = ""


class TagPatch(BaseModel):
    url: str | None = Field(default=None)
    label: str | None = None
    enabled: bool | None = None
    clear_url: bool = False


@app.get("/api/tags")
def tags_list():
    return resolver.list()


@app.post("/api/tags")
def tags_create(req: TagCreate):
    t = resolver.create(req.mode, req.url, req.prefix, req.code, req.label)
    return {**t, "symbol": _encode_info(codec.encode(t["mode"], t["prefix"], t["code"]))}


@app.patch("/api/tags/{row_id}")
def tags_patch(row_id: int, req: TagPatch):
    fields = {"label": req.label, "enabled": req.enabled}
    if req.url is not None or req.clear_url:
        fields["url"] = None if req.clear_url else req.url
    return resolver.update(row_id, **fields)


@app.delete("/api/tags/{row_id}")
def tags_delete(row_id: int):
    resolver.delete(row_id)
    return {"deleted": row_id}


@app.get("/api/tags/{row_id}/scans")
def tags_scans(row_id: int):
    return resolver.scans(row_id)


@app.get("/api/scans")
def scans_all(limit: int = 200):
    return resolver.scans(None, limit)


@app.get("/api/stats")
def stats():
    return resolver.stats()


@app.get("/api/resolve/{mode}/{prefix}/{code}")
def resolve_ep(mode: str, prefix: int, code: int):
    return resolver.resolve(mode, prefix, code, record=False)


@app.get("/r/{mode}/{prefix}/{code}")
def redirect(mode: str, prefix: int, code: int, request: Request):
    r = resolver.resolve(mode, prefix, code, source="redirect", user_agent=request.headers.get("user-agent", ""))
    if r["outcome"] == "resolved":
        return RedirectResponse(r["url"], status_code=302)
    raise HTTPException(404 if r["outcome"] == "unassigned" else 410, f"tag {r['tag_id']} is {r['outcome']}")


# ------------------------------------------------------------------ scan

@app.post("/api/scan")
def scan_ep(request: Request, file: UploadFile = File(...), source: str = Form("upload"),
            record: bool = Form(True), debug: bool = Form(True)):
    img = _decode_upload(file.file.read())
    r = detect.scan_image(img, debug=debug)
    out = _scan_payload(r)
    if r.ok:
        out["resolution"] = resolver.resolve(r.mode, r.prefix, r.code, source=source,
                                             corrected=r.corrected_symbols + r.erasures,
                                             user_agent=request.headers.get("user-agent", ""), record=record)
    return out


# ------------------------------------------------------------ experiment

class ExperimentReq(BaseModel):
    mode: str = "mstag"
    prefix: int = 1
    code: int = 1
    params: dict = {}


@app.post("/api/experiment")
def experiment_ep(req: ExperimentReq):
    e = codec.encode(req.mode, req.prefix, req.code)
    p = distort.DistortParams.from_dict(req.params)
    p.canvas = max(200, min(p.canvas, 1600))
    img, meta = distort.apply(e.cells, p)
    clean = cv2.cvtColor(render.render_rgb(e.cells, 480), cv2.COLOR_RGB2BGR)
    r = detect.scan_image(img, debug=True)
    out = _scan_payload(r)
    out["expected"] = {"mode": e.mode, "prefix": e.prefix, "code": e.code, "tag_id": e.tag_id}
    out["recovered"] = bool(r.ok and r.mode == e.mode and r.prefix == e.prefix and r.code == e.code)
    out["wrong_id"] = bool(r.ok and not out["recovered"])
    out["original_image"] = _png_b64(clean)
    out["modified_image"] = _jpg_b64(img, 92) if p.jpeg_quality else _png_b64(img)
    out["params"] = p.to_dict()
    out["ground_truth_corners"] = meta["corners"]
    return out


# ----------------------------------------------------------------- embed

@app.post("/api/embed")
def embed_ep(file: UploadFile = File(...), mode: str = Form("mstag"), prefix: int = Form(1), code: int = Form(1),
             params: str = Form("{}"), sweep: str = Form("")):
    art = _decode_upload(file.file.read())
    h, w = art.shape[:2]
    if max(h, w) > 1600:  # keep experiments snappy
        s = 1600 / max(h, w)
        art = cv2.resize(art, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    e = codec.encode(mode, prefix, code)
    p = embed.EmbedParams.from_dict(json.loads(params or "{}"))
    comp, corners = embed.embed(art, e.cells, p)
    r = detect.scan_image(comp, debug=True)
    out = _scan_payload(r)
    out["recovered"] = bool(r.ok and r.mode == e.mode and r.prefix == e.prefix and r.code == e.code)
    out["wrong_id"] = bool(r.ok and not out["recovered"])
    out["composite"] = _jpg_b64(comp, 92)
    out["expected"] = {"tag_id": e.tag_id}
    out["corners"] = corners
    if sweep:
        # sweep one numeric parameter, e.g. "opacity:0.1,0.2,...". Each point is a real scan.
        key, _, vals = sweep.partition(":")
        if key not in ("opacity", "frame_opacity", "scale", "rotation"):
            raise HTTPException(400, "sweep key must be opacity, frame_opacity, scale or rotation")
        results = []
        for v in [float(x) for x in vals.split(",") if x.strip()][:25]:
            d = json.loads(params or "{}")
            d[key] = v
            c2, _ = embed.embed(art, e.cells, embed.EmbedParams.from_dict(d))
            r2 = detect.scan_image(c2, debug=False)
            results.append({"value": v, "recovered": bool(r2.ok and r2.code == e.code and r2.prefix == e.prefix and r2.mode == e.mode),
                            "wrong_id": bool(r2.ok and r2.code != e.code), "reason": r2.reason,
                            "corrections": r2.corrected_symbols + r2.erasures})
        out["sweep"] = {"key": key, "results": results}
    return out


# ------------------------------------------------------------- benchmark

class BenchReq(BaseModel):
    conditions: list[str] | None = None
    n: int = 10
    modes: list[str] = ["mstag", "exp1"]
    seed: int = 1234


@app.post("/api/benchmark")
def benchmark_ep(req: BenchReq):
    n = max(1, min(req.n, 100))
    return benchmark.run(req.conditions, n=n, modes=tuple(req.modes), seed=req.seed)


@app.post("/api/false-positive")
def fp_ep(n: int = 30):
    return benchmark.false_positive_trial(max(1, min(n, 200)))


# -------------------------------------------------------- static frontend

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
