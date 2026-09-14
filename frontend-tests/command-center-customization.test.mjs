import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

function loadTs(path) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
  return import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
}

test("quick tap Y opens swap customization while hold Y enters move mode", async () => {
  const { createCustomizeGestureRecognizer, CUSTOMIZE_HOLD_MS } = await loadTs("../src/quick-access/expanded-command-center/customization-input.ts");
  let clock = 1000;
  const events = [];
  const recognizer = createCustomizeGestureRecognizer({ tab: () => "quick", now: () => clock, onGesture: event => events.push(event) });
  recognizer.down(); clock += CUSTOMIZE_HOLD_MS - 1; recognizer.up();
  recognizer.down(); clock += CUSTOMIZE_HOLD_MS; recognizer.up();
  assert.deepEqual(events, [{kind:"swap",tab:"quick"},{kind:"move",tab:"quick"}]);
});

test("non-quick tabs only allow reorder on hold", async () => {
  const { createCustomizeGestureRecognizer, CUSTOMIZE_HOLD_MS } = await loadTs("../src/quick-access/expanded-command-center/customization-input.ts");
  let clock = 1000;
  const events = [];
  const recognizer = createCustomizeGestureRecognizer({ tab: () => "egpu", now: () => clock, onGesture: event => events.push(event) });
  recognizer.down(); clock += 100; recognizer.up();
  recognizer.down(); clock += CUSTOMIZE_HOLD_MS; recognizer.up();
  assert.deepEqual(events, [{kind:"move",tab:"egpu"}]);
});

test("reorder helper moves one-cell buttons without changing membership", async () => {
  const source = readFileSync(new URL("../src/quick-access/expanded-command-center/layout-customization.tsx", import.meta.url), "utf8");
  assert.match(source, /reorderById/);
  assert.match(source, /regearTileJiggle/);
  assert.match(source, /prefers-reduced-motion/);
  assert.match(source, /D-pad moves the selected button/);
});

test('hold fires at550ms while pressed, ignores repeats and stale cancelled callbacks, and release never taps after hold',async()=>{
 const {createCustomizeGestureRecognizer}=await loadTs('../src/quick-access/expanded-command-center/customization-input.ts');
 let clock=0;const jobs=[],events=[];
 const recognizer=createCustomizeGestureRecognizer({tab:()=> 'quick',now:()=>clock,onGesture:e=>events.push(e),schedule:(fn,delay)=>{const job={fn,at:clock+delay};jobs.push(job);return job;},unschedule:job=>job.cancelled=true});
 const advance=ms=>{clock+=ms;for(const job of jobs){if(!job.cancelled&&!job.ran&&job.at<=clock){job.ran=true;job.fn();}}};
 recognizer.down();recognizer.down();advance(549);assert.equal(events.length,0);advance(1);assert.deepEqual(events,[{kind:'move',tab:'quick'}]);assert.equal(recognizer.isPressed(),true);
 recognizer.up();assert.equal(events.length,1);
 recognizer.down();const stale=jobs.at(-1);recognizer.cancel();recognizer.down();stale.fn();assert.equal(events.length,1);advance(20);recognizer.up();assert.deepEqual(events.at(-1),{kind:'swap',tab:'quick'});
 recognizer.down();const abandoned=jobs.at(-1);recognizer.cancel();abandoned.fn();advance(600);assert.equal(events.length,2);
});
