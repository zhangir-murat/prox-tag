# HCCB Lab

A working, testable reconstruction of **Microsoft Tag** (High Capacity Color Barcode, 5 × 10 triangles),
with a real OpenCV scanner, a local URL resolver, and a research UI for stress-testing and embedding visual codes.

> **Compatibility status:** the *MS Tag (RE)* mode re-implements the codec published by the third-party
> UN_HCCB reverse-engineering project, bit for bit. It has **not** been validated against original Microsoft
> Tag images. See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md). The *Experimental v1* mode is this
> project's own documented scheme. The two modes are labelled everywhere and are never substituted for each other.

```
URL → create ID (SQLite) → encode (CRC + Reed–Solomon + whitening) → SVG/PNG → camera/photo
    → detect frame → rectify → normalise colour → classify 50 cells → RS errors+erasures → checksum
    → ID → resolver lookup → open URL (+ scan event logged)
```

## Quick start (desktop)

Requirements: Python ≥ 3.10, Node ≥ 18. No paid APIs, no Microsoft servers.

```bash
cd backend
pip install -r requirements.txt
```

```bash
cd frontend
npm install
npm run build
```

```bash
cd backend
uvicorn app:app --port 8000
```

Open http://localhost:8000. The backend also serves the built UI. `localhost` counts as a secure context, so the laptop webcam works.

For UI development with hot reload, run the backend as above, then in another terminal:

```bash
cd frontend
npm run dev
```

and open http://localhost:5173 (`/api` is proxied to port 8000).

## Testing with your iPhone (or Android) camera

Mobile browsers only allow the camera on **HTTPS** pages. Two options:

**A. One command (recommended).** This builds the UI, creates a self-signed certificate in `certs/`, and serves everything over HTTPS:

```bash
scripts/run_https.sh 8443
```

**B. Dev server.** Keep the backend on port 8000, then run:

```bash
cd frontend
npm run dev:https
```

Then serve https://&lt;LAN-IP&gt;:5173.

On the iPhone:
1. Join the same Wi-Fi as the computer. The script prints the URL, e.g. `https://192.168.1.23:8443`. If the computer's firewall asks, allow incoming connections.
2. Open it in **Safari**. You'll see *"This Connection Is Not Private"* (self-signed cert): tap **Show Details → visit this website → Visit Website**.
3. Generate a tag on the computer (tab **A · Generate**) and leave it on screen, or print it ≥ 25 mm wide.
4. On the phone, open **B · Scan → Start camera** and allow camera access. Hold the phone 15–30 cm away so the black frame fills about a third of the view.
   The first frame that passes Reed–Solomon + checksum is decoded, logged, and shown with its diagnostics.
   Tick *open destination automatically* to complete the original Microsoft Tag experience.
5. Alternatively, use **Take photo (mobile)**, which uses the native camera app with full resolution and autofocus.

Tips: avoid glare on glossy prints and screens (tilt slightly); a phone photographing a monitor works but moiré can reduce
colour confidence. The Scan tab's "normalised samples" panel shows exactly which cells were ambiguous.

## What's in the UI

| Tab | Purpose |
|---|---|
| **A · Generate** | URL → new tag ID stored in the resolver, or numeric code / tag ID → symbol. Shows bytes, GF(32) symbols and the cell map. SVG/PNG export and print-size export (mm @ dpi, PNG carries a pHYs DPI chunk). Cross-checks the server encoder against an independent TypeScript port. |
| **B · Scan** | Live camera (rear/front) or upload. Shows the detection overlay, dark mask, rectified image, normalised samples vs. classified palette, confidence, palette references, the pipeline log, the checksum/correction status, and the resolver result. Failures carry a specific reason. |
| **C · Experiment** | Size, rotation, perspective (strength + direction), Gaussian and motion blur, brightness, contrast, saturation, hue, gamma, JPEG quality, noise, occlusion (size + position), background type + complexity, seed. **Test Decoding** runs the real scanner on the modified image. A 16-step parameter sweep finds breaking points. |
| **D · Embed** | Upload artwork (a procedural demo poster loads by default). Controls: position, scale, rotation, opacity, separate frame opacity, blend mode (normal/multiply/screen/overlay/soft-light/luminosity/colour), and quiet zone on/off. Every change is verified by scanning the composite, and a threshold sweep finds e.g. the minimum opacity. |
| **E · Tag manager** | All tags, destinations (edit in place: the symbol never changes), enable/disable/delete, per-tag scan history, analytics by outcome/source/day, and recent scan events including unassigned IDs. |
| **F · Benchmark** | Choose conditions, n, modes → real-decoder success rates, wrong-ID counts, failure reasons. Also a false-positive check against decoy images. |
| **G · Format** | Bit layout and evidence levels. |

