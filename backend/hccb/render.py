"""Rendering of 50-cell symbols to SVG (vector) and raster (numpy / PNG)."""
from __future__ import annotations

import cv2
import numpy as np

from .codec import PALETTE_HEX, PALETTE_RGB, N_CELLS
from .geometry import GEOM, Geometry, ROWS


def render_svg(cells: list[int], width_mm: float | None = None, geom: Geometry = GEOM,
               quiet_zone: bool = True, title: str | None = None) -> str:
    if len(cells) != N_CELLS:
        raise ValueError("need 50 cells")
    q = geom.quiet if quiet_zone else 0.0
    W = geom.frame_w + 2 * q
    H = geom.frame_h + 2 * q
    if width_mm:
        size = f'width="{width_mm:.2f}mm" height="{width_mm * H / W:.2f}mm"'
    else:
        size = f'width="{W:.0f}" height="{H:.0f}"'
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.3f} {H:.3f}" {size} shape-rendering="geometricPrecision">',
    ]
    if title:
        out.append(f"<title>{title}</title>")
    out.append(f'<rect width="{W:.3f}" height="{H:.3f}" fill="#FFFFFF"/>')
    out.append(f'<g transform="translate({q:.3f},{q:.3f})">')
    out.append(f'<rect width="{geom.frame_w:.3f}" height="{geom.frame_h:.3f}" fill="#000000"/>')
    for i in range(ROWS + 1):
        out.append(f'<rect x="0" y="{geom.separator_y(i):.3f}" width="{geom.frame_w:.3f}" height="{geom.separator:.3f}" fill="#FFFFFF"/>')
    for idx, s in enumerate(cells):
        pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in geom.triangle(idx))
        out.append(f'<polygon data-cell="{idx}" data-symbol="{s}" points="{pts}" fill="{PALETTE_HEX[s]}"/>')
    out.append("</g></svg>")
    return "\n".join(out)


def render_rgb(cells: list[int], width_px: int = 600, geom: Geometry = GEOM,
               quiet_zone: bool = True, palette: dict[int, tuple[int, int, int]] | None = None) -> np.ndarray:
    """Return an RGB uint8 image of the symbol, ``width_px`` wide (incl. quiet zone)."""
    if len(cells) != N_CELLS:
        raise ValueError("need 50 cells")
    pal = palette or PALETTE_RGB
    q = geom.quiet if quiet_zone else 0.0
    W = geom.frame_w + 2 * q
    H = geom.frame_h + 2 * q
    s = width_px / W
    h_px = int(round(H * s))
    SS = 4  # supersampling for clean anti-aliased edges
    shift = 4
    k = s * (1 << shift)
    img = np.full((h_px, width_px, 3), 255, np.uint8)
    img = cv2.resize(img, (width_px * SS, h_px * SS), interpolation=cv2.INTER_NEAREST)
    ks = k * SS

    def P(x, y):
        return [int(round((x + q) * ks)), int(round((y + q) * ks))]

    cv2.fillPoly(img, [np.array([P(0, 0), P(geom.frame_w, 0), P(geom.frame_w, geom.frame_h), P(0, geom.frame_h)])], (0, 0, 0), shift=shift)
    for i in range(ROWS + 1):
        y0 = geom.separator_y(i)
        y1 = y0 + geom.separator
        cv2.fillPoly(img, [np.array([P(0, y0), P(geom.frame_w, y0), P(geom.frame_w, y1), P(0, y1)])], (255, 255, 255), shift=shift)
    for idx, c in enumerate(cells):
        pts = np.array([P(x, y) for x, y in geom.triangle(idx)])
        cv2.fillPoly(img, [pts], tuple(int(v) for v in pal[c]), shift=shift)
    return cv2.resize(img, (width_px, h_px), interpolation=cv2.INTER_AREA)


def encode_png(rgb: np.ndarray, dpi: int | None = None) -> bytes:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("PNG encoding failed")
    data = buf.tobytes()
    if dpi:
        data = _set_png_dpi(data, dpi)
    return data


def _set_png_dpi(png: bytes, dpi: int) -> bytes:
    import struct
    import zlib
    ppm = int(round(dpi / 0.0254))
    chunk = b"pHYs" + struct.pack(">IIB", ppm, ppm, 1)
    phys = struct.pack(">I", 9) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
    # insert after IHDR (8-byte sig + 25-byte IHDR chunk)
    return png[:33] + phys + png[33:]
