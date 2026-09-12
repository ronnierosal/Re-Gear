import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const popup=readFileSync(new URL('../src/quick-access/expanded-command-center/popup-ui.tsx',import.meta.url),'utf8');
const customize=readFileSync(new URL('../src/quick-access/expanded-command-center/quick-actions-customization.tsx',import.meta.url),'utf8');
const layout=readFileSync(new URL('../src/quick-access/expanded-command-center/utility-layout.ts',import.meta.url),'utf8');

test('shared popup keeps viewport-safe max dimensions and an internally scrolling body',()=>{
 assert.match(popup,/calc\(100vw - 48px\)/);
 assert.match(popup,/calc\(100vh - 48px\)/);
 assert.match(popup,/data-regear-popup-body/);
 assert.match(popup,/overflow: "auto"/);
});

test('popup status rows use the repository icon component instead of unicode status glyphs',()=>{
 assert.match(popup,/CommandCenterIcon/);
 assert.doesNotMatch(popup,/[✓✔❌⚠]/);
});

test('quick action customization cannot absorb brightness or volume',()=>{
 assert.match(customize,/Brightness and Volume remain part of the main Command Center/);
 assert.match(layout,/commandCenterUtilityIds = \["brightness", "volume"\]/);
 assert.match(layout,/side !== "right"/);
});

test('approved quick actions remain stable and optional actions are explicit',()=>{
 assert.match(layout,/quickActionIds = \["mic", "wifi", "overlay", "recording"\]/);
 assert.match(layout,/optionalQuickActionIds = \["audio"\]/);
});
