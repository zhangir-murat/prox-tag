"""Milestone 3: resolver + HTTP API."""
import io
import os
import tempfile

import pytest

os.environ["HCCB_DB"] = os.path.join(tempfile.mkdtemp(), "t.sqlite3")

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402
from hccb import codec, render  # noqa: E402
from hccb.resolver import Resolver, ResolverError  # noqa: E402

client = TestClient(server.app)


def test_resolver_lifecycle():
    r = Resolver(":memory:")
    t = r.create("mstag", "https://example.org/a", prefix=1, code=1000)
    assert r.resolve("mstag", 1, 1000)["url"] == "https://example.org/a"
    r.update(t["id"], url="https://example.org/b")
    assert r.resolve("mstag", 1, 1000)["url"] == "https://example.org/b"
    r.update(t["id"], enabled=False)
    assert r.resolve("mstag", 1, 1000)["outcome"] == "disabled"
    r.update(t["id"], enabled=True)
    assert r.resolve("mstag", 1, 999)["outcome"] == "unassigned"
    assert len(r.scans(t["id"])) == 3
    assert r.stats()["total_scans"] == 4
    r.delete(t["id"])
    assert r.resolve("mstag", 1, 1000)["outcome"] == "unassigned"


def test_duplicate_and_invalid():
    r = Resolver(":memory:")
    r.create("exp1", "https://x.test", prefix=2, code=5)
    with pytest.raises(ResolverError):
        r.create("exp1", "https://x.test", prefix=2, code=5)
    r.create("mstag", "https://x.test", prefix=2, code=5)  # same numbers, other mode: separate namespace
    with pytest.raises(ResolverError):
        r.create("mstag", "javascript:alert(1)")
    with pytest.raises(ResolverError):
        r.create("exp1", None, prefix=300)
    auto = {r.create("mstag", None)["code"] for _ in range(50)}
    assert len(auto) == 50


def test_end_to_end_url_to_scan_to_url():
    t = client.post("/api/tags", json={"url": "https://example.com/start", "mode": "mstag", "prefix": 3}).json()
    png = client.get(f"/api/symbol/mstag/3/{t['code']}.png?width=500").content
    s = client.post("/api/scan", files={"file": ("t.png", io.BytesIO(png), "image/png")}, data={"source": "test"}).json()
    assert s["ok"] and s["code"] == t["code"]
    assert s["resolution"]["url"] == "https://example.com/start"
    # edit destination without changing the symbol
    client.patch(f"/api/tags/{t['id']}", json={"url": "https://example.com/changed"})
    png2 = client.get(f"/api/symbol/mstag/3/{t['code']}.png?width=500").content
    assert png2 == png
    s2 = client.post("/api/scan", files={"file": ("t.png", io.BytesIO(png2), "image/png")}).json()
    assert s2["resolution"]["url"] == "https://example.com/changed"
    assert len(client.get(f"/api/tags/{t['id']}/scans").json()) == 2
    # redirect endpoint
    r = client.get(f"/r/mstag/3/{t['code']}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://example.com/changed"
    client.patch(f"/api/tags/{t['id']}", json={"enabled": False})
    assert client.get(f"/r/mstag/3/{t['code']}", follow_redirects=False).status_code == 410
    assert client.delete(f"/api/tags/{t['id']}").status_code == 200
    assert client.delete(f"/api/tags/{t['id']}").status_code == 404


def test_unassigned_decoded_id():
    e = codec.encode("mstag", 1, 9692)
    png = render.encode_png(render.render_rgb(e.cells, 400))
    s = client.post("/api/scan", files={"file": ("t.png", io.BytesIO(png), "image/png")}).json()
    assert s["ok"] and s["resolution"]["outcome"] == "unassigned"


def test_svg_export_and_print_sizes():
    svg = client.get("/api/symbol/exp1/1/2.svg?width_mm=25").text
    assert 'width="25.00mm"' in svg and svg.count("<polygon") == 50
    png = client.get("/api/symbol/mstag/1/2.png?width_mm=20&dpi=600").content
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[1] == round(20 / 25.4 * 600)
    assert b"pHYs" in png[:100]


def test_experiment_and_embed_endpoints():
    r = client.post("/api/experiment", json={"mode": "exp1", "prefix": 4, "code": 44,
                                             "params": {"rotation": 20, "jpeg_quality": 40}}).json()
    assert r["recovered"] and r["modified_image"].startswith("data:image/jpeg")
    import cv2
    import numpy as np
    art = np.full((600, 800, 3), (40, 120, 200), np.uint8)
    ok, buf = cv2.imencode(".jpg", art)
    res = client.post("/api/embed", files={"file": ("a.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
                      data={"mode": "mstag", "prefix": "1", "code": "5", "params": '{"opacity": 1.0, "scale": 0.4}',
                            "sweep": "opacity:0.2,1.0"}).json()
    assert res["recovered"]
    assert [x["recovered"] for x in res["sweep"]["results"]][-1] is True


def test_bad_inputs():
    assert client.post("/api/encode", json={"mode": "mstag", "prefix": 1, "code": -5}).status_code == 400
    assert client.post("/api/scan", files={"file": ("x.png", io.BytesIO(b"zz"), "image/png")}).status_code == 400
    assert client.post("/api/tags", json={"url": "ftp://x", "mode": "mstag"}).status_code == 400
