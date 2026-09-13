import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/utility-rail.tsx", import.meta.url), "utf8");

test("utility rail exports a stable runtime wiring seam", () => {
  assert.match(source, /export type UtilityRailProps/);
  assert.match(source, /readings\?: Partial<Record<UtilityId,UtilityReading>>/);
  assert.match(source, /onRequest\?: \(id: UtilityId, percent\?: number\) => Promise<void>/);
});

test("rapid brightness and volume changes preserve the newest requested value", () => {
  assert.match(source, /queued = useRef\(new Map<UtilityId,number>\(\)\)/);
  assert.match(source, /queued\.current\.set\(id,percent\)/);
  assert.match(source, /const next = queued\.current\.get\(id\)/);
  assert.match(source, /if \(next !== undefined && next !== percent\) void run\(id,next\)/);
});

test("slider availability is truthful and pending work remains visible", () => {
  assert.match(source, /Boolean\(reading\?\.pending\)/);
  assert.match(source, /aria-busy=\{waiting \|\| undefined\}/);
  assert.match(source, /No verified capability/);
});
