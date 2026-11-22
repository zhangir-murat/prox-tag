"""Symbol geometry (5 rows x 10 triangles).

Layout follows the UN_HCCB renderer and the published Microsoft Research HCCB
samples: rows of alternating down/up triangles separated by white horizontal
bars, inside a black frame whose bottom bar is thicker than the top bar (the
orientation cue), surrounded by a white quiet zone. Exact historical proportions
are NOT confirmed; the values below are UN_HCCB's.

All coordinates are in abstract "units" relative to the top-left of the WHITE
quiet zone. ``frame_*`` describe the black rectangle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

ROWS, COLS = 5, 10


@dataclass(frozen=True)
class Geometry:
    tri_h: float = 60.0
    separator: float = 11.0
    quiet: float = 26.0
    black_side: float = 24.0
    black_top: float = 18.0
    black_bottom: float = 34.0

    @property
    def base(self) -> float:
        return 2 * self.tri_h / math.sqrt(3)

    @property
    def dx(self) -> float:
        return self.base / 2

    @property
    def lattice_w(self) -> float:
        return self.base + (COLS - 1) * self.dx

    @property
    def frame_w(self) -> float:
        return 2 * self.black_side + self.lattice_w

    @property
    def frame_h(self) -> float:
        return self.black_top + self.black_bottom + ROWS * self.tri_h + (ROWS + 1) * self.separator

    @property
    def width(self) -> float:
        return self.frame_w + 2 * self.quiet

    @property
    def height(self) -> float:
        return self.frame_h + 2 * self.quiet

    def separator_y(self, i: int) -> float:
        """Top y of white separator bar i (0..5), frame-relative."""
        return self.black_top + i * (self.separator + self.tri_h)

    def triangle(self, idx: int) -> list[tuple[float, float]]:
        """Triangle vertices for cell idx in FRAME-relative units."""
        row, col = divmod(idx, COLS)
        top = self.separator_y(row) + self.separator
        bottom = top + self.tri_h
        x = self.black_side + col * self.dx
        if col % 2 == 0:  # pointing down
            return [(x, top), (x + self.base, top), (x + self.base / 2, bottom)]
        return [(x, bottom), (x + self.base, bottom), (x + self.base / 2, top)]

    def centroid(self, idx: int) -> tuple[float, float]:
        pts = self.triangle(idx)
        return (sum(p[0] for p in pts) / 3, sum(p[1] for p in pts) / 3)


GEOM = Geometry()
