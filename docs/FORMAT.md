# Encoding format implemented by HCCB Lab

Both modes share one visual layout and one scanner. The **filler cells 44–45** tell the modes apart.

## Geometry (abstract units, `backend/hccb/geometry.py`)

```
 ┌──────────── quiet zone 26 (white) ─────────────┐
 │ ┌──────────── black frame 428.8 × 418 ───────┐ │
 │ │ top bar 18                                 │ │
 │ │════════ white separator 11 ════════════════│ │
 │ │ ▼▲▼▲▼▲▼▲▼▲   row 0  cells 0–9   (h = 60)   │ │
 │ │═════════════════════════════════════════════│ │
 │ │ ▼▲▼▲▼▲▼▲▼▲   row 1  cells 10–19            │ │
 │ │   …                                        │ │
 │ │ ▼▲▼▲▼▲▼▲▼▲   row 4  cells 40–49            │ │
 │ │═════════════════════════════════════════════│ │
 │ │ bottom bar 34  (heavier: orientation cue)  │ │
 │ └────────────────────────────────────────────┘ │
 └────────────────────────────────────────────────┘
side bars 24; triangle base = 2h/√3; neighbours overlap by half a base.
Even columns point down, odd columns point up.
```

Palette: `0 = yellow #FFFF00`, `1 = magenta #FF00FF`, `2 = black #000000`, `3 = cyan #00FFFF`.
Cells 46–49 are always `Y M K C` (calibration).

## MS Tag (reverse-engineered) mode, `mstag`

```
body    = prefix:u16le ‖ code:u32le                     6 bytes
crc     = CRC-16/X-25(body)  (poly 0x8408 reflected, init/xorout 0xFFFF)
raw8    = crc:u16le ‖ body                              8 bytes = 64 bits
d[0..12]= raw8 as MSB-first 5-bit symbols (last one padded with 1 zero bit)
p[0..3] = RS parity, GF(32) prim 0x25, generator ∏_{j=1..4}(x − α^j)
          codeword c(x) = Σ p_j x^j + Σ d_i x^(i+4)     (n = 17, k = 13)
par3    = p0‖p1‖p2‖p3 MSB-first in 20 bits + 4 zero pad bits
buf     = par3 ‖ raw8                                   11 bytes
w       = buf XOR MSTAG_XOR[0..10]                      (0f4d9417483a861c02f8e3…)
cell[k] = (bit(w, 2k) << 1) | bit(w, 2k+1)  where bit(w,i) = (w[i>>3] >> (i&7)) & 1
cells   = cell[0..43] ‖ [0,1] ‖ [0,1,2,3]
Tag ID  = "PPPPP_CCCCCCCCCC" (decimal prefix_code)
```

Decoder: invert the packing, de-whiten, RS errors-and-erasures decode (corrects 2e + s ≤ 4 symbols),
require the RS data pad bit to be 0, verify the CRC. Erasures come from the scanner's lowest-confidence
cells (each cell maps to one or two GF(32) symbols).

Measured at the cell level (`tests/test_codec.py`): 1 wrong cell → always corrected. 2 random wrong
cells → ≈ 91 % corrected. 3 → ≈ 20 %. 12 → always rejected, never misdecoded. 50,000 random
cell patterns → 0 accepted.

## Experimental Tag Mode v1, `exp1`

```
payload = prefix:u8 ‖ code:u32be                        5 bytes
tx      = payload ‖ RS(11,5) parity                     GF(256) prim 0x11D, fcr 0, 6 parity bytes
w       = tx XOR LFSR16(taps 0xB400, seed 0xACE1)[0..10]
cells   = each byte → 4 cells, MSB pair first           (byte-aligned: 1 cell ∈ exactly 1 symbol)
cells   = 44 data ‖ [3,2] filler ‖ [0,1,2,3]
Tag ID  = "XPPP_CCCCCCCCCC"
```

The code can correct any 3 wrong bytes (up to 12 cells when they cluster) or 6 erased bytes. Acceptance policy:
hard-decision decodes may use the full radius (3 errors). **Assisted** decodes (scanner-supplied erasures or
Chase substitutions) must satisfy 2e + s ≤ 4, so at least 2 parity symbols remain unused as a check.

### Acceptance budget (both modes)
An early benchmark run produced one wrong ID: a mis-oriented warp gave garbage cells, the scanner erased 6
low-confidence cells (= all 6 exp1 parity symbols) and RS "solved" the garbage. With zero redundancy left,
any input decodes. The fix (`codec.ASSISTED_BUDGET`): exp1 assisted decodes need 2e+s ≤ 4 (2 parity symbols stay unused as a check). mstag may use all 4 parity
symbols because CRC16-X25 is an independent 16-bit check. Measured: 0 accepts in 600 rendered adversarial
mosaics and 40,000 random assisted codec trials. The scanner also rejects warps where calibration cell 48 (black) is not the
darkest calibration cell. The image is kept as `fixtures/regression/` and tested.

## Why two modes?
The reverse-engineered format packs 2-bit cells into 5-bit symbols, so one colour error can corrupt two
RS symbols. Exp1 shows what the same 50-triangle real estate does with byte-aligned symbols. The
benchmark compares the two under identical distortions.
