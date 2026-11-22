"""Milestone 1/2: image-level round trips through the real OpenCV scanner."""
import random

import cv2
import numpy as np
import pytest

from hccb import benchmark, codec, detect, distort, render


def _bgr(cells, w=500):
    return cv2.cvtColor(render.render_rgb(cells, w), cv2.COLOR_RGB2BGR)


def _check(img, e):
    r = detect.scan_image(img, debug=False)
    return r.ok and (r.mode, r.prefix, r.code) == (e.mode, e.prefix, e.code), r


@pytest.mark.parametrize("mode", ["mstag", "exp1"])
def test_100_random_clean_png_roundtrips(mode):
    rng = random.Random(100 if mode == "mstag" else 200)
    fails = []
    for i in range(100):
        e = codec.encode(mode, rng.randrange(256), rng.randrange(1 << 32))
        png = render.encode_png(render.render_rgb(e.cells, rng.choice([180, 320, 640])))
        r = detect.scan_bytes(png, debug=False)
        if not (r.ok and r.code == e.code and r.prefix == e.prefix):
            fails.append((e.tag_id, r.reason))
    assert not fails


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_right_angle_rotations(k):
    rng = random.Random(k)
    for _ in range(10):
        e = codec.encode("mstag", rng.randrange(65536), rng.randrange(1 << 32))
        ok, r = _check(np.ascontiguousarray(np.rot90(_bgr(e.cells), k)), e)
        assert ok, r.reason
        assert r.orientation["rotation_deg"] in (0, 90, 180, 270)


def test_mirrored_image_decodes():
    e = codec.encode("exp1", 9, 99)
    ok, r = _check(cv2.flip(_bgr(e.cells), 1), e)
    assert ok and r.orientation["mirrored"]


CONDS = {
    "scale_small": {"size": 0.15},
    "scale_large": {"size": 0.85},
    "jpeg_q20": {"jpeg_quality": 20},
    "rotation_33": {"rotation": 33},
    "perspective": {"perspective": 0.35, "perspective_dir": 45},
    "hue_shift_30": {"hue_shift": 30},
    "desaturate": {"saturation": 0.45},
    "dark": {"brightness": -0.3},
    "low_contrast": {"contrast": 0.45},
    "gamma_cast": {"gamma": 1.7},
    "blur": {"blur": 2.5},
    "noise": {"noise": 0.08},
    "clutter_bg": {"background": "clutter", "background_complexity": 0.7},
}


@pytest.mark.parametrize("name", list(CONDS))
def test_distortion_conditions(name):
    rng = random.Random(hash(name) & 0xFFFF)
    ok = 0
    for i in range(6):
        mode = ("mstag", "exp1")[i % 2]
        e = codec.encode(mode, rng.randrange(256), rng.randrange(1 << 32))
        img, _ = distort.apply(e.cells, distort.DistortParams.from_dict({"canvas": 640, "seed": i, **CONDS[name]}))
        ok += _check(img, e)[0]
    assert ok == 6


def test_unreadable_image_fails_with_reason():
    e = codec.encode("mstag", 1, 5)
    img, _ = distort.apply(e.cells, distort.DistortParams(blur=14))
    r = detect.scan_image(img, debug=True)
    assert not r.ok and r.reason
    assert "detection" in r.debug


def test_scanner_rejects_random_colourful_images():
    res = benchmark.false_positive_trial(n=30, seed=7)
    assert res["false_decodes"] == 0


def test_random_triangle_mosaic_in_valid_frame_rejected():
    rng = random.Random(3)
    for _ in range(25):
        cells = [rng.randrange(4) for _ in range(44)] + [0, 1, 0, 1, 2, 3]
        r = detect.scan_image(_bgr(cells), debug=False)
        assert not r.ok


def test_debug_outputs_present():
    e = codec.encode("mstag", 1, 77)
    r = detect.scan_image(_bgr(e.cells), debug=True)
    assert r.ok
    for k in ("detection", "warped", "cells", "mask"):
        assert r.debug[k].startswith("data:image/")


def test_garbage_bytes():
    r = detect.scan_bytes(b"not an image")
    assert not r.ok


def test_regression_wrong_orientation_erasure_misdecode():
    """Benchmark once produced a WRONG ID: a mirrored/rotated mis-orientation plus 6 erasures
    (= all exp1 parity) 'decoded' garbage. Fixed by the assisted-decoding budget and the
    calibration darkness check."""
    from conftest import FIXTURES
    img = cv2.imread(str(FIXTURES / "regression" / "exp1_blur2_misdecode_X239_2363493425.png"))
    r = detect.scan_image(img, debug=False)
    assert r.ok and r.tag_id == "X239_2363493425"


def test_assisted_decoding_never_accepts_random_cells():
    rng = random.Random(11)
    hits = 0
    for _ in range(4000):
        filler = rng.choice([[0, 1], [3, 2]])
        cells = [rng.randrange(4) for _ in range(44)] + filler + [0, 1, 2, 3]
        er = rng.sample(range(44), rng.randrange(1, 5))
        hits += codec.decode_cells(cells, erasure_cells=er).ok
        hits += codec.decode_cells(cells, assisted=True).ok
    assert hits == 0


def test_adversarial_mosaics_with_valid_trailer_never_decode():
    rng = random.Random(21)
    claims = []
    for i in range(300):
        cells = [rng.randrange(4) for _ in range(44)] + rng.choice([[0, 1], [3, 2]]) + [0, 1, 2, 3]
        img, _ = distort.apply(cells, distort.DistortParams(canvas=400, rotation=rng.uniform(0, 360), blur=rng.choice([0, 1, 2]), seed=i))
        r = detect.scan_image(img, debug=False)
        if r.ok:
            claims.append(r.tag_id)
    assert claims == []
