"""Committed image fixtures + optional historical Microsoft Tag images."""
import json

import cv2
import pytest
from conftest import FIXTURES

from hccb import detect

MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
HIST = FIXTURES / "historical"
HIST_FILES = sorted(p for p in HIST.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))


@pytest.mark.parametrize("item", MANIFEST, ids=[m["file"] for m in MANIFEST])
def test_committed_fixtures(item):
    img = cv2.imread(str(FIXTURES / item["file"]))
    r = detect.scan_image(img, debug=False)
    if item["expect"] == "fail":
        assert not r.ok
    else:
        assert r.ok, r.reason
        assert (r.mode, r.prefix, r.code) == (item["mode"], item["prefix"], item["code"])


@pytest.mark.skipif(not HIST_FILES, reason="no historical Microsoft Tag images in fixtures/historical/ (see README there)")
@pytest.mark.parametrize("path", HIST_FILES, ids=[p.name for p in HIST_FILES])
def test_historical_microsoft_tag(path):
    meta = {}
    if (HIST / "sources.json").exists():
        meta = json.loads((HIST / "sources.json").read_text()).get(path.name, {})
    r = detect.scan_image(cv2.imread(str(path)), debug=False, modes=("mstag",))
    assert r.ok, f"{path.name}: {r.reason}"
    if meta.get("expected_tag_id"):
        assert r.tag_id == meta["expected_tag_id"]