## Tests

```bash
cd backend
python -m pytest -q
```

At last run this gave 71 passed and 1 skipped (the skip is the empty `fixtures/historical/`). Coverage includes:

* RS errors-and-erasures decoding over GF(32) and GF(256) with random injections.
* 50 golden vectors produced by UN_HCCB's own script.
* 100 random IDs per mode through PNG → scanner.
* 0°/90°/180°/270° rotation and mirroring.
* Scale, JPEG, perspective, hue, desaturation, gamma, blur, noise and clutter conditions.
* Corruption beyond capacity is rejected and never misdecoded (500 trials).
* 50,000 random cell patterns plus 300 rendered adversarial mosaics with a valid trailer: 0 accepted.
* Random colourful images are never accepted.
* Resolver lifecycle, duplicates, and the HTTP end-to-end flow (URL → PNG → scan → URL → edit → same PNG → new URL → redirect → disable → 410).
* The committed image fixtures, including the regression image of a misdecode that was found and fixed.

```bash
cd frontend
npm test
```

This runs the TypeScript encoder against the same 50 golden vectors, plus ID parsing.

Benchmark report (re-generate with `python hccb_cli.py benchmark --n 30 --out ../docs/benchmark.md`):
see [`docs/benchmark.md`](docs/benchmark.md).

## CLI

```bash
cd backend
python hccb_cli.py encode --mode mstag --prefix 1 --code 9692 --png tag.png --svg tag.svg --width-mm 25
```

```bash
python hccb_cli.py decode photo.jpg --debug-dir out/
```

```bash
python hccb_cli.py fixtures ../fixtures
```

## Layout

```
backend/hccb/rs.py         generic GF(2^m) Reed–Solomon (BM + Chien + Forney, errors & erasures)
backend/hccb/codec.py      ID ↔ 50 cells: mstag (reverse-engineered) and exp1 (experimental)
backend/hccb/geometry.py   triangle lattice + frame proportions
backend/hccb/render.py     SVG and anti-aliased raster rendering, print DPI
backend/hccb/detect.py     OpenCV scanner + diagnostics
backend/hccb/distort.py    deterministic distortions (experiments, benchmark)
backend/hccb/embed.py      compositing into artwork with blend modes
backend/hccb/resolver.py   SQLite ID → URL resolver + scan events
backend/hccb/benchmark.py  batch benchmark + false-positive trial
backend/app.py             FastAPI (REST + /r/{mode}/{prefix}/{code} redirect + static UI)
frontend/src/              React + TypeScript UI, codec.ts (TS port of the encoder)
fixtures/                  golden vectors, example symbols, distorted photos, regression image, historical/ slot
docs/                      FORMAT.md, COMPATIBILITY.md, benchmark.md
```

**Stack:** FastAPI + OpenCV (Python has the best CV tooling and makes the codec easy to test), React/TS/Vite UI,
SQLite (zero-config, a single file at `backend/data/hccb_lab.sqlite3`; override with `HCCB_DB`). Decoding runs
server-side, so phones only stream JPEG frames; the trade-off is that scanning needs the local backend.

## Known limitations

* **Historical compatibility is unproven.** No original Microsoft Tag image was available. Proportions,
  orientation conventions and the whitening table come from UN_HCCB; we could not open the patent or the 2009 analyses
  from this environment. See `docs/COMPATIBILITY.md` for how to validate with real tags.
* The Microsoft monochrome ("black & white") Tag variant, custom/"dot" Tags and the larger HCCB grids are not implemented.
* The decoder requires the black frame's four sides to be visible (it locates the frame from its convex hull).
  Occlusion that hits the frame corners or more than ≈ 6–8 cells usually fails. Pure 2-colour images can't carry the palette.
* Synthetic benchmarks are not camera physics. Real optics (defocus, rolling shutter, specular glare, ink gamut,
  white balance) need real photos; use the Scan tab's diagnostics and add your photos as fixtures.
* MS Tag cells 8–9 carry 4 RS-unprotected pad bits. Errors there are harmless (reported as a pad warning) but undetected.
* The camera loop sends about 5 frames/s to the backend at 1280 px. On slow machines it adapts by waiting for each response.
* Blend modes are evaluated on a digital composite. Print or screen reproduction of transparent tags will behave differently.
* No authentication: the resolver API is meant for a trusted local network.
* Patent and trademark status is undetermined (see `docs/COMPATIBILITY.md`). Not affiliated with Microsoft.
