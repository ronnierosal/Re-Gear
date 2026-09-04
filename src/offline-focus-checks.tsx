import { callable, routerHook } from "@decky/api";
import { Router } from "@decky/ui";
import { OfflineDetailsSession } from "./offline-details-session";
import { offlineReportBadge } from "./offline-badge-state";
import { offlineBadgeImages } from "./offline-readiness-badge";
import { offlineNativeSource } from "./offline-native-source";
import { attachOfflineTileBadge, exactTileElementAppId, OFFLINE_TILE_SELECTOR } from "./offline-tile-badge";

const classify = callable<[Record<string, number | boolean>], { schema_version?: unknown; status?: unknown; reason_codes?: unknown }>("classify_offline_details");
const SETTLE_MS = 450;
const CACHE_MS = 5 * 60 * 1000;
const CACHE_LIMIT = 32;

type CachedBadge = { at: number; asset: "offline-attention" | "offline-verify"; label: string };

function libraryWindows(): Window[] {
  try {
    const host = window as unknown as { DFL?: { getGamepadNavigationTrees?(): Array<{ m_window?: Window }> } };
    const trees = host.DFL?.getGamepadNavigationTrees?.();
    if (!Array.isArray(trees)) return [];
    return [...new Set(trees.slice(0, 16).map(tree => tree.m_window).filter((view): view is Window => !!view))];
  } catch { return []; }
}

/** Start once with the plugin, independently of Quick Access rendering. */
export function startOfflineFocusChecks(): { stop(): void } {
  const session = new OfflineDetailsSession(); const cache = new Map<number, CachedBadge>();
  let timer: ReturnType<typeof setTimeout> | undefined; let sequence = 0;
  let shown: ReturnType<typeof attachOfflineTileBadge> | undefined;
  const cancel = () => { sequence++; clearTimeout(timer); session.invalidate(); shown?.stop(); shown = undefined; };
  const context = (id: number, app: unknown, source: NonNullable<ReturnType<typeof offlineNativeSource>>) =>
    (window.appStore as unknown) === source.store && source.store.GetAppOverviewByAppID(id) === app && (app as { display_status?: number }).display_status !== 4 && Array.isArray(Router.RunningApps) && Router.RunningApps.length === 0;
  const focus = (event: FocusEvent) => {
    cancel(); const target = event.target as Element | null; const tile = target?.closest?.(OFFLINE_TILE_SELECTOR);
    const id = tile ? exactTileElementAppId(tile) : null; const view = tile?.ownerDocument.defaultView;
    if (!tile || !view || id === null) return;
    const source = offlineNativeSource(); const app = source?.store.GetAppOverviewByAppID(id);
    if (!source || !app || app.display_status === 4 || !Array.isArray(Router.RunningApps) || Router.RunningApps.length) return;
    const valid = () => context(id, app, source) && tile.isConnected &&
      tile.ownerDocument.activeElement?.closest(OFFLINE_TILE_SELECTOR) === tile && exactTileElementAppId(tile) === id;
    const show = (badge: CachedBadge) => { shown?.stop(); shown = attachOfflineTileBadge(view, id, offlineBadgeImages[badge.asset], badge.label, valid, tile); };
    const cached = cache.get(id); if (cached && Date.now() - cached.at < CACHE_MS && valid()) { show(cached); return; }
    const request = sequence; timer = setTimeout(async () => {
      try {
        if (request !== sequence || !valid()) return; const report = await session.request(id, source.subscribe, valid);
        if (!report || request !== sequence) return; const result = await classify(report.details);
        if (!report.isValid() || request !== sequence || !valid()) return; const badge = offlineReportBadge(result); if (!badge) return;
        const saved: CachedBadge = { ...badge, at: Date.now() }; cache.delete(id); cache.set(id, saved);
        while (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value!); show(saved);
      } catch { /* Steam/Decky may disappear during a request; discard this result. */ }
    }, SETTLE_MS);
  };
  const views = new Set<Window>();
  const syncViews = () => {
    for (const view of libraryWindows()) {
      if (views.has(view)) continue;
      view.document.addEventListener("focusin", focus, true);
      views.add(view);
      const active = view.document.activeElement;
      if (active?.closest?.(OFFLINE_TILE_SELECTOR)) {
        focus({ target: active } as unknown as FocusEvent);
      }
    }
  };
  // Steam may not expose navigation windows when Decky first loads. Route
  // patches provide an event-driven retry without a timer or document scan.
  const routePatch = <T,>(route: T): T => { syncViews(); return route; };
  const libraryPatch = routerHook.addPatch("/library", routePatch);
  const searchPatch = routerHook.addPatch("/search", routePatch);
  syncViews();
  return { stop() {
    cancel();
    routerHook.removePatch("/library", libraryPatch);
    routerHook.removePatch("/search", searchPatch);
    for (const view of views) view.document.removeEventListener("focusin", focus, true);
    views.clear();
  } };
}
