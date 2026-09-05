import assert from "node:assert/strict";
import test from "node:test";
import { offlineBadgeLayout } from "../src/offline-badge-layout.ts";
test("matches visible Steam symbol size and stacks above its group including scaled artwork", () => {
 for (const scale of [0.75, 1, 1.5]) {
  const host={left:0,top:0,width:300*scale,height:150*scale};
  const icon={left:270*scale,top:120*scale,width:20*scale,height:20*scale};
  const group={left:240*scale,top:118*scale,width:52*scale,height:24*scale};
  const result=offlineBadgeLayout(host,300,150,icon,group);
  assert.equal(result.height,32); assert.equal(result.width,64);
  assert.equal(150-result.bottom,114);
  assert.equal(result.left+result.width,292);
 }
});
test("narrow artwork keeps matching size without covering native icon", () => {
 const result=offlineBadgeLayout({left:0,top:0,width:100,height:150},100,150,{left:62,top:120,width:20,height:20});
 assert.equal(result.height,32); assert.equal(150-result.bottom,116);
 assert.equal(result.left+result.width,82);
});
test("invalid and excessively small host geometry is rejected", () => {
 assert.equal(offlineBadgeLayout({left:0,top:0,width:0,height:150},0,150,{left:62,top:120,width:20,height:20}),null);
 assert.equal(offlineBadgeLayout({left:0,top:0,width:40,height:150},40,150,{left:20,top:120,width:20,height:20}),null);
});
