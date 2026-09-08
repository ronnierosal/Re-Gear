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
const REFRESH_MS = 60000;
const RETRY_MS = 5000;

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
  let selectionContextMatches: (() => boolean) | undefined;
  const cancel = () => { sequence++; clearTimeout(timer); session.invalidate(); shown?.stop(); shown = undefined; };
  const context = (id: number, app: unknown, source: NonNullable<ReturnType<typeof offlineNativeSource>>) =>
    (window.appStore as unknown) === source.store && source.store.GetAppOverviewByAppID(id) === app && (app as { display_status?: number }).display_status !== 4 && Array.isArray(Router.RunningApps) && Router.RunningApps.length === 0;
  const focus = (event: FocusEvent) => {
    const target = event.target as Element | null; const tile = target?.closest?.(OFFLINE_TILE_SELECTOR);
    const id = tile ? exactTileElementAppId(tile) : null; const view = tile?.ownerDocument.defaultView;
    if (event.type !== "focusin" && tile === selectedTile && id === selectedId && selectionContextMatches?.()) return;
    cancel(); selectedTile = tile ?? null; selectedId = id;
    selectionContextMatches = undefined;
    if (!tile || !view || id === null) return;
    const request = sequence;
    const selected = () => request === sequence && tile.isConnected &&
      tile.ownerDocument.activeElement?.closest(OFFLINE_TILE_SELECTOR) === tile && exactTileElementAppId(tile) === id;
    const capture = () => {
      const source = offlineNativeSource(); const app = source?.store.GetAppOverviewByAppID(id);
      const account = offlineAccountScope(); const displayStatus = app?.display_status;
      const idle = Array.isArray(Router.RunningApps) && Router.RunningApps.length === 0;
      selectionContextMatches = () => offlineAccountScope() === account &&
        (window.appStore as unknown) === source?.store && source?.store.GetAppOverviewByAppID(id) === app &&
        app?.display_status === displayStatus && idle === (Array.isArray(Router.RunningApps) && Router.RunningApps.length === 0);
      return { source, app, matches: selectionContextMatches };
    };
    capture();
    let failures = 0;
    // Re-read on settled selection so positive confidence cannot reuse an old build report.
    const check = async () => {
      let delay = REFRESH_MS;
      try {
        if (!selected()) return;
        shown?.validate();
        const { source, app, matches } = capture();
        if (!source || !app || !context(id, app, source)) { session.invalidate(); return; }
        // Bind each attempt to its own observation, not the original focus state.
        // Once invalidated, a late response cannot become valid again.
        let invalid = false;
        const valid = () => { invalid ||= !selected() || !matches() || !context(id, app, source); return !invalid; };
        delay = ++failures <= 2 ? RETRY_MS : REFRESH_MS;
        const report = await session.request(id, source.subscribe, valid);
        if (!report || !report.isValid() || !valid()) return;
        const result = await classify(report.details);
        if (!report.isValid() || request !== sequence || !valid()) return; if (!offlineReportBadge(result)) return;
        const badge = offlineConfidenceBadge(offlineConfidenceForGame(report.preparation, source, id, result));
        shown?.stop();
        shown = attachOfflineTileBadge(view, id, offlineBadgeImages[badge.asset], badge.label, valid, tile, { image: offlineBadgeImages["offline-verify"], label: "Check unavailable" }, 65000);
        failures = 0; delay = REFRESH_MS;
      } catch { /* Failed refresh expires to neutral; never retain a stale positive. */ }
      finally {
        // Keep the existing cadence alive while this exact tile is selected,
        // including gameplay/unknown state. Ineligible ticks make no requests.
        if (selected()) timer = setTimeout(check, delay);
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
