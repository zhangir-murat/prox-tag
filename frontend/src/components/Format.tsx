export function Format() {
  return (
    <div className="grid cols-2">
      <div className="panel prose">
        <h2>Format & evidence</h2>
        <p>
          Microsoft Tag (2009–2015) printed a 5 × 10 HCCB symbol that carried only a short numeric identifier; the destination lived on Microsoft's
          servers. Those servers are gone, so this lab ships its own resolver.
        </p>
        <h3>Evidence levels</h3>
        <table className="data">
          <thead>
            <tr><th>claim</th><th>status</th></tr>
          </thead>
          <tbody>
            <tr><td>Rows of alternating triangles, white row separators, black frame, coloured cells</td><td><span className="badge ok">confirmed</span> MSR samples</td></tr>
            <tr><td>Microsoft Tag grew out of MSR's HCCB; 3/4″ minimum print size; decode on mobile</td><td><span className="badge ok">confirmed</span> MSR page</td></tr>
            <tr><td>5×10 cells, palette Y/M/K/C, 2 bits per cell</td><td><span className="badge warn">third-party RE</span> UN_HCCB</td></tr>
            <tr><td>CRC16-X25 ‖ prefix16 ‖ code32, little-endian</td><td><span className="badge warn">third-party RE</span></td></tr>
            <tr><td>RS over GF(32), x⁵+x²+1, 4 parity symbols (t = 2)</td><td><span className="badge warn">third-party RE</span>; we verified it is a valid RS(17,13), fcr = 1</td></tr>
            <tr><td>100-byte XOR whitening table, LSB-first 2-bit packing</td><td><span className="badge warn">third-party RE</span></td></tr>
            <tr><td>Cells 44–45 filler [Y,M]; 46–49 calibration [Y,M,K,C]</td><td><span className="badge warn">third-party RE</span></td></tr>
            <tr><td>Exact proportions (separator, border, bottom bar)</td><td><span className="badge bad">unverified</span></td></tr>
            <tr><td>Decoding of genuine historical Microsoft Tags</td><td><span className="badge bad">untested</span> no independently sourced originals available</td></tr>
          </tbody>
        </table>
        <p className="small">
          Round trips between our own encoder and decoder prove internal consistency only. See <code>docs/COMPATIBILITY.md</code> for sources and the
          procedure for validating with real Microsoft Tag images (drop them in <code>fixtures/historical/</code>).
        </p>
      </div>
      <div className="panel prose">
        <h2>Bit layout</h2>
        <h3>MS Tag (RE) mode</h3>
        <ol className="small">
          <li><code>body = prefix (u16 LE) ‖ code (u32 LE)</code>, <code>crc = CRC16-X25(body)</code>, <code>raw8 = crc (u16 LE) ‖ body</code></li>
          <li>raw8 → 13 GF(32) symbols (MSB-first, 1 pad bit); RS(17,13) systematic parity → 4 symbols packed MSB-first into 3 bytes (4 pad bits)</li>
          <li><code>buf = parity3 ‖ raw8</code> (11 bytes) XOR whitening table</li>
          <li>88 bits read LSB-first, two at a time → 44 cells (0 Y, 1 M, 2 K, 3 C)</li>
          <li>append filler [0,1] and calibration [0,1,2,3] → 50 cells, row-major, row 0 at top, col 0 pointing down</li>
        </ol>
        <p className="small">One colour error can hit two 5-bit symbols, so two random cell errors are corrected only ≈ 91 % of the time; cells 8–9 hold pad bits that RS does not protect.</p>
        <h3>Experimental v1 (HCCB Lab)</h3>
        <ol className="small">
          <li><code>payload = prefix (u8) ‖ code (u32 BE)</code></li>
          <li>RS(11,5) over GF(256) (0x11D, fcr = 0) → 6 parity bytes</li>
          <li>XOR with 11 bytes from a 16-bit Galois LFSR (taps 0xB400, seed 0xACE1)</li>
          <li>4 cells per byte, MSB pair first → every cell lies in exactly one RS symbol</li>
          <li>filler [3,2] (C,K) marks the mode; calibration identical</li>
        </ol>
        <p className="small">Corrects any 3 wrong bytes (= up to 12 cells if clustered) or 6 erasures. Scanner-assisted decodes (erasures / Chase) must keep 2e+s ≤ 4 so that unused parity still guards against miscorrection (mstag: ≤ 4, guarded by its independent CRC16).</p>
        <h3>Scanner</h3>
        <p className="small">
          Dark-mask candidates (Otsu + adaptive, multi-scale closing) → convex quad + edge line-fit → 8 dihedral warps ordered by a structural score
          (white separators, black side bars, heavy bottom bar) → row-grid refinement → black/white normalisation from frame and separators → median
          sampling inside shrunken triangles → nearest-reference classification seeded by calibration cells or ideal palette, k-means refined →
          RS hard decision, then errors-and-erasures with the least-confident cells, then Chase trials.
        </p>
      </div>
    </div>
  );
}
