"""Deterministic image distortions for experiments and benchmarks.

All functions take/return BGR uint8 images. ``apply`` composes them in a
physically motivated order: scene composition (background, placement,
rotation, perspective, occlusion) -> optics (blur) -> sensor/colour
(brightness, contrast, saturation, hue) -> noise -> JPEG.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields

import cv2
import numpy as np

from .render import render_rgb


@dataclass
class DistortParams:
    canvas: int = 800            # output square size, px
    size: float = 0.5            # tag width as a fraction of canvas
    cx: float = 0.5              # tag centre (fraction)
    cy: float = 0.5
    rotation: float = 0.0        # degrees
    perspective: float = 0.0     # 0..0.6 keystone strength
    perspective_dir: float = 0.0 # degrees: which side recedes
    blur: float = 0.0            # gaussian sigma in px
    motion_blur: float = 0.0     # length px
    brightness: float = 0.0      # -1..1 additive
    contrast: float = 1.0        # multiplicative around mid-grey
    saturation: float = 1.0      # 0 = greyscale
    hue_shift: float = 0.0       # degrees
    gamma: float = 1.0
    jpeg_quality: int = 0        # 0 = no JPEG
    noise: float = 0.0           # gaussian sigma (0..1 scale)
    occlusion: float = 0.0       # fraction of tag frame area occluded
    occlusion_x: float = 0.8     # occluder centre within tag (0..1)
    occlusion_y: float = 0.2
    background: str = "plain"    # plain | gradient | texture | clutter
    background_complexity: float = 0.5
    seed: int = 1

    @classmethod
    def from_dict(cls, d: dict) -> "DistortParams":
        names = {f.name: f.type for f in fields(cls)}
        kw = {}
        for k, v in (d or {}).items():
            if k in names and v is not None:
                default = getattr(cls, k)
                kw[k] = type(default)(v) if not isinstance(default, str) else str(v)
        return cls(**kw)

    def to_dict(self) -> dict:
        return asdict(self)


def make_background(n: int, kind: str, complexity: float, rng: np.random.Generator) -> np.ndarray:
    if kind == "plain":
        return np.full((n, n, 3), 235, np.uint8)
    if kind == "gradient":
        y, x = np.mgrid[0:n, 0:n].astype(np.float32) / n
        a = rng.uniform(0, 255, 3)
        b = rng.uniform(0, 255, 3)
        t = (x * 0.6 + y * 0.4)[..., None]
        return (a * (1 - t) + b * t).astype(np.uint8)
    if kind == "texture":
        small = max(2, int(4 + complexity * 60))
        base = rng.uniform(0, 255, (small, small, 3)).astype(np.float32)
        img = cv2.resize(base, (n, n), interpolation=cv2.INTER_CUBIC)
        fine = rng.normal(0, 40 * complexity, (n, n, 3))
        return np.clip(img + fine, 0, 255).astype(np.uint8)
    # clutter: random coloured shapes incl. dark rectangles and triangles (adversarial)
    img = np.full((n, n, 3), rng.integers(120, 255), np.uint8)
    count = int(10 + complexity * 250)
    for _ in range(count):
        col = tuple(int(v) for v in rng.integers(0, 256, 3))
        kind_ = rng.integers(0, 4)
        p = rng.integers(0, n, 2)
        s = int(rng.integers(n // 60 + 2, n // 6 + 3))
        if kind_ == 0:
            cv2.rectangle(img, tuple(int(v) for v in p), (int(p[0] + s), int(p[1] + s * rng.uniform(0.3, 1.5))), col, -1)
        elif kind_ == 1:
            cv2.circle(img, tuple(int(v) for v in p), s // 2, col, -1)
        elif kind_ == 2:
            pts = (p + rng.integers(-s, s, (3, 2))).astype(np.int32)
            cv2.fillConvexPoly(img, pts, col)
        else:
            q = rng.integers(0, n, 2)
            cv2.line(img, tuple(int(v) for v in p), tuple(int(v) for v in q), col, int(rng.integers(1, 6)))
    return img


def place_tag(canvas: np.ndarray, tag_rgb: np.ndarray, p: DistortParams) -> tuple[np.ndarray, np.ndarray]:
    """Warp the tag onto the canvas. Returns (image, 4 destination corners)."""
    n = canvas.shape[0]
    th, tw = tag_rgb.shape[:2]
    W = p.size * n
    H = W * th / tw
    src = np.array([[0, 0], [tw, 0], [tw, th], [0, th]], np.float32)
    # keystone in tag-local coordinates
    k = p.perspective
    local = np.array([[-W / 2, -H / 2], [W / 2, -H / 2], [W / 2, H / 2], [-W / 2, H / 2]], np.float32)
    if k:
        d = np.deg2rad(p.perspective_dir)
        u = np.array([np.cos(d), np.sin(d)], np.float32)
        for i in range(4):
            side = float(np.dot(local[i] / (np.linalg.norm(local[i]) + 1e-6), u))
            # corners on the receding side shrink toward the centre axis
            perp = local[i] - np.dot(local[i], u) * u
            local[i] = local[i] - perp * (k * max(side, 0) * 0.9) - np.dot(local[i], u) * u * (k * 0.35 * max(side, 0))
    th_r = np.deg2rad(p.rotation)
    R = np.array([[np.cos(th_r), -np.sin(th_r)], [np.sin(th_r), np.cos(th_r)]], np.float32)
    dst = (local @ R.T) + np.array([p.cx * n, p.cy * n], np.float32)
    M = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    tag_bgr = cv2.cvtColor(tag_rgb, cv2.COLOR_RGB2BGR)
    warped = cv2.warpPerspective(tag_bgr, M, (n, n), flags=cv2.INTER_AREA if p.size < 0.3 else cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full((th, tw), 255, np.uint8), M, (n, n), flags=cv2.INTER_LINEAR)
    a = (mask.astype(np.float32) / 255.0)[..., None]
    out = (warped.astype(np.float32) * a + canvas.astype(np.float32) * (1 - a)).astype(np.uint8)
    return out, dst


def occlude(tag_rgb: np.ndarray, frac: float, ox: float, oy: float, rng: np.random.Generator) -> np.ndarray:
    if frac <= 0:
        return tag_rgb
    from .geometry import GEOM
    out = tag_rgb.copy()
    h, w = out.shape[:2]
    s = w / GEOM.width
    fw, fh = GEOM.frame_w * s, GEOM.frame_h * s
    area = frac * fw * fh
    side = np.sqrt(area)
    x0 = GEOM.quiet * s + ox * fw - side / 2
    y0 = GEOM.quiet * s + oy * fh - side / 2
    col = tuple(int(v) for v in rng.integers(60, 200, 3))
    cv2.rectangle(out, (int(x0), int(y0)), (int(x0 + side), int(y0 + side)), col, -1)
    return out


def adjust_colour(img: np.ndarray, p: DistortParams) -> np.ndarray:
    f = img.astype(np.float32) / 255.0
    if p.hue_shift or p.saturation != 1.0:
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)  # H in degrees for float
        hsv[..., 0] = (hsv[..., 0] + p.hue_shift) % 360
        hsv[..., 1] = np.clip(hsv[..., 1] * p.saturation, 0, 1)
        f = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    if p.gamma != 1.0:
        f = np.power(np.clip(f, 0, 1), p.gamma)
    f = (f - 0.5) * p.contrast + 0.5 + p.brightness
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


def apply(cells: list[int], p: DistortParams, tag_px: int | None = None) -> tuple[np.ndarray, dict]:
    rng = np.random.default_rng(p.seed)
    n = p.canvas
    bg = make_background(n, p.background, p.background_complexity, rng)
    tag_w = tag_px or max(64, int(p.size * n * 1.5))
    tag = render_rgb(cells, min(tag_w, 1600))
    tag = occlude(tag, p.occlusion, p.occlusion_x, p.occlusion_y, rng)
    img, corners = place_tag(bg, tag, p)
    if p.blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), p.blur)
    if p.motion_blur >= 2:
        L = int(p.motion_blur)
        k = np.zeros((L, L), np.float32)
        k[L // 2, :] = 1.0 / L
        img = cv2.filter2D(img, -1, k)
    img = adjust_colour(img, p)
    if p.noise > 0:
        img = np.clip(img.astype(np.float32) + rng.normal(0, p.noise * 255, img.shape), 0, 255).astype(np.uint8)
    if p.jpeg_quality and p.jpeg_quality < 100:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(p.jpeg_quality)])
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img, {"corners": corners.round(1).tolist()}
