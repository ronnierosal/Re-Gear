import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const native = readFileSync(new URL("../src/quick-access/expanded-command-center/native.tsx", import.meta.url), "utf8");
const control = readFileSync(new URL("../src/whole-dock-control.tsx", import.meta.url), "utf8");

test("native direct activation distinguishes consumed from submitted across remounts", () => {
  assert.match(native, /"available"\|"consumed"\|"submitted"/);
  assert.match(native, /state:\(\)=>startState/);
  assert.match(native, /markSubmitted/);
  assert.doesNotMatch(native, /startState==="consumed"[^\n]*execute_egpu_disconnect/);
});

test("control restores only an explicit retry for consumed-but-unsent activation", () => {
  assert.match(control, /directStartState\(startRequest\) === "consumed"/);
  assert.match(control, /startRequest\.markSubmitted\(\)/);
  assert.match(control, /No request was sent by this attempt/);
  assert.match(control, /onClick=\{\(event\)=>/);
});
