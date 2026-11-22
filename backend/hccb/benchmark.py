"""Batch benchmark: run the REAL scanner over distorted renderings."""
from __future__ import annotations

import random
import time

import numpy as np

from . import codec
from .detect import scan_image
from .distort import DistortParams, apply, make_background

# name -> dict of DistortParams overrides
CONDITIONS: dict[str, dict] = {
    "clean": {},
    "rot 0°": {"rotation": 0},
    "rot 90°": {"rotation": 90},
    "rot 180°": {"rotation": 180},
    "rot 270°": {"rotation": 270},
    "rot 23°": {"rotation": 23},
    "small (12% of frame)": {"size": 0.12},
    "large (90% of frame)": {"size": 0.9},
    "perspective 0.25": {"perspective": 0.25, "perspective_dir": 30},
    "perspective 0.45": {"perspective": 0.45, "perspective_dir": 120},
    "blur σ=2": {"blur": 2.0},
    "blur σ=4": {"blur": 4.0},
    "motion blur 12px": {"motion_blur": 12},
    "dark (-0.35)": {"brightness": -0.35},
    "bright (+0.3)": {"brightness": 0.3},
    "low contrast 0.5": {"contrast": 0.5},
    "desaturated 0.4": {"saturation": 0.4},
    "hue +25°": {"hue_shift": 25},
    "hue +60°": {"hue_shift": 60},
    "warm cast (γ 1.6)": {"gamma": 1.6},
    "JPEG q=30": {"jpeg_quality": 30},
    "JPEG q=10": {"jpeg_quality": 10},
    "noise σ=0.06": {"noise": 0.06},
    "noise σ=0.15": {"noise": 0.15},
    "occlusion 3%": {"occlusion": 0.03, "occlusion_x": 0.5, "occlusion_y": 0.45},
    "occlusion 8%": {"occlusion": 0.08, "occlusion_x": 0.3, "occlusion_y": 0.5},
    "clutter background": {"background": "clutter", "background_complexity": 0.6},
    "texture background": {"background": "texture", "background_complexity": 0.8},
    "tiny (6% of frame)": {"size": 0.06},
    "perspective 0.65": {"perspective": 0.65, "perspective_dir": 200},
    "blur σ=7": {"blur": 7.0},
    "contrast 0.2": {"contrast": 0.2},
    "hue +120°": {"hue_shift": 120},
    "greyscale (sat 0.05)": {"saturation": 0.05},
    "JPEG q=5": {"jpeg_quality": 5},
    "noise σ=0.3": {"noise": 0.3},
    "occlusion 12%": {"occlusion": 0.12, "occlusion_x": 0.5, "occlusion_y": 0.5},
    "occlusion 20%": {"occlusion": 0.2, "occlusion_x": 0.7, "occlusion_y": 0.3},
    "combined (rot+persp+blur+jpeg)": {"rotation": 37, "perspective": 0.25, "blur": 1.5, "jpeg_quality": 45, "noise": 0.03},
}


def run(conditions: list[str] | None = None, n: int = 20, modes=("mstag", "exp1"), seed: int = 1234,
        base: dict | None = None, canvas: int = 640) -> dict:
    rng = random.Random(seed)
    names = conditions or list(CONDITIONS)
    rows = []
    t0 = time.perf_counter()
    for name in names:
        over = CONDITIONS.get(name, {})
        for mode in modes:
            ok = wrong = 0
            times = []
            reasons: dict[str, int] = {}
            for i in range(n):
                prefix = rng.randrange(256)
                code = rng.randrange(1 << 32)
                enc = codec.encode(mode, prefix, code)
                params = {"canvas": canvas, "size": 0.5, "seed": rng.randrange(1 << 30)}
                params.update(base or {})
                params.update(over)
                img, _ = apply(enc.cells, DistortParams.from_dict(params))
                r = scan_image(img, debug=False)
                times.append(r.elapsed_ms)
                if r.ok and r.mode == mode and r.prefix == prefix and r.code == code:
                    ok += 1
                elif r.ok:
                    wrong += 1
                else:
                    key = r.reason.split(" Best attempt")[0][:80]
                    reasons[key] = reasons.get(key, 0) + 1
            rows.append({
                "condition": name, "mode": mode, "n": n, "success": ok, "wrong_id": wrong,
                "rate": ok / n, "median_ms": float(np.median(times)),
                "failure_reasons": reasons,
            })
    return {"rows": rows, "seconds": round(time.perf_counter() - t0, 2), "seed": seed, "n_per_condition": n}


def false_positive_trial(n: int = 50, seed: int = 99, canvas: int = 640) -> dict:
    """Scan random colourful images with NO tag; count any claimed decode."""
    rng = np.random.default_rng(seed)
    claims = []
    for i in range(n):
        kind = ["clutter", "texture", "gradient"][i % 3]
        img = make_background(canvas, kind, float(rng.uniform(0.3, 1.0)), rng)
        # also add random triangle mosaics in black frames: an adversarial near-miss
        if i % 5 == 4:
            from .render import render_rgb
            import cv2
            cells = [int(x) for x in rng.integers(0, 4, 50)]
            t = render_rgb(cells, 300)
            y, x = 100, 100
            img[y:y + t.shape[0], x:x + t.shape[1]] = cv2.cvtColor(t, cv2.COLOR_RGB2BGR)
        r = scan_image(img, debug=False)
        if r.ok:
            claims.append({"index": i, "tag_id": r.tag_id})
    return {"images": n, "false_decodes": len(claims), "claims": claims}
