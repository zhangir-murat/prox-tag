/**
 * TypeScript port of the MS Tag (reverse-engineered) symbol encoder.
 * Used by the UI to cross-check the server and by Vitest to verify the
 * format against the third-party UN_HCCB golden vectors in /fixtures.
 * Decoding (and everything image-related) is done by the Python backend.
 */

export function crc16x25(data: Uint8Array): number {
  let crc = 0xffff;
  for (const b of data) {
    crc ^= b;
    for (let i = 0; i < 8; i++) crc = crc & 1 ? (crc >>> 1) ^ 0x8408 : crc >>> 1;
  }
  return (crc ^ 0xffff) & 0xffff;
}

// GF(32), primitive x^5 + x^2 + 1
const EXP: number[] = [];
const LOG: number[] = new Array(32).fill(0);
{
  let x = 1;
  for (let i = 0; i < 31; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 32) x ^= 0x25;
  }
  for (let i = 31; i < 62; i++) EXP[i] = EXP[i - 31];
}
const gmul = (a: number, b: number) => (a && b ? EXP[LOG[a] + LOG[b]] : 0);

function generator(nsym: number, fcr: number): number[] {
  let g = [1];
  for (let j = 0; j < nsym; j++) {
    const root = EXP[(fcr + j) % 31];
    const out = new Array(g.length + 1).fill(0);
    g.forEach((c, i) => {
      out[i] ^= gmul(c, root);
      out[i + 1] ^= c;
    });
    g = out;
  }
  return g; // lowest degree first
}
const GEN = generator(4, 1);

export function rsParity(msg: number[]): number[] {
  const rem = [0, 0, 0, 0];
  for (let i = msg.length - 1; i >= 0; i--) {
    const fb = msg[i] ^ rem[3];
    for (let k = 3; k > 0; k--) rem[k] = rem[k - 1] ^ gmul(fb, GEN[k]);
    rem[0] = gmul(fb, GEN[0]);
  }
  return rem;
}

function toSymbols5(bytes: Uint8Array): number[] {
  const out: number[] = [];
  let acc = 0,
    bits = 0;
  for (const b of bytes) {
    acc = (acc << 8) | b;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      out.push((acc >> bits) & 31);
      acc &= (1 << bits) - 1;
    }
  }
  if (bits) out.push((acc << (5 - bits)) & 31);
  return out;
}

export const MSTAG_XOR = hex(
  "0f4d9417483a861c02f8e3e896e8074cd1f7183b18cfc97723630430fdc82fcb2104c488055a43d3e2886a8a70d19be6996910475f80830624b253fd6478905a6250c64a49df7d2c9b08860c7a612b6aa5d107123046ce404b7786ea2bcb42fe8a8a3dc1",
);

function hex(s: string): Uint8Array {
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.slice(2 * i, 2 * i + 2), 16);
  return out;
}

export function mstagCells(prefix: number, code: number): number[] {
  if (!(prefix >= 0 && prefix <= 0xffff && Number.isInteger(prefix))) throw new Error("prefix out of range");
  if (!(code >= 0 && code <= 0xffffffff && Number.isInteger(code))) throw new Error("code out of range");
  const body = new Uint8Array(6);
  const dv = new DataView(body.buffer);
  dv.setUint16(0, prefix, true);
  dv.setUint32(2, code, true);
  const crc = crc16x25(body);
  const raw = new Uint8Array(8);
  new DataView(raw.buffer).setUint16(0, crc, true);
  raw.set(body, 2);
  const par = rsParity(toSymbols5(raw));
  const pacc = ((par[0] << 15) | (par[1] << 10) | (par[2] << 5) | par[3]) << 4;
  const buf = new Uint8Array(11);
  buf[0] = (pacc >>> 16) & 255;
  buf[1] = (pacc >>> 8) & 255;
  buf[2] = pacc & 255;
  buf.set(raw, 3);
  const cells: number[] = [];
  for (let pos = 0; pos < 88; pos += 2) {
    const w = (i: number) => (buf[i >> 3] ^ MSTAG_XOR[i >> 3]) >> (i & 7) & 1;
    cells.push((w(pos) << 1) | w(pos + 1));
  }
  return [...cells, 0, 1, 0, 1, 2, 3];
}

export function formatTagId(mode: string, prefix: number, code: number): string {
  const p = mode === "mstag" ? String(prefix).padStart(5, "0") : "X" + String(prefix).padStart(3, "0");
  return `${p}_${String(code).padStart(10, "0")}`;
}

/** Parse "00001_0000009692", "X001_0000000042" or "1:9692" style IDs. */
export function parseTagId(s: string): { mode: "mstag" | "exp1"; prefix: number; code: number } | null {
  const t = s.trim();
  let m = /^X(\d{1,3})[_:](\d{1,10})$/i.exec(t);
  if (m) return check("exp1", +m[1], +m[2]);
  m = /^(\d{1,5})[_:](\d{1,10})$/.exec(t);
  if (m) return check("mstag", +m[1], +m[2]);
  return null;
}

function check(mode: "mstag" | "exp1", prefix: number, code: number) {
  const pmax = mode === "mstag" ? 0xffff : 0xff;
  if (prefix > pmax || code > 0xffffffff) return null;
  return { mode, prefix, code };
}
