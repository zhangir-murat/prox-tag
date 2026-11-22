import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { crc16x25, formatTagId, mstagCells, parseTagId } from "./codec";

const golden = JSON.parse(readFileSync(new URL("../../fixtures/unhccb_golden_vectors.json", import.meta.url), "utf8"));

describe("codec (TS port)", () => {
  it("CRC-16/X-25 check value", () => {
    expect(crc16x25(new TextEncoder().encode("123456789"))).toBe(0x906e);
  });
  it("matches all 50 UN_HCCB reference vectors", () => {
    expect(golden.vectors.length).toBe(50);
    for (const v of golden.vectors) expect(mstagCells(v.prefix, v.code)).toEqual(v.cells);
  });
  it("is deterministic and injective over a range", () => {
    const seen = new Set<string>();
    for (let c = 0; c < 1000; c++) {
      const k = mstagCells(1, c).join("");
      expect(seen.has(k)).toBe(false);
      seen.add(k);
    }
  });
  it("rejects out-of-range ids", () => {
    expect(() => mstagCells(70000, 1)).toThrow();
    expect(() => mstagCells(1, 2 ** 32)).toThrow();
  });
  it("formats and parses tag ids", () => {
    expect(formatTagId("mstag", 1, 9692)).toBe("00001_0000009692");
    expect(formatTagId("exp1", 7, 42)).toBe("X007_0000000042");
    expect(parseTagId("00001_0000009692")).toEqual({ mode: "mstag", prefix: 1, code: 9692 });
    expect(parseTagId("x7:42")).toEqual({ mode: "exp1", prefix: 7, code: 42 });
    expect(parseTagId("1:99999999999")).toBeNull();
    expect(parseTagId("https://example.com")).toBeNull();
  });
});
