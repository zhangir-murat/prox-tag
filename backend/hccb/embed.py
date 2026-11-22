"""Place a tag inside a photograph / artwork with blending controls."""
from __future__ import annotations

from dataclasses import dataclass, fields

import cv2
import numpy as np

from .geometry import GEOM
from .render import render_rgb

BLEND_MODES = ("normal", "multiply", "screen", "overlay", "soft-light", "luminosity", "color")


@dataclass
class EmbedParams:
    cx: float = 0.5           # centre, fraction of image width
    cy: float = 0.5           # centre, fraction of image height
    scale: float = 0.3        # tag width as fraction of image width
    rotation: float = 0.0
    opacity: float = 1.0      # 0..1
    blend: str = "normal"
    quiet_zone: bool = True   # include white margin around the black frame
    frame_opacity: float = 1.0  # separate opacity for the black frame/separators

    @classmethod
    def from_dict(cls, d: dict) -> "EmbedParams":
        kw = {}
        for f in fields(cls):
            if f.name in (d or {}) and d[f.name] is not None:
                default = getattr(cls, f.name)
                v = d[f.name]
                if isinstance(default, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
                else:
                    v = type(default)(v)
                kw[f.name] = v
        p = cls(**kw)
        if p.blend not in BLEND_MODES:
            raise ValueError(f"blend must be one of {BLEND_MODES}")
        return p


def _blend(base: np.ndarray, top: np.ndarray, mode: str) -> np.ndarray:
    """base/top float32 RGB in [0,1]."""
    if mode == "normal":
        return top
    if mode == "multiply":
        return base * top
    if mode == "screen":
        return 1 - (1 - base) * (1 - top)
    if mode == "overlay":
        return np.where(base < 0.5, 2 * base * top, 1 - 2 * (1 - base) * (1 - top))
    if mode == "soft-light":
        return (1 - 2 * top) * base * base + 2 * top * base
    if mode in ("luminosity", "color"):
        bl = cv2.cvtColor(base.astype(np.float32), cv2.COLOR_RGB2Lab)
        tl = cv2.cvtColor(top.astype(np.float32), cv2.COLOR_RGB2Lab)
        out = bl.copy()
        if mode == "luminosity":
            out[..., 0] = tl[..., 0]
        else:
            out[..., 1:] = tl[..., 1:]
        return np.clip(cv2.cvtColor(out, cv2.COLOR_Lab2RGB), 0, 1)
    raise ValueError(mode)


def embed(art_bgr: np.ndarray, cells: list[int], p: EmbedParams) -> tuple[np.ndarray, list]:
    H, W = art_bgr.shape[:2]
    tw = max(40, int(p.scale * W))
    tag = render_rgb(cells, tw, quiet_zone=True)
    th = tag.shape[0]
    # alpha: quiet zone optional; frame/separators may have their own opacity
    s = tw / GEOM.width
    q = int(round(GEOM.quiet * s))
    alpha = np.full((th, tw), p.opacity, np.float32)
    if not p.quiet_zone:
        alpha[:q, :] = 0
        alpha[-q:, :] = 0
        alpha[:, :q] = 0
        alpha[:, -q:] = 0
    if p.frame_opacity != 1.0:
        cellmask = np.zeros((th, tw), np.uint8)
        for i in range(50):
            pts = np.array(GEOM.triangle(i)) * s + q
            cv2.fillConvexPoly(cellmask, np.round(pts).astype(np.int32), 1)
        inner = np.zeros((th, tw), np.uint8)
        inner[q:th - q, q:tw - q] = 1
        frame = (inner == 1) & (cellmask == 0)
        alpha[frame] *= p.frame_opacity
    # rotate tag + alpha around its centre and place
    cx, cy = p.cx * W, p.cy * H
    M = cv2.getRotationMatrix2D((tw / 2, th / 2), -p.rotation, 1.0)
    M[0, 2] += cx - tw / 2
    M[1, 2] += cy - th / 2
    tag_w = cv2.warpAffine(tag.astype(np.float32) / 255.0, M, (W, H), flags=cv2.INTER_LINEAR)
    a_w = cv2.warpAffine(alpha, M, (W, H), flags=cv2.INTER_LINEAR)[..., None]
    base = cv2.cvtColor(art_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    blended = _blend(base, tag_w, p.blend)
    out = base * (1 - a_w) + blended * a_w
    corners = cv2.transform(np.array([[[0, 0], [tw, 0], [tw, th], [0, th]]], np.float32), M)[0].round(1).tolist()
    return cv2.cvtColor((np.clip(out, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR), corners
