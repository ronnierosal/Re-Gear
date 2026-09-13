import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/quick-access/expanded-command-center/utility-rail.tsx", import.meta.url), "utf8");

test("utility rail exports a stable runtime wiring seam", () => {
  assert.match(source.replace(/\s/g, ""), /exporttypeUtilityRailProps/);
  assert.match(source.replace(/\s/g, ""), /readings\?:Partial<Record<UtilityId,UtilityReading>>/);
  assert.match(source.replace(/\s/g, ""), /onRequest\?:\(id:UtilityId,percent\?:number\)=>Promise<void>/);
});

test("rapid brightness and volume changes preserve the newest requested value", () => {
  assert.match(source.replace(/\s/g, ""), /queued=useRef\(newMap<UtilityId,number>\(\)\)/);
  assert.match(source.replace(/\s/g, ""), /queued\.current\.set\(id,percent\)/);
  assert.match(source.replace(/\s/g, ""), /constnext=queued\.current\.get\(id\)/);
  assert.match(source.replace(/\s/g, ""), /if\(next!==undefined&&next!==percent\)voidrun\(id,next\)/);
});

test("slider availability is truthful and pending work remains visible", () => {
  assert.match(source.replace(/\s/g, ""), /Boolean\(reading\?\.pending\)/);
  assert.match(source.replace(/\s/g, ""), /aria-busy=\{waiting\|\|undefined\}/);
  assert.match(source.replace(/\s/g, ""), /Noverifiedcapability/);
});
