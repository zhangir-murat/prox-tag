"""Milestone 1: symbol-level codec correctness."""
import json
import random

import pytest
from conftest import FIXTURES

from hccb import codec
from hccb.rs import GaloisField, ReedSolomon


def test_crc16_x25_check_value():
    assert codec.crc16_x25(b"123456789") == 0x906E


def test_gf32_generator_matches_published_values():
    assert codec.MSTAG_RS.generator == [17, 9, 6, 30, 1]


@pytest.mark.parametrize("m,prim,nsym,fcr,n", [(5, 0x25, 4, 1, 17), (8, 0x11D, 6, 0, 11), (8, 0x11D, 10, 0, 40)])
def test_rs_errors_and_erasures(m, prim, nsym, fcr, n):
    rs = ReedSolomon(GaloisField(m, prim), nsym, fcr)
    rng = random.Random(m * 100 + nsym)
    for _ in range(400):
        msg = [rng.randrange(1 << m) for _ in range(n - nsym)]
        cw = rs.encode(msg)
        assert not any(rs.syndromes(cw))
        ne = rng.randrange(0, nsym // 2 + 1)
        ns = rng.randrange(0, nsym - 2 * ne + 1)
        pos = rng.sample(range(n), ne + ns)
        bad = list(cw)
        for p in pos:
            bad[p] ^= rng.randrange(1, 1 << m)
        res = rs.decode(bad, erasures=pos[ne:])
        assert res.ok and res.codeword == cw


def test_mstag_matches_unhccb_reference_vectors():
    data = json.loads((FIXTURES / "unhccb_golden_vectors.json").read_text())
    assert len(data["vectors"]) == 50
    for v in data["vectors"]:
        assert codec.mstag_encode(v["prefix"], v["code"]).cells == v["cells"], v


@pytest.mark.parametrize("mode,pmax", [("mstag", 0xFFFF), ("exp1", 0xFF)])
def test_100_random_ids_roundtrip_at_cell_level(mode, pmax):
    rng = random.Random(42)
    for _ in range(100):
        p, c = rng.randrange(pmax + 1), rng.randrange(1 << 32)
        e = codec.encode(mode, p, c)
        assert len(e.cells) == 50 and set(e.cells) <= {0, 1, 2, 3}
        assert e.cells[46:] == [0, 1, 2, 3]
        d = codec.decode_cells(e.cells)
        assert d.ok and (d.mode, d.prefix, d.code) == (mode, p, c)


def test_distinct_ids_give_distinct_symbols_and_determinism():
    seen = {}
    for code in range(2000):
        cells = tuple(codec.encode("mstag", 1, code).cells)
        assert cells not in seen
        seen[cells] = code
        assert list(cells) == codec.encode("mstag", 1, code).cells


@pytest.mark.parametrize("mode", ["mstag", "exp1"])
def test_single_cell_error_always_corrected(mode):
    e = codec.encode(mode, 7, 0xDEADBEEF)
    for pos in range(44):
        for delta in (1, 2, 3):
            cells = list(e.cells)
            cells[pos] = (cells[pos] + delta) % 4
            d = codec.decode_cells(cells)
            assert d.ok and d.code == 0xDEADBEEF, (pos, delta)
            # mstag cells 8-9 hold the 4 zero-padding bits after the 20 parity bits: not RS-protected,
            # so an error there is harmless and only visible as a non-zero pad warning.
            assert len(d.corrected_symbols) >= 1 or (mode == "mstag" and pos in (8, 9) and d.details["parity_pad_bits"])


def test_exp1_corrects_three_cell_errors():
    rng = random.Random(5)
    for _ in range(200):
        e = codec.encode("exp1", rng.randrange(256), rng.randrange(1 << 32))
        cells = list(e.cells)
        for pos in rng.sample(range(44), 3):
            cells[pos] = (cells[pos] + rng.randrange(1, 4)) % 4
        d = codec.decode_cells(cells)
        assert d.ok and d.code == e.code


@pytest.mark.parametrize("mode", ["mstag", "exp1"])
def test_heavy_corruption_is_rejected_not_misdecoded(mode):
    """Corruption beyond capability must fail (or, astronomically rarely, decode wrongly). Count both."""
    rng = random.Random(9)
    wrong = rejected = 0
    for _ in range(500):
        e = codec.encode(mode, 3, rng.randrange(1 << 32))
        cells = list(e.cells)
        for pos in rng.sample(range(44), 12):
            cells[pos] = (cells[pos] + rng.randrange(1, 4)) % 4
        d = codec.decode_cells(cells)
        if not d.ok:
            rejected += 1
        elif d.code != e.code:
            wrong += 1
    assert wrong == 0
    assert rejected >= 495


def test_erasures_extend_mstag_capability():
    e = codec.encode("mstag", 1, 424242)
    cells = list(e.cells)
    # 2 erased cells within distinct symbols + still decodes thanks to erasure info
    for pos in (0, 20):
        cells[pos] = (cells[pos] + 1) % 4
    d = codec.decode_cells(cells, erasure_cells=[0, 20])
    assert d.ok and d.code == 424242


def test_random_cells_never_validate():
    rng = random.Random(1)
    hits = 0
    for _ in range(50000):
        cells = [rng.randrange(4) for _ in range(44)] + rng.choice([[0, 1], [3, 2]]) + [0, 1, 2, 3]
        hits += codec.decode_cells(cells).ok
    assert hits == 0


def test_trailer_and_filler_checks():
    e = codec.encode("mstag", 1, 1)
    bad = list(e.cells)
    bad[47] = 0
    assert not codec.decode_cells(bad).ok
    bad = list(e.cells)
    bad[44:46] = [2, 2]
    assert not codec.decode_cells(bad).ok


@pytest.mark.parametrize("mode,prefix,code", [("mstag", -1, 1), ("mstag", 70000, 1), ("mstag", 1, 1 << 32),
                                              ("exp1", 256, 1), ("nope", 1, 1)])
def test_out_of_range_inputs(mode, prefix, code):
    with pytest.raises(ValueError):
        codec.encode(mode, prefix, code)


def test_modes_never_cross_decode():
    for code in range(300):
        d = codec.decode_cells(codec.encode("exp1", 1, code).cells, modes=("mstag",))
        assert not d.ok
        d = codec.decode_cells(codec.encode("mstag", 1, code).cells, modes=("exp1",))
        assert not d.ok
