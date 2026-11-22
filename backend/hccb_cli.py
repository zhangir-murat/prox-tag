"""Command-line interface.

  python hccb_cli.py encode --mode mstag --prefix 1 --code 9692 --png out.png --svg out.svg
  python hccb_cli.py decode photo.jpg [--debug-dir dir]
  python hccb_cli.py benchmark --n 20 --out ../docs/benchmark.md
  python hccb_cli.py fixtures ../fixtures
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from pathlib import Path

import cv2

from hccb import benchmark, codec, detect, distort, render


def cmd_encode(a):
    e = codec.encode(a.mode, a.prefix, a.code)
    print(json.dumps({"tag_id": e.tag_id, "cells": e.cells, "payload": e.payload.hex(), "ecc": e.ecc_bytes.hex(),
                      "whitened": e.whitened.hex()}, indent=1))
    if a.png:
        Path(a.png).write_bytes(render.encode_png(render.render_rgb(e.cells, a.width), a.dpi))
    if a.svg:
        Path(a.svg).write_text(render.render_svg(e.cells, width_mm=a.width_mm, title=e.tag_id))


def cmd_decode(a):
    img = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"cannot read {a.image}")
    r = detect.scan_image(img, debug=bool(a.debug_dir))
    d = r.to_dict()
    dbg = d.pop("debug", {})
    if a.debug_dir:
        out = Path(a.debug_dir)
        out.mkdir(parents=True, exist_ok=True)
        for k, v in dbg.items():
            if isinstance(v, str) and v.startswith("data:image/"):
                ext = "png" if "png" in v[:20] else "jpg"
                (out / f"{k}.{ext}").write_bytes(base64.b64decode(v.split(",", 1)[1]))
    print(json.dumps(d, indent=1))
    sys.exit(0 if r.ok else 1)


def cmd_benchmark(a):
    res = benchmark.run(n=a.n, seed=a.seed)
    fp = benchmark.false_positive_trial(a.fp)
    lines = [f"# Benchmark report", "",
             f"Real scanner (`hccb.detect.scan_image`) on synthetically distorted renderings. "
             f"n = {a.n} random IDs per condition and mode, seed {a.seed}, canvas 640 px, tag 50 % of width unless stated. "
             f"Runtime {res['seconds']} s.", "",
             "| condition | MS Tag (RE) | Experimental v1 | wrong IDs | median ms |", "|---|---|---|---|---|"]
    rows = {}
    for r in res["rows"]:
        rows.setdefault(r["condition"], {})[r["mode"]] = r
    for c, m in rows.items():
        a1, b1 = m["mstag"], m["exp1"]
        lines.append(f"| {c} | {a1['success']}/{a1['n']} | {b1['success']}/{b1['n']} | {a1['wrong_id'] + b1['wrong_id']} | "
                     f"{(a1['median_ms'] + b1['median_ms']) / 2:.0f} |")
    lines += ["", f"False-positive trial: **{fp['false_decodes']} decodes in {fp['images']} tag-free images** "
                  f"(random clutter/texture/gradient backgrounds; every 5th contains a random triangle mosaic in a valid frame).", ""]
    text = "\n".join(lines)
    if a.out:
        Path(a.out).write_text(text)
        Path(a.out).with_suffix(".json").write_text(json.dumps({"benchmark": res, "false_positive": fp}, indent=1))
    print(text)


def cmd_fixtures(a):
    out = Path(a.dir)
    (out / "examples").mkdir(parents=True, exist_ok=True)
    (out / "distorted").mkdir(parents=True, exist_ok=True)
    manifest = []
    for mode, p, c in [("mstag", 1, 9692), ("mstag", 0, 0), ("mstag", 65535, 4294967295), ("mstag", 12345, 1234567890),
                       ("exp1", 1, 42), ("exp1", 200, 3000000000)]:
        e = codec.encode(mode, p, c)
        base = f"{mode}_{e.tag_id}"
        (out / "examples" / f"{base}.png").write_bytes(render.encode_png(render.render_rgb(e.cells, 600)))
        (out / "examples" / f"{base}.svg").write_text(render.render_svg(e.cells, title=e.tag_id))
        manifest.append({"file": f"examples/{base}.png", "mode": mode, "prefix": p, "code": c, "expect": "decode"})
    rng = random.Random(77)
    for name, over in [("rot37_persp", {"rotation": 37, "perspective": 0.3}), ("jpeg15", {"jpeg_quality": 15}),
                       ("blur3_noise", {"blur": 3, "noise": 0.05}), ("hue40_desat", {"hue_shift": 40, "saturation": 0.5}),
                       ("clutter_small", {"background": "clutter", "size": 0.2}), ("occl4", {"occlusion": 0.04})]:
        mode = "mstag"
        p, c = rng.randrange(65536), rng.randrange(1 << 32)
        e = codec.encode(mode, p, c)
        img, _ = distort.apply(e.cells, distort.DistortParams.from_dict({"canvas": 640, "seed": 5, **over}))
        fn = f"distorted/{name}_{e.tag_id}.jpg"
        cv2.imwrite(str(out / fn), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        manifest.append({"file": fn, "mode": mode, "prefix": p, "code": c, "expect": "decode", "params": over})
    e = codec.encode("mstag", 1, 1)
    img, _ = distort.apply(e.cells, distort.DistortParams(blur=15))
    cv2.imwrite(str(out / "distorted/unreadable_blur15.jpg"), img)
    manifest.append({"file": "distorted/unreadable_blur15.jpg", "expect": "fail"})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {len(manifest)} fixtures to {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encode")
    e.add_argument("--mode", default="mstag", choices=codec.MODES)
    e.add_argument("--prefix", type=int, default=1)
    e.add_argument("--code", type=int, required=True)
    e.add_argument("--png")
    e.add_argument("--svg")
    e.add_argument("--width", type=int, default=1200)
    e.add_argument("--dpi", type=int)
    e.add_argument("--width-mm", type=float)
    e.set_defaults(f=cmd_encode)
    d = sub.add_parser("decode")
    d.add_argument("image")
    d.add_argument("--debug-dir")
    d.set_defaults(f=cmd_decode)
    b = sub.add_parser("benchmark")
    b.add_argument("--n", type=int, default=20)
    b.add_argument("--seed", type=int, default=1234)
    b.add_argument("--fp", type=int, default=100)
    b.add_argument("--out")
    b.set_defaults(f=cmd_benchmark)
    f = sub.add_parser("fixtures")
    f.add_argument("dir")
    f.set_defaults(f=cmd_fixtures)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
