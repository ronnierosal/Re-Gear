import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const popup = readFileSync(new URL('../src/quick-access/expanded-command-center/popup-ui.tsx', import.meta.url), 'utf8');
const egpu = readFileSync(new URL('../src/quick-access/expanded-command-center/egpu-ui.tsx', import.meta.url), 'utf8');

test('popup shell centers itself and stays viewport safe', () => {
  assert.match(popup, /data-regear-popup-layer/);
  assert.match(popup, /position: "fixed"/);
  assert.match(popup, /placeItems: "center"/);
  assert.match(popup, /calc\(100vw - 48px\)/);
  assert.match(popup, /calc\(100vh - 48px\)/);
});

test('active popup states animate but respect reduced motion', () => {
  assert.match(popup, /regearPopupPulse/);
  assert.match(popup, /prefers-reduced-motion: reduce/);
  assert.match(popup, /data-regear-popup-active/);
});

test('eGPU connection popup is compact and caps visible lifecycle rows', () => {
  assert.match(egpu, /export function EgpuConnectionPopup/);
  assert.match(egpu, /steps\.slice\(0, 4\)/);
  assert.match(egpu, /Connecting eGPU/);
  assert.match(egpu, /eGPU connected/);
});

test('retry is runtime-gated rather than elapsed-time driven', () => {
  assert.match(egpu, /mode === "failed" \? retryAction : null/);
  assert.match(egpu, /Retry appears only when the runtime has explicitly classified/);
  assert.match(egpu, /Retry is intentionally unavailable until runtime explicitly reports a retry-safe failure/);
});

test('delayed mode offers waiting rather than blind restart', () => {
  assert.match(egpu, /mode === "delayed" \? keepWaitingAction : null/);
  assert.match(egpu, /Taking longer than usual/);
});
