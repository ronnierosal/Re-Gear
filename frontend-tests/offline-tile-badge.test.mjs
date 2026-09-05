import assert from "node:assert/strict";
import test from "node:test";
import { attachOfflineTileBadge, exactTileAppId, exactTileElementAppId } from "../src/offline-tile-badge.ts";

// Small DOM contract double: selector matching is controlled independently of
// connectivity, reproducing virtualized tiles without importing a browser DOM.
function surface(ids = [123]) {
  class Element {
    nodeType = 1;
    tagName = "DIV";
    attrs = new Map();
    children = [];
    parentElement = null;
    connected = true;
    tile = false;
    matchesSelector = true;
    style = {};
    position = "relative";
    get isConnected() { return this.connected && (!this.parentElement || this.parentElement.isConnected); }
    setAttribute(name, value) { this.attrs.set(name, String(value)); }
    getAttribute(name) { return this.attrs.get(name) ?? null; }
    hasAttribute(name) { return this.attrs.has(name); }
    matches() { return this.tile && this.matchesSelector; }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) ?? null; }
    querySelectorAll(selector) { return this.children.flatMap(child => [...((selector === "img" ? child.tagName === "IMG" : child.matches(selector)) ? [child] : []), ...child.querySelectorAll(selector)]); }
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; this.connected = false; }
  }
  const body = new Element();
  const tiles = ids.map(id => {
    const tile = new Element(); tile.tile = true;
    if (id !== null) tile.setAttribute("data-id", id);
    return body.appendChild(tile);
  });
  const observers = [];
  class Observer {
    disconnected = false;
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe(target, options) { this.options = options; }
    disconnect() { this.disconnected = true; }
  }
  const view = {
    document: { body, querySelectorAll: selector => body.querySelectorAll(selector), createElement: tag => { const element = new Element(); element.tagName = tag.toUpperCase(); return element; } },
    MutationObserver: Observer,
    getComputedStyle: element => ({ position: element.position }),
  };
  const mutate = (target, type = "attributes", addedNodes = [], removedNodes = []) => {
    for (const observer of observers) if (!observer.disconnected) observer.callback([{ target, type, addedNodes, removedNodes }]);
  };
  const badges = tile => tile.children.filter(child => child.hasAttribute("data-regear-offline-badge"));
  return { view, tiles, body, mutate, badges, observers, Element };
}

test("tile identity accepts only exact unsigned Steam application IDs", () => {
  for (const value of [null, "", "0", "00123", "123junk", "-123", "4294967296", " 123", "123.0"]) assert.equal(exactTileAppId(value), null);
  assert.equal(exactTileAppId("123"), 123);
  assert.equal(exactTileAppId("4294967295"), 4294967295);
});

test("tile identity accepts one exact Steam artwork ID and rejects conflicts", () => {
  const tile = (sources) => ({
    getAttribute: () => null,
    querySelectorAll: () => sources.map(src => ({ getAttribute: () => src })),
  });
  assert.equal(exactTileElementAppId(tile(["https://cdn.example/apps/123/library.jpg"])), 123);
  assert.equal(exactTileElementAppId(tile(["x/assets/123/a.jpg", "x/assets/123/b.jpg"])), 123);
  assert.equal(exactTileElementAppId(tile(["x/apps/123/a.jpg", "x/apps/456/b.jpg"])), null);
  assert.equal(exactTileElementAppId(tile(["x/anything/123/a.jpg"])), null);
});

test("recycled tiles lose the old game's badge and recover only on the exact identity", () => {
  const s = surface();
  const handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Offline report", () => true);
  try {
    const tile = s.tiles[0];
    assert.equal(s.badges(tile).length, 1);
    tile.setAttribute("data-id", 456); s.mutate(tile);
    assert.equal(s.badges(tile).length, 0);
    tile.setAttribute("data-id", 123); s.mutate(tile);
    assert.equal(s.badges(tile).length, 1);
    s.mutate(tile);
    assert.equal(s.badges(tile).length, 1);
  } finally { handle.stop(); }
});

test("unknown identities and statically positioned tiles get no badge", () => {
  const s = surface([null, "0123", "123junk", 456, 123]);
  s.tiles[4].position = "static";
  const handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Offline report", () => true);
  try { assert.deepEqual(s.tiles.map(s.badges), [[], [], [], [], []]); }
  finally { handle.stop(); }
});

