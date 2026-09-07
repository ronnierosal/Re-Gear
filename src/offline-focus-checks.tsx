import { callable, routerHook } from "@decky/api";
import { Router } from "@decky/ui";
import { offlineTestMemory } from "./offline-test-memory";
import { OfflineDetailsSession } from "./offline-details-session";
import { offlineConfidenceForGame, offlineConfidenceBadge, offlineAccountScope } from "./offline-confidence-session";
import { offlineReportBadge } from "./offline-badge-state";
import { offlineBadgeImages } from "./offline-readiness-badge";
import { offlineNativeSource } from "./offline-native-source";
import { attachOfflineTileBadge, exactTileElementAppId, OFFLINE_TILE_SELECTOR } from "./offline-tile-badge";

const classify = callable<[Record<string, number | boolean>], { schema_version?: unknown; status?: unknown; reason_codes?: unknown }>("classify_offline_details");
const SETTLE_MS = 450;

type CachedBadge = ReturnType<typeof offlineConfidenceBadge>;

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
  const session = new OfflineDetailsSession();
  let timer: ReturnType<typeof setTimeout> | undefined; let sequence = 0;
  let selectedTile: Element | null = null; let selectedId: number | null = null;
  let shown: ReturnType<typeof attachOfflineTileBadge> | undefined;
  const cancel = () => { sequence++; clearTimeout(timer); session.invalidate(); shown?.stop(); shown = undefined; };
  const context = (id: number, app: unknown, source: NonNullable<ReturnType<typeof offlineNativeSource>>) =>
    (window.appStore as unknown) === source.store && source.store.GetAppOverviewByAppID(id) === app && (app as { display_status?: number }).display_status !== 4 && Array.isArray(Router.RunningApps) && Router.RunningApps.length === 0;
  const focus = (event: FocusEvent) => {
    const target = event.target as Element | null; const tile = target?.closest?.(OFFLINE_TILE_SELECTOR);
    const id = tile ? exactTileElementAppId(tile) : null; const view = tile?.ownerDocument.defaultView;
    if (event.type !== "focusin" && tile === selectedTile && id === selectedId) return;
    cancel(); selectedTile = tile ?? null; selectedId = id;
    if (!tile || !view || id === null) return;
    const source = offlineNativeSource(); const app = source?.store.GetAppOverviewByAppID(id);
    if (!source || !app || app.display_status === 4 || !Array.isArray(Router.RunningApps) || Router.RunningApps.length) return;
    const account = offlineAccountScope();
    const displayStatus = app.display_status;
    const valid = () => offlineAccountScope() === account && app.display_status === displayStatus && context(id, app, source) && tile.isConnected &&
      tile.ownerDocument.activeElement?.closest(OFFLINE_TILE_SELECTOR) === tile && exactTileElementAppId(tile) === id;
    const show = (badge: CachedBadge) => { shown?.stop(); shown = attachOfflineTileBadge(view, id, offlineBadgeImages[badge.asset], badge.label, valid, tile, { image: offlineBadgeImages["offline-verify"], label: "Check unavailable" }, 65000); };
    // Re-read on settled selection so positive confidence cannot reuse an old build report.
    const request = sequence; const check = async () => {
      try {
        if (request !== sequence || !valid()) return; const report = await session.request(id, source.subscribe, valid);
        if (!report || request !== sequence) return; const result = await classify(report.details);
        if (!report.isValid() || request !== sequence || !valid()) return; if (!offlineReportBadge(result)) return;
        const badge = offlineConfidenceBadge(offlineConfidenceForGame(report.preparation, source, id, result));
        show(badge);
      } catch { /* Failed refresh expires to neutral; never retain a stale positive. */ }
      finally {
        if (request === sequence && valid()) timer = setTimeout(check, 60000);
      }
    };
    timer = setTimeout(check, SETTLE_MS);
  };
  const views = new Map<Window, MutationObserver>();
  const refresh = (view: Window) => {
    const active = view.document.activeElement;
    if (active?.closest?.(OFFLINE_TILE_SELECTOR) || selectedTile?.ownerDocument === view.document)
      focus({ target: active } as unknown as FocusEvent);
  };
  const syncViews = () => {
    for (const view of libraryWindows()) {
      if (!views.has(view)) {
        view.document.addEventListener("focusin", focus, true);
        const Observer = (view as unknown as { MutationObserver: typeof MutationObserver }).MutationObserver;
        // Controller tab changes and recycled artwork need not emit focusin.
        // Inspect only the active element; never enumerate library tiles.
        const observer = new Observer(() => refresh(view));
        observer.observe(view.document.body, { subtree: true, childList: true,
          attributes: true, attributeFilter: ["class", "role", "data-id", "src"] });
        views.set(view, observer);
      }
      refresh(view);
    }
  };
  // Steam may not expose navigation windows when Decky first loads. Route
  // patches provide an event-driven retry without a timer or document scan.
  const routePatch = <T,>(route: T): T => { syncViews(); return route; };
  const libraryPatch = routerHook.addPatch("/library", routePatch);
  const homePatch = routerHook.addPatch("/library/home", routePatch);
  const searchPatch = routerHook.addPatch("/search", routePatch);
  syncViews();
  return { stop() {
    cancel();
    offlineTestMemory.clear();
    routerHook.removePatch("/library", libraryPatch);
    routerHook.removePatch("/search", searchPatch);
    routerHook.removePatch("/library/home", homePatch);
    for (const [view, observer] of views) {
      view.document.removeEventListener("focusin", focus, true); observer.disconnect();
    }
    views.clear();
  } };
}
