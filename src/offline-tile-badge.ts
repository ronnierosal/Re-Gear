// Native DOM seam researched in sebet/decky-nonsteam-badges (BSD-3-Clause),
// cc620181962f601b713c9db2045e98dd82ecdbf2. Independent bounded implementation:
// exact data-id only; no native style changes, per-tile requests, or polling.
export const OFFLINE_TILE_SELECTOR = 'div[role="tabpanel"] div[role="gridcell"],.ReactVirtualized__Grid__innerScrollContainer div[role="listitem"]';
const OWN = "data-regear-offline-badge";

export function exactTileAppId(value: string | null): number | null {
  if (!value || !/^[1-9][0-9]{0,9}$/.test(value)) return null;
  const id = Number(value);
  return id < 2 ** 32 ? id : null;
}

export function attachOfflineTileBadge(
  view: Window,
  appId: number,
  image: string,
  label: string,
  current: () => boolean,
): { stop(): void; validate(): void } {
  const owned = new Map<Element, HTMLImageElement>();
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let observer: MutationObserver | undefined;
  const stop = () => {
    stopped = true;
    observer?.disconnect();
    clearTimeout(timer);
    for (const badge of owned.values()) badge.remove();
    owned.clear();
  };
  const validate = () => {
    try { if (!current()) stop(); } catch { stop(); }
  };
  const reconcile = (tile: Element) => {
    const existing = owned.get(tile);
    if (!tile.isConnected || !tile.matches(OFFLINE_TILE_SELECTOR) ||
        exactTileAppId(tile.getAttribute("data-id")) !== appId ||
        view.getComputedStyle(tile).position === "static") {
      existing?.remove(); owned.delete(tile); return;
    }
    if (existing?.parentElement === tile) return;
    existing?.remove();
    const badge = view.document.createElement("img");
    badge.setAttribute(OWN, "");
    badge.src = image;
    badge.alt = label;
    badge.title = `${label} — Steam report at check time`;
    badge.width = 72; badge.height = 32;
    badge.style.cssText = "position:absolute;top:6px;left:6px;width:72px;height:32px;pointer-events:none;z-index:2";
    tile.appendChild(badge);
    owned.set(tile, badge);
  };
  try {
    validate();
    if (!stopped) {
      const tiles = view.document.querySelectorAll(OFFLINE_TILE_SELECTOR);
      // Fail closed rather than process an unexpectedly large rendered surface.
      if (tiles.length > 256) stop();
      else for (const tile of Array.from(tiles)) reconcile(tile);
    }
    if (!stopped) {
      const Observer = (view as unknown as { MutationObserver: typeof MutationObserver }).MutationObserver;
      observer = new Observer((records) => {
        validate();
        if (stopped) return;
        try {
          if (records.length > 128) { stop(); return; }
          const candidates = new Set<Element>();
          const collect = (node: Node) => {
            if (node.nodeType !== 1) return;
            const element = node as Element;
            if (element.hasAttribute(OWN)) return;
            const parent = element.closest(OFFLINE_TILE_SELECTOR);
            if (parent) candidates.add(parent);
            for (const tile of Array.from(element.querySelectorAll(OFFLINE_TILE_SELECTOR))) {
              candidates.add(tile);
              if (candidates.size > 256) throw new Error();
            }
          };
          for (const record of records) {
            // Own insertion/removal is not a reason to rescan its tile subtree.
            if (record.type === "childList" && [...Array.from(record.addedNodes), ...Array.from(record.removedNodes)].every(
              node => node.nodeType === 1 && (node as Element).hasAttribute(OWN))) continue;
            collect(record.target);
            for (const node of Array.from(record.addedNodes)) collect(node);
          }
          // An ancestor can change role/class while the tile stays connected.
          // Revalidate the bounded set we own, not just newly matching selectors.
          for (const tile of owned.keys()) reconcile(tile);
          for (const tile of candidates) reconcile(tile);
        } catch { stop(); }
      });
      observer.observe(view.document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-id", "role", "class"] });
      timer = setTimeout(stop, 30000);
    }
  } catch { stop(); }
  return { stop, validate };
}

export function offlineLibraryWindow(): Window | null {
  try {
    const host = window as unknown as { DFL?: { getGamepadNavigationTrees?(): Array<{ m_window?: Window }> } };
    const trees = host.DFL?.getGamepadNavigationTrees?.();
    if (!Array.isArray(trees)) return null;
    const seen = new Set<Window>();
    for (const tree of trees.slice(0, 16)) {
      const view = tree.m_window;
      if (!view || seen.has(view)) continue;
      seen.add(view);
      if (view.document.querySelector(OFFLINE_TILE_SELECTOR)) return view;
    }
  } catch { /* Native Steam internals unavailable. */ }
  return null;
}
