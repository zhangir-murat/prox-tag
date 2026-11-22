"""Image -> tag ID scanner (OpenCV).

Pipeline
  1. Pre-process: downscale, pad with white.
  2. Candidate search: dark masks (global Otsu + local adaptive on HSV value),
     multi-scale morphological closing to merge the black strips that the white
     row separators cut apart, convex hulls -> quadrilaterals.
  3. Corner refinement: robust line fit on the four hull edges.
  4. For each candidate and each of the 8 dihedral orientations: perspective
     warp to the canonical frame, structural score (white separators, black
     side bars, thick bottom bar) to order attempts.
  5. Vertical grid refinement from the separator profile on the side bars.
  6. Lighting normalisation with measured black (frame) and white (separator)
     references, per channel.
  7. Shrunken-triangle median sampling of the 50 cells.
  8. Colour classification seeded by the calibration cells (46-49) or by the
     ideal palette, refined with two k-means iterations; per-cell confidence.
  9. Mode detection from the filler cells, de-whitening, Reed-Solomon
     errors-and-erasures decoding (low-confidence cells become erasures,
     plus Chase-style second-choice trials), checksum verification.
"""
from __future__ import annotations

import base64
import itertools
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import codec
from .codec import CAL_POS, CALIBRATION, MODES, N_CELLS, PALETTE_RGB
from .geometry import GEOM, ROWS

WARP_SCALE = 1.0  # canonical px per geometry unit
CW = int(round(GEOM.frame_w * WARP_SCALE))
CH = int(round(GEOM.frame_h * WARP_SCALE))
IDEAL = np.array([[c / 255 for c in PALETTE_RGB[i]] for i in range(4)], dtype=np.float32)


def _build_cell_masks(shrink: float = 0.55):
    idxs = []
    for i in range(N_CELLS):
        pts = np.array(GEOM.triangle(i), dtype=np.float32) * WARP_SCALE
        c = pts.mean(axis=0)
        pts = c + (pts - c) * shrink
        m = np.zeros((CH, CW), np.uint8)
        cv2.fillConvexPoly(m, np.round(pts).astype(np.int32), 1)
        ys, xs = np.nonzero(m)
        idxs.append((ys, xs))
    return idxs


CELL_PIX = _build_cell_masks()


@dataclass
class ScanResult:
    ok: bool
    mode: str | None = None
    prefix: int | None = None
    code: int | None = None
    tag_id: str | None = None
    checksum_ok: bool | None = None
    corrected_symbols: int = 0
    erasures: int = 0
    strategy: str = ""
    orientation: dict | None = None
    quad: list[list[float]] | None = None
    cells: list[int] | None = None
    confidence: list[float] | None = None
    reason: str = ""
    log: list[str] = field(default_factory=list)
    candidates: int = 0
    attempts: int = 0
    elapsed_ms: float = 0.0
    debug: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        return d


