"""Symbol-level codecs: identifier <-> 50 colour cells.

Two modes are implemented and are NEVER substituted for one another silently:

``mstag`` – "MS Tag (reverse-engineered)" mode.
    A clean-room re-implementation of the 5x10 Microsoft Tag codec *as described
    by the third-party UN_HCCB project* (github.com/yannickfan67-ai/UN_HCCB, MIT).
    Bit layout, whitening table, CRC and RS parameters come from that project's
    claims of having reverse-engineered Microsoft Tag Reader 5.6.4. We verified
    that the RS parity is a standard RS(17,13) code over GF(32) and that our
    independent implementation reproduces UN_HCCB bit-for-bit, but we have NOT
    validated it against independently sourced original Microsoft Tag images.
    Compatibility with real Microsoft Tags is therefore UNVERIFIED.

``exp1`` – "Experimental Tag Mode v1" (HCCB Lab's own documented scheme).
    Same geometry, palette and calibration cells; a byte-aligned RS(11,5) code
    over GF(256) so that every colour cell maps into exactly one RS symbol.
    Not compatible with Microsoft Tag readers by design.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .rs import GaloisField, ReedSolomon

N_CELLS = 50
N_DATA_CELLS = 44
CALIBRATION = [0, 1, 2, 3]
CAL_POS = list(range(46, 50))
FILLER_POS = [44, 45]

# Palette index convention (UN_HCCB / Microsoft print palette claim).
PALETTE_RGB = {
    0: (255, 255, 0),    # yellow
    1: (255, 0, 255),    # magenta
    2: (0, 0, 0),        # black
    3: (0, 255, 255),    # cyan
}
PALETTE_NAMES = {0: "yellow", 1: "magenta", 2: "black", 3: "cyan"}
PALETTE_HEX = {k: "#%02X%02X%02X" % v for k, v in PALETTE_RGB.items()}

MODES = ("mstag", "exp1")


class DecodeError(Exception):
    pass


@dataclass
class EncodeResult:
    mode: str
    prefix: int
    code: int
    cells: list[int]
    payload: bytes            # bytes protected by the checksum/ECC
    ecc_bytes: bytes
    whitened: bytes           # the 11 bytes actually written into 44 cells
    checksum: int | None
    details: dict = field(default_factory=dict)

    @property
    def tag_id(self) -> str:
        return format_tag_id(self.mode, self.prefix, self.code)


@dataclass
class DecodeResult:
    ok: bool
    mode: str | None = None
    prefix: int | None = None
    code: int | None = None
    checksum_ok: bool | None = None
    corrected_symbols: list[int] = field(default_factory=list)
    erasures: list[int] = field(default_factory=list)
    reason: str = ""
    details: dict = field(default_factory=dict)

    @property
    def tag_id(self) -> str | None:
        if not self.ok:
            return None
        return format_tag_id(self.mode, self.prefix, self.code)


def format_tag_id(mode: str, prefix: int, code: int) -> str:
    if mode == "mstag":
        return f"{prefix:05d}_{code:010d}"
    return f"X{prefix:03d}_{code:010d}"


# ---------------------------------------------------------------- bit helpers

def bytes_to_cells_lsb(data: bytes) -> list[int]:
    """mstag packing: bits read LSB-first; cell = (b0 << 1) | b1."""
    out = []
    for pos in range(0, len(data) * 8, 2):
        b0 = (data[pos // 8] >> (pos % 8)) & 1
        b1 = (data[(pos + 1) // 8] >> ((pos + 1) % 8)) & 1
        out.append((b0 << 1) | b1)
    return out


def cells_to_bytes_lsb(cells: list[int]) -> bytes:
    out = bytearray((len(cells) * 2 + 7) // 8)
    bit = 0
    for c in cells:
        for b in ((c >> 1) & 1, c & 1):
            if b:
                out[bit // 8] |= 1 << (bit % 8)
            bit += 1
    return bytes(out)


def bytes_to_cells_msb(data: bytes) -> list[int]:
    """exp1 packing: four cells per byte, most-significant pair first."""
    return [(b >> s) & 3 for b in data for s in (6, 4, 2, 0)]


def cells_to_bytes_msb(cells: list[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(cells), 4):
        v = 0
        for c in cells[i:i + 4]:
            v = (v << 2) | c
        out.append(v)
    return bytes(out)


def bytes_to_symbols5(data: bytes) -> list[int]:
    """MSB-first bitstream split into 5-bit symbols, last one right-padded."""
    syms, acc, bits = [], 0, 0
    for b in data:
        acc = (acc << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            syms.append((acc >> bits) & 0x1F)
            acc &= (1 << bits) - 1
    if bits:
        syms.append((acc << (5 - bits)) & 0x1F)
    return syms


def symbols5_to_bytes(syms: list[int], nbytes: int) -> tuple[bytes, int]:
    """Inverse of bytes_to_symbols5. Returns (bytes, value of the padding bits)."""
    acc, bits = 0, 0
    for s in syms:
        acc = (acc << 5) | s
        bits += 5
    extra = bits - nbytes * 8
    pad = acc & ((1 << extra) - 1)
    acc >>= extra
    return acc.to_bytes(nbytes, "big"), pad


def crc16_x25(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return crc ^ 0xFFFF


# ------------------------------------------------------------- mstag (RE)

# 100-byte XOR whitening table as published by UN_HCCB (claimed to be embedded
# in Microsoft's libtagdecoder.so). Only the first 11 bytes are used for 5x10.
MSTAG_XOR = bytes.fromhex(
    "0f4d9417483a861c02f8e3e896e8074c"
    "d1f7183b18cfc97723630430fdc82fcb"
    "2104c488055a43d3e2886a8a70d19be6"
    "996910475f80830624b253fd6478905a"
    "6250c64a49df7d2c9b08860c7a612b6a"
    "a5d107123046ce404b7786ea2bcb42fe"
    "8a8a3dc1"
)
MSTAG_FILLER = [0, 1]
_GF32 = GaloisField(5, 0x25)            # x^5 + x^2 + 1
MSTAG_RS = ReedSolomon(_GF32, nsym=4, fcr=1)  # RS(17,13) shortened from (31,27)


def _xor(data: bytes, table: bytes) -> bytes:
    return bytes(b ^ table[i % len(table)] for i, b in enumerate(data))


def mstag_encode(prefix: int, code: int) -> EncodeResult:
    if not 0 <= prefix <= 0xFFFF:
        raise ValueError("mstag prefix must be 0..65535")
    if not 0 <= code <= 0xFFFFFFFF:
        raise ValueError("mstag code must be 0..4294967295")
    body = struct.pack("<HI", prefix, code)
    crc = crc16_x25(body)
    raw8 = struct.pack("<H", crc) + body
    dsyms = bytes_to_symbols5(raw8)               # 13 symbols (65 bits, 1 pad bit)
    psyms = MSTAG_RS.parity(dsyms)                # 4 symbols
    pbytes = _pack5_padded(psyms, 3)              # 20 bits + 4 zero pad bits -> 3 bytes
    rsbuf = pbytes + raw8
    whitened = _xor(rsbuf, MSTAG_XOR)
    cells = bytes_to_cells_lsb(whitened) + MSTAG_FILLER + CALIBRATION
    return EncodeResult(
        mode="mstag", prefix=prefix, code=code, cells=cells, payload=raw8,
        ecc_bytes=pbytes, whitened=whitened, checksum=crc,
        details={
            "data_symbols_gf32": dsyms,
            "parity_symbols_gf32": psyms,
            "rs_buffer": rsbuf.hex(),
            "layout": "cells[0:44]=LSB-first 2-bit packing of XOR(parity3 || crc16le || prefix16le || code32le); [44:46]=filler [0,1]; [46:50]=calibration [0,1,2,3]",
        },
    )


def _pack5_padded(syms: list[int], nbytes: int) -> bytes:
    acc, bits = 0, 0
    for s in syms:
        acc = (acc << 5) | s
        bits += 5
    acc <<= nbytes * 8 - bits
    return acc.to_bytes(nbytes, "big")


def mstag_decode_cells(cells: list[int], erasure_cells: list[int] | None = None) -> DecodeResult:
    if len(cells) != N_CELLS:
        raise ValueError("need 50 cells")
    whitened = cells_to_bytes_lsb(cells[:N_DATA_CELLS])
    rsbuf = _xor(whitened, MSTAG_XOR)
    pbytes, raw8 = rsbuf[:3], rsbuf[3:]
    pacc = int.from_bytes(pbytes, "big")
    psyms = [(pacc >> (19 - 5 * i)) & 0x1F for i in range(4)]
    pad_bits = pacc & 0xF
    dsyms = bytes_to_symbols5(raw8)
    cw = psyms + dsyms  # lowest degree first
    # Map erased cells to RS symbol positions.
    er_sym: set[int] = set()
    for c in erasure_cells or []:
        for bitpos in (2 * c, 2 * c + 1):
            byte, b_lsb = divmod(bitpos, 8)
            stream = byte * 8 + (7 - b_lsb)  # MSB-first stream position
            if byte < 3:
                if stream < 20:
                    er_sym.add(stream // 5)
            else:
                er_sym.add(4 + (stream - 24) // 5)
    res = MSTAG_RS.decode(cw, sorted(er_sym))
    details = {"syndromes_nonzero": any(MSTAG_RS.syndromes(cw)), "rs_reason": res.reason,
               "parity_pad_bits": pad_bits}
    if not res.ok:
        return DecodeResult(False, "mstag", reason=f"Reed-Solomon GF(32) failed: {res.reason}", details=details)
    fixed = res.codeword
    raw8c, last_pad = symbols5_to_bytes(fixed[4:], 8)
    if last_pad != 0:
        return DecodeResult(False, "mstag", reason="RS output has non-zero padding bit (miscorrection)", details=details)
    stored = int.from_bytes(raw8c[:2], "little")
    calc = crc16_x25(raw8c[2:])
    if stored != calc:
        return DecodeResult(False, "mstag", checksum_ok=False,
                            reason=f"CRC16-X25 mismatch (stored {stored:04X}, computed {calc:04X})", details=details)
    prefix, code = struct.unpack("<HI", raw8c[2:])
    return DecodeResult(True, "mstag", prefix, code, checksum_ok=True,
                        corrected_symbols=res.error_positions, erasures=sorted(er_sym), details=details)


# -------------------------------------------------------------- exp1 (ours)

EXP1_FILLER = [3, 2]
_GF256 = GaloisField(8, 0x11D)
EXP1_RS = ReedSolomon(_GF256, nsym=6, fcr=0)  # RS(11,5)


def _exp1_whitening() -> bytes:
    # 11 bytes from a documented 16-bit Galois LFSR (taps 0xB400, seed 0xACE1).
    s, out = 0xACE1, bytearray()
    for _ in range(11):
        v = 0
        for _ in range(8):
            lsb = s & 1
            s >>= 1
            if lsb:
                s ^= 0xB400
            v = (v << 1) | lsb
        out.append(v)
    return bytes(out)


EXP1_XOR = _exp1_whitening()
EXP1_MAX_ERRORS = 3


def exp1_encode(prefix: int, code: int) -> EncodeResult:
    if not 0 <= prefix <= 0xFF:
        raise ValueError("exp1 prefix must be 0..255")
    if not 0 <= code <= 0xFFFFFFFF:
        raise ValueError("exp1 code must be 0..4294967295")
    payload = struct.pack(">BI", prefix, code)
    msg = list(payload)
    # Codeword as transmitted: payload bytes first, then parity (high degree first).
    parity = EXP1_RS.parity(list(reversed(msg)))
    tx = bytes(msg + list(reversed(parity)))
    whitened = _xor(tx, EXP1_XOR)
    cells = bytes_to_cells_msb(whitened) + EXP1_FILLER + CALIBRATION
    return EncodeResult(
        mode="exp1", prefix=prefix, code=code, cells=cells, payload=payload,
        ecc_bytes=tx[5:], whitened=whitened, checksum=None,
        details={"layout": "cells[0:44]=MSB-first 2-bit packing of XOR(prefix8 || code32be || RS(11,5) parity6); [44:46]=filler [3,2]; [46:50]=calibration [0,1,2,3]"},
    )


def exp1_decode_cells(cells: list[int], erasure_cells: list[int] | None = None,
                      max_errors: int = EXP1_MAX_ERRORS) -> DecodeResult:
    whitened = cells_to_bytes_msb(cells[:N_DATA_CELLS])
    tx = _xor(whitened, EXP1_XOR)
    cw = list(reversed(tx))  # lowest degree first
    er = sorted({10 - c // 4 for c in (erasure_cells or []) if c < N_DATA_CELLS})
    res = EXP1_RS.decode(cw, er)
    if not res.ok:
        return DecodeResult(False, "exp1", reason=f"Reed-Solomon GF(256) failed: {res.reason}")
    if len(res.error_positions) > max_errors:
        return DecodeResult(False, "exp1", reason=f"{len(res.error_positions)} errors exceeds acceptance limit {max_errors}")
    fixed = bytes(reversed(res.codeword))
    prefix, code = struct.unpack(">BI", fixed[:5])
    return DecodeResult(True, "exp1", prefix, code, checksum_ok=True,
                        corrected_symbols=res.error_positions, erasures=er)


# ------------------------------------------------------------ dispatchers

def encode(mode: str, prefix: int, code: int) -> EncodeResult:
    if mode == "mstag":
        return mstag_encode(prefix, code)
    if mode == "exp1":
        return exp1_encode(prefix, code)
    raise ValueError(f"unknown mode {mode!r}")


def detect_mode(cells: list[int]) -> str | None:
    f = cells[44:46]
    if f == MSTAG_FILLER:
        return "mstag"
    if f == EXP1_FILLER:
        return "exp1"
    return None


def decode_cells(cells: list[int], erasure_cells: list[int] | None = None,
                 modes: tuple[str, ...] = MODES, require_trailer: bool = True) -> DecodeResult:
    """Decode 50 cells. The filler cells select the mode; trailer cells are checked."""
    if len(cells) != N_CELLS:
        raise ValueError("need 50 cells")
    if require_trailer and cells[46:50] != CALIBRATION:
        return DecodeResult(False, reason="calibration cells 46-49 are not [Y,M,K,C]")
    mode = detect_mode(cells)
    if mode is None or mode not in modes:
        return DecodeResult(False, reason=f"filler cells {cells[44:46]} match no enabled mode")
    if mode == "mstag":
        return mstag_decode_cells(cells, erasure_cells)
    return exp1_decode_cells(cells, erasure_cells)
