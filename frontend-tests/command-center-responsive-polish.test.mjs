import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

const styles = readFileSync(new URL("../src/quick-access/expanded-command-center/styles.ts", import.meta.url), "utf8");
const rail = readFileSync(new URL("../src/quick-access/expanded-command-center/utility-rail.tsx", import.meta.url), "utf8");

const registrySource=readFileSync(new URL('../src/quick-access/expanded-command-center/control-registry.ts',import.meta.url),'utf8');
const registryJs=ts.transpileModule(registrySource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {controlForKey}=await import('data:text/javascript;base64,'+Buffer.from(registryJs).toString('base64'));

test("Quick root does not spend vertical space on a duplicate title and subtitle", () => {
  assert.match(styles, /data-ec-tab=quick/);
  assert.match(styles, />h2/);
  assert.match(styles, />\.rg-expanded-context/);
  assert.match(styles, /display:none/);
});

test("main command center keeps the approved wide responsive geometry", () => {
  assert.match(styles, /width:min\(78vw,1120px\)/);
  assert.match(styles, /height:79.2vh/);
  assert.doesNotMatch(styles, /width:min\(64vw,980px\)/);
});

test("brightness and volume are visually integrated into the main command center", () => {
  assert.match(styles, /data-utility-side=left/);
  assert.match(styles, /position:absolute/);
  assert.match(styles, /width:clamp\(46px,5\.1vw,55px\)/);
  assert.match(rail, /height:0;min-height:0;flex:1 1 0/);
  assert.doesNotMatch(styles, /Very narrow hosts cannot fit side controls/);
  assert.doesNotMatch(styles, /data-utility-side=left[^}]*display:none/);
});

test("detached action rail fits four compact actions without scrolling", () => {
  assert.match(styles, /data-utility-side=right/);
  assert.match(styles, /width:clamp\(58px,6\.2vw,70px\)/);
  assert.match(styles, /height:79.2vh/);
  assert.match(rail, /data-utility-side=right\] \.rg-utility-control\{[^}]*height:clamp\(46px,9vh,62px\);min-height:0;max-height:62px/);
  assert.match(rail, /height:clamp\(46px,9vh,62px\)/);
  assert.match(rail, /overflow:hidden/);
  assert.doesNotMatch(rail, /min-height:clamp\(58px,13vh,84px\)/);
});

test("utility rails do not add redundant headings and retain approved labels", () => {
  assert.doesNotMatch(rail, /Support unverified/);
  assert.doesNotMatch(rail, /Quick actions/);
  assert.match(rail, /data-utility-id=\{id\}/);
  assert.equal(controlForKey('utility:brightness').label,'Brightness');
  assert.equal(controlForKey('utility:volume').label,'Volume');
  assert.equal(controlForKey('utility:mic').shortLabel,'Mic');
  assert.equal(controlForKey('utility:recording').shortLabel,'Record');
  assert.equal(controlForKey('utility:overlay').shortLabel,'Overlay');
});

test("quick tiles stay compact rather than drifting back to oversized cards", () => {
  const approved=styles.slice(styles.indexOf("/* Ally last-mile overrides"));
  const grid=approved.match(/\.rg-expanded-grid\{([^}]+)\}/)?.[1];
  const tile=approved.match(/\.rg-expanded \.rg-expanded-tile\{([^}]+)\}/)?.[1];
  assert.ok(grid,"grid rule missing"); assert.ok(tile,"tile rule missing");
  assert.match(tile, /height:88px!important;min-height:88px!important;max-height:88px!important/);
  assert.match(grid, /gap:7px/);
  assert.doesNotMatch(tile, /min-height:116px/);
  assert.doesNotMatch(grid, /gap:10px/);
});