test("expiry and repeated stop preserve Steam's nodes and another owner's badge", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const s = surface();
  const tile = s.tiles[0];
  const native = tile.appendChild(new s.Element());
  const other = tile.appendChild(new s.Element()); other.setAttribute("data-regear-offline-badge", "");
  const handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Offline report", () => true);
  assert.equal(tile.children.length, 3);
  t.mock.timers.tick(29999); assert.equal(tile.children.length, 3);
  t.mock.timers.tick(1);
  assert.deepEqual(tile.children, [native, other]);
  handle.stop(); handle.stop();
  assert.deepEqual(tile.children, [native, other]);
  assert.equal(s.observers[0].disconnected, true);
});

test("source invalidation and throwing context remove badges and disconnect", () => {
  for (const throws of [false, true]) {
    const s = surface(); let valid = true;
    const handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Offline report", () => {
      if (!valid && throws) throw Error("private source unavailable");
      return valid;
    });
    valid = false; handle.validate();
    assert.equal(s.badges(s.tiles[0]).length, 0);
    assert.equal(s.observers[0].disconnected, true);
    s.mutate(s.tiles[0]); assert.equal(s.badges(s.tiles[0]).length, 0);
  }
});

test("ancestor role changes remove badges from connected tiles that leave the library selector", () => {
  const s = surface();
  const handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Offline report", () => true);
  try {
    s.tiles[0].matchesSelector = false;
    s.mutate(s.body);
    assert.equal(s.badges(s.tiles[0]).length, 0);
  } finally { handle.stop(); }
});


test("focused attachment never spreads to duplicate tiles after mutations", () => {
  const s = surface([123, 123]);
  const handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Offline report", () => true, s.tiles[0]);
  try {
    s.mutate(s.body);
    assert.deepEqual(s.tiles.map(tile => s.badges(tile).length), [1, 0]);
  } finally { handle.stop(); }
});

test("artwork-only recycling removes a stale Library badge", () => {
  const s = surface([null]);
  const tile = s.tiles[0];
  const artwork = s.view.document.createElement("img");
  artwork.setAttribute("src", "https://cdn.example/apps/123/library.jpg");
  tile.appendChild(artwork);
  const handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Offline report", () => true, tile);
  try {
    assert.equal(s.badges(tile).length, 1);
    artwork.setAttribute("src", "https://cdn.example/apps/456/library.jpg");
    // Deliver only mutations the production observer actually subscribes to.
    if (s.observers[0].options.attributeFilter.includes("src")) s.mutate(artwork);
    assert.equal(s.badges(tile).length, 0);
  } finally { handle.stop(); }
});


test("badges use a full-size fallback when the native reference is absent", () => {
  const s = surface([123]); const tile = s.tiles[0]; tile.setAttribute("role", "listitem");
  let handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Report", () => true, tile);
  assert.match(s.badges(tile)[0].style.cssText, /bottom:6px/);
  assert.match(s.badges(tile)[0].style.cssText, /width:64px;height:32px/); handle.stop();
  tile.setAttribute("role", "gridcell");
  handle = attachOfflineTileBadge(s.view, 123, "badge.svg", "Report", () => true, tile);
  assert.match(s.badges(tile)[0].style.cssText, /bottom:6px/); handle.stop();
});


test("focused badge remains neutral after expiry and ignores unrelated mutation bursts", t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const s=surface(); const tile=s.tiles[0]; let current=true;
  const handle=attachOfflineTileBadge(s.view,123,"ready.svg","Likely offline-ready",()=>current,tile,
    {image:"verify.svg",label:"Recheck needed"});
  try {
    s.observers[0].callback(Array.from({length:200},()=>({target:s.body,type:"attributes"})));
    assert.equal(s.badges(tile).length,1);
    t.mock.timers.tick(30000);
    assert.equal(s.badges(tile).length,1);
    assert.equal(s.badges(tile)[0].src,"verify.svg");
    assert.equal(s.badges(tile)[0].alt,"Recheck needed");
    t.mock.timers.tick(300000); assert.equal(s.badges(tile).length,1);
    current=false; handle.validate(); assert.equal(s.badges(tile).length,0);
  } finally { handle.stop(); }
});