def _b64png(img_bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img_bgr)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _b64jpg(img_bgr: np.ndarray, q: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


# ----------------------------------------------------------- candidates

def _order_quad(pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]  # clockwise in image coords (y down)
    start = int(np.argmin(pts[:, 0] + pts[:, 1]))
    return np.roll(pts, -start, axis=0)


def _quad_from_contour(cnt: np.ndarray) -> np.ndarray | None:
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in (0.02, 0.035, 0.05, 0.07, 0.1):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4 and cv2.isContourConvex(ap):
            return _order_quad(ap.reshape(4, 2))
    box = cv2.boxPoints(cv2.minAreaRect(hull))
    return _order_quad(box)


def _refine_quad(quad: np.ndarray, cnt: np.ndarray) -> np.ndarray:
    """Fit a line to the contour points along each edge and intersect them."""
    pts = cnt.reshape(-1, 2).astype(np.float32)
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        ab = b - a
        L = float(np.linalg.norm(ab))
        if L < 8:
            return quad
        u = ab / L
        nrm = np.array([-u[1], u[0]], np.float32)
        rel = pts - a
        t = rel @ u
        d = np.abs(rel @ nrm)
        sel = (t > 0.12 * L) & (t < 0.88 * L) & (d < max(3.0, 0.04 * L))
        if sel.sum() < 6:
            return quad
        vx, vy, x0, y0 = cv2.fitLine(pts[sel], cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    out = []
    for i in range(4):
        p1, d1 = lines[(i - 1) % 4]
        p2, d2 = lines[i]
        A = np.array([d1, -d2]).T
        if abs(np.linalg.det(A)) < 1e-6:
            return quad
        t = np.linalg.solve(A, p2 - p1)
        out.append(p1 + t[0] * d1)
    out = np.array(out, np.float32)
    if np.max(np.linalg.norm(out - quad, axis=1)) > 0.15 * np.sqrt(cv2.contourArea(quad)):
        return quad
    return out


def find_candidates(img: np.ndarray, log: list[str] | None = None, debug: dict | None = None,
                    max_candidates: int = 10) -> list[np.ndarray]:
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    V = cv2.GaussianBlur(hsv[:, :, 2], (3, 3), 0)
    masks = []
    t, otsu = cv2.threshold(V, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    masks.append(("otsu", otsu))
    blk = max(15, (min(h, w) // 6) | 1)
    adapt = cv2.adaptiveThreshold(V, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, blk, 25)
    masks.append(("adaptive", adapt))
    if log is not None:
        log.append(f"dark masks: Otsu threshold V<{t:.0f}; adaptive block {blk}px")
    quads: list[tuple[float, np.ndarray]] = []
    md = min(h, w)
    for name, m in masks:
        for kf in (0.008, 0.02, 0.045):
            k = max(3, int(md * kf)) | 1
            closed = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
            closed = cv2.morphologyEx(closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
            if debug is not None and name == "otsu" and kf == 0.02:
                debug["mask"] = closed
            cnts, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
            for c in cnts:
                a = cv2.contourArea(c)
                if a < h * w * 0.0012 or a > h * w * 0.97:
                    continue
                q = _quad_from_contour(c)
                qa = cv2.contourArea(q)
                if qa < h * w * 0.0012:
                    continue
                sides = [np.linalg.norm(q[i] - q[(i + 1) % 4]) for i in range(4)]
                if min(sides) < 12 or max(sides) / min(sides) > 4:
                    continue
                fill = a / max(qa, 1)
                if fill < 0.25:
                    continue
                q = _refine_quad(q, c)
                quads.append((qa, q))
    # de-duplicate
    quads.sort(key=lambda x: -x[0])
    out: list[np.ndarray] = []
    for _, q in quads:
        if all(np.max(np.linalg.norm(q - o, axis=1)) > 0.04 * np.sqrt(cv2.contourArea(o)) for o in out):
            out.append(q)
        if len(out) >= max_candidates:
            break
    if log is not None:
        log.append(f"{len(out)} candidate quadrilateral(s) after de-duplication")
    return out


# -------------------------------------------------------------- per-candidate

DST = np.array([[0, 0], [CW - 1, 0], [CW - 1, CH - 1], [0, CH - 1]], np.float32)
ORIENTATIONS = [(mirror, rot) for mirror in (False, True) for rot in range(4)]


def _src_for(quad: np.ndarray, mirror: bool, rot: int) -> np.ndarray:
    q = quad[[0, 3, 2, 1]] if mirror else quad
    return np.roll(q, -rot, axis=0).astype(np.float32)


def _structure_score(warp_gray: np.ndarray, yoff: float = 0.0, ysc: float = 1.0) -> float:
    g = warp_gray.astype(np.float32) / 255.0
    side = np.concatenate([g[:, 3:int(GEOM.black_side) - 3], g[:, CW - int(GEOM.black_side) + 3:CW - 3]], axis=1).mean(axis=1)
    sep_vals, bar_vals = [], []
    for i in range(ROWS + 1):
        y0 = GEOM.separator_y(i)
        yc = int(round((y0 + GEOM.separator / 2) * ysc + yoff))
        if 0 <= yc < CH:
            sep_vals.append(side[yc])
        if i < ROWS:
            ym = int(round((y0 + GEOM.separator + GEOM.tri_h / 2) * ysc + yoff))
            if 0 <= ym < CH:
                bar_vals.append(side[ym])
    bottom = g[int(CH - GEOM.black_bottom * 0.8):CH - 3, 3:CW - 3].mean()
    top = g[3:int(GEOM.black_top * 0.6), 3:CW - 3].mean()
    return float(np.mean(sep_vals) - np.mean(bar_vals) - 0.5 * bottom - 0.25 * top) if sep_vals and bar_vals else -1.0


def _refine_rows(warp_gray: np.ndarray) -> tuple[float, float]:
    """Search small vertical offset/scale maximising the separator contrast."""
    best = (-9.0, 0.0, 1.0)
    for ysc in (0.97, 0.985, 1.0, 1.015, 1.03):
        for yoff in range(-6, 7, 2):
            s = _structure_score(warp_gray, yoff, ysc)
            if s > best[0]:
                best = (s, yoff, ysc)
    return best[1], best[2]


def _sample(warp: np.ndarray, yoff: float, ysc: float) -> np.ndarray:
    out = np.zeros((N_CELLS, 3), np.float32)
    for i, (ys, xs) in enumerate(CELL_PIX):
        yy = np.clip(np.round(ys * ysc + yoff).astype(int), 0, CH - 1)
        out[i] = np.median(warp[yy, xs], axis=0)
    return out


def _references(warp: np.ndarray, yoff: float, ysc: float) -> tuple[np.ndarray, np.ndarray]:
    """Measured black (frame bars) and white (separators) per channel."""
    sb = int(GEOM.black_side)
    whites, blacks = [], []
    for i in range(ROWS + 1):
        y0 = GEOM.separator_y(i) * ysc + yoff
        a, b = int(round(y0 + 3)), int(round(y0 + GEOM.separator * ysc - 3))
        if b > a:
            whites.append(warp[a:b, 4:CW - 4].reshape(-1, 3))
    for i in range(ROWS):
        y0 = (GEOM.separator_y(i) + GEOM.separator + 6) * ysc + yoff
        y1 = (GEOM.separator_y(i + 1) - 6) * ysc + yoff
        blacks.append(warp[int(y0):int(y1), 4:sb - 4].reshape(-1, 3))
        blacks.append(warp[int(y0):int(y1), CW - sb + 4:CW - 4].reshape(-1, 3))
    blacks.append(warp[int(CH - GEOM.black_bottom * ysc + 4):CH - 4, 4:CW - 4].reshape(-1, 3))
    W = np.percentile(np.concatenate(whites), 60, axis=0)
    K = np.percentile(np.concatenate(blacks), 40, axis=0)
    return K, W


def _classify(samples: np.ndarray, refs: np.ndarray, iters: int = 2):
    refs = refs.copy()
    for it in range(iters + 1):
        d = np.linalg.norm(samples[:, None, :] - refs[None, :, :], axis=2)  # 50x4
        lab = np.argmin(d, axis=1)
        if it == iters:
            break
        for k in range(4):
            sel = lab == k
            if sel.sum() >= 2:
                refs[k] = 0.5 * refs[k] + 0.5 * samples[sel].mean(axis=0)
    order = np.sort(d, axis=1)
    conf = (order[:, 1] - order[:, 0]) / (order[:, 1] + order[:, 0] + 1e-6)
    second = np.argsort(d, axis=1)[:, 1]
    return lab.astype(int), conf, second.astype(int), refs


def _decode_with_strategies(cells: list[int], conf: np.ndarray, second: np.ndarray, modes) -> tuple[codec.DecodeResult, str, int]:
    attempts = 0
    res = codec.decode_cells(cells, modes=modes)
    attempts += 1
    if res.ok:
        return res, "hard-decision", attempts
    first_res = res
    data_order = [int(i) for i in np.argsort(conf) if i < codec.N_DATA_CELLS]
    # filler may be misread: if mode can't be determined, try both fillers when low confidence
    variants = [cells]
    if codec.detect_mode(cells) is None:
        for f in (codec.MSTAG_FILLER, codec.EXP1_FILLER):
            v = list(cells)
            v[44:46] = f
            variants.append(v)
    for base in variants:
        mode = codec.detect_mode(base)
        if mode is None or mode not in modes:
            continue
        # erasure decoding with the k least confident data cells
        max_k = 2 if mode == "mstag" else 4
        for k in range(1, max_k + 1):
            r = codec.decode_cells(base, erasure_cells=data_order[:k], modes=modes)
            attempts += 1
            if r.ok:
                return r, f"erasures({k} low-confidence cells)", attempts
        # Chase: second-choice substitution for the least confident cells
        cand = data_order[:5]
        for n in (1, 2, 3):
            for combo in itertools.combinations(cand, n):
                v = list(base)
                for c in combo:
                    v[c] = int(second[c])
                r = codec.decode_cells(v, modes=modes, assisted=True)
                attempts += 1
                if r.ok:
                    return r, f"chase(substituted {n} cell(s))", attempts
    return first_res, "failed", attempts


def scan_image(img_bgr: np.ndarray, debug: bool = True, modes: tuple[str, ...] = MODES,
               max_dim: int = 1000) -> ScanResult:
    t0 = time.perf_counter()
    log: list[str] = []
    dbg: dict = {}
    if img_bgr is None or img_bgr.size == 0:
        return ScanResult(False, reason="empty image")
    if img_bgr.ndim == 2:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    if img_bgr.shape[2] == 4:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2BGR)
    h0, w0 = img_bgr.shape[:2]
    s = min(1.0, max_dim / max(h0, w0))
    img = cv2.resize(img_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img_bgr.copy()
    pad = max(8, int(0.03 * max(img.shape[:2])))
    img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    log.append(f"input {w0}x{h0}px, working scale {s:.3f}, padded {pad}px")

    cands = find_candidates(img, log, dbg if debug else None)
    res = ScanResult(False, candidates=len(cands), log=log)
    if not cands:
        res.reason = "No dark rectangular frame found. Make sure the whole tag including its black border is visible, in focus, and not too small."
        _finish(res, t0, img, None, None, dbg, debug, s, pad)
        return res

    best_fail = None
    tried = 0
    for ci, quad in enumerate(cands):
        plans = []
        for mirror, rot in ORIENTATIONS:
            src = _src_for(quad, mirror, rot)
            M = cv2.getPerspectiveTransform(src, DST)
            warp = cv2.warpPerspective(img, M, (CW, CH), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            gray = cv2.cvtColor(warp, cv2.COLOR_BGR2GRAY)
            lo, hi = np.percentile(gray, (3, 97))
            gray = np.clip((gray.astype(np.float32) - lo) * (255.0 / max(hi - lo, 8.0)), 0, 255).astype(np.uint8)
            plans.append((_structure_score(gray), mirror, rot, warp, gray, src))
        plans.sort(key=lambda p: -p[0])
        if plans[0][0] < 0.12:
            log.append(f"candidate {ci}: structure score {plans[0][0]:.2f} too low (no separator pattern) - skipped")
            continue
        for score, mirror, rot, warp, gray, src in plans:
            if score < 0.5 * plans[0][0]:
                continue
            tried += 1
            yoff, ysc = _refine_rows(gray)
            rgb = cv2.cvtColor(warp, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            K, W = _references(rgb, yoff, ysc)
            span = np.maximum(W - K, 0.08)
            raw = _sample(rgb, yoff, ysc)
            norm = np.clip((raw - K) / span, -0.2, 1.2)
            # Orientation sanity: calibration cell 48 is black and must be the darkest of 46-49
            # under any plausible lighting / hue shift. Rejects most wrong orientations early.
            cal_lum = norm[CAL_POS].sum(axis=1)
            if not (cal_lum[2] < np.min(np.delete(cal_lum, 2)) - 0.15):
                log.append(f"candidate {ci} rot={rot*90} mirror={mirror}: calibration cell 48 is not the darkest - orientation rejected")
                continue
            for refname in ("calibration", "ideal"):
                if refname == "calibration":
                    refs = norm[CAL_POS]
                    dmin = min(np.linalg.norm(refs[i] - refs[j]) for i in range(4) for j in range(i + 1, 4))
                    if dmin < 0.12:
                        continue
                else:
                    refs = IDEAL
                labels, conf, second, final_refs = _classify(norm, refs)
                cells = [int(x) for x in labels]
                if refname == "ideal" and cells[46:50] != CALIBRATION:
                    # let the trailer check speak for itself, but no need to try harder
                    pass
                r, strategy, n_att = _decode_with_strategies(cells, conf, second, modes)
                res.attempts += n_att
                orient = {"mirrored": mirror, "rotation_deg": rot * 90, "structure_score": round(score, 3),
                          "row_offset_px": yoff, "row_scale": ysc, "palette_reference": refname}
                if r.ok:
                    res.ok = True
                    res.mode, res.prefix, res.code, res.tag_id = r.mode, r.prefix, r.code, r.tag_id
                    res.checksum_ok = r.checksum_ok
                    res.corrected_symbols = len(r.corrected_symbols)
                    res.erasures = len(r.erasures)
                    res.strategy = strategy
                    res.orientation = orient
                    res.cells, res.confidence = cells, [round(float(c), 3) for c in conf]
                    q_orig = (src - pad) / s
                    res.quad = q_orig.round(1).tolist()
                    log.append(f"candidate {ci} orientation rot={rot*90} mirror={mirror} refs={refname}: "
                               f"DECODED {r.tag_id} via {strategy} ({len(r.corrected_symbols)} RS symbol corrections, {len(r.erasures)} erasures)")
                    _finish(res, t0, img, src, warp, dbg, debug, s, pad, norm, cells, conf, final_refs, (yoff, ysc))
                    return res
                fail = (score, ci, mirror, rot, refname, r.reason, cells, conf, src, warp, norm, final_refs, (yoff, ysc))
                if best_fail is None or score > best_fail[0]:
                    best_fail = fail
                log.append(f"candidate {ci} rot={rot*90} mirror={mirror} refs={refname}: {r.reason}")
    res.reason = "Frame(s) found but no orientation produced a valid codeword." if best_fail else \
        "Dark regions found, but none shows the row-separator structure of a tag."
    if best_fail:
        score, ci, mirror, rot, refname, why, cells, conf, src, warp, norm, refs, rows = best_fail
        res.reason += f" Best attempt (candidate {ci}, rotation {rot*90}°, {refname} palette): {why}."
        low = int(np.sum(np.array(conf) < 0.15))
        if low > 6:
            res.reason += f" {low} cells have ambiguous colours - check lighting, blur, or colour cast."
        res.cells, res.confidence = cells, [round(float(c), 3) for c in conf]
        res.quad = ((src - pad) / s).round(1).tolist()
        res.orientation = {"mirrored": mirror, "rotation_deg": rot * 90, "structure_score": round(score, 3), "palette_reference": refname}
        _finish(res, t0, img, src, warp, dbg, debug, s, pad, norm, cells, conf, refs, rows)
    else:
        _finish(res, t0, img, cands[0] if cands else None, None, dbg, debug, s, pad)
    return res


def _finish(res: ScanResult, t0, img, quad, warp, dbg, debug, s, pad, norm=None, cells=None, conf=None, refs=None, rows=None):
    res.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    if not debug:
        return
    out = {}
    if "mask" in dbg:
        out["mask"] = _b64png(dbg["mask"])
    ov = img.copy()
    if quad is not None:
        q = np.round(quad).astype(np.int32)
        color = (60, 220, 60) if res.ok else (40, 40, 230)
        cv2.polylines(ov, [q], True, color, max(2, ov.shape[1] // 250))
        cv2.circle(ov, tuple(int(v) for v in q[0]), max(4, ov.shape[1] // 120), (255, 160, 0), -1)
    out["detection"] = _b64jpg(ov)
    if warp is not None:
        out["warped"] = _b64png(warp)
        if norm is not None and cells is not None:
            out["cells"] = _b64png(_cell_diagnostic(warp, norm, cells, conf, rows))
    if refs is not None:
        out["palette_refs"] = [[round(float(v), 3) for v in r] for r in refs]
    res.debug = out


def _cell_diagnostic(warp, norm, cells, conf, rows) -> np.ndarray:
    """Side by side: measured normalised colour | classified palette colour, with confidence."""
    yoff, ysc = rows if rows else (0, 1)
    W2 = CW * 2 + 10
    canvas = np.full((CH, W2, 3), 40, np.uint8)
    for half in (0, 1):
        ox = half * (CW + 10)
        cv2.rectangle(canvas, (ox, 0), (ox + CW - 1, CH - 1), (0, 0, 0), -1)
        for i in range(ROWS + 1):
            y0 = int(GEOM.separator_y(i))
            cv2.rectangle(canvas, (ox, y0), (ox + CW - 1, y0 + int(GEOM.separator)), (255, 255, 255), -1)
        for i in range(N_CELLS):
            pts = np.array(GEOM.triangle(i), np.float32)
            pts[:, 0] += ox
            if half == 0:
                c = np.clip(norm[i], 0, 1) * 255
                col = (int(c[2]), int(c[1]), int(c[0]))
            else:
                r, g, b = PALETTE_RGB[cells[i]]
                col = (b, g, r)
            cv2.fillConvexPoly(canvas, np.round(pts).astype(np.int32), col)
            if half == 1 and conf is not None and conf[i] < 0.15:
                cx, cy = pts.mean(axis=0)
                cv2.circle(canvas, (int(cx), int(cy)), 6, (0, 0, 255), 2)
    return canvas


def scan_bytes(data: bytes, **kw) -> ScanResult:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return ScanResult(False, reason="could not decode image file (unsupported format?)")
    return scan_image(img, **kw)
