import { callable } from "@decky/api";
import { Router } from "@decky/ui";
import { useEffect, useRef } from "react";
import { OfflineDetailsSession } from "./offline-details-session";
import { offlineReportBadge } from "./offline-badge-state";
import { offlineBadgeImages } from "./offline-readiness-badge";
import { offlineNativeSource } from "./offline-native-source";
import { attachOfflineTileBadge, exactTileAppId, OFFLINE_TILE_SELECTOR } from "./offline-tile-badge";

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

/** Invisible, event-driven selected-game check. It never scans or polls the library. */
export function OfflineFocusChecks({ gameState }: { gameState: string }) {
  const state = useRef(gameState);
  state.current = gameState;
  useEffect(() => {
    const session = new OfflineDetailsSession();
    const cache = new Map<number, CachedBadge>();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let sequence = 0;
    let shown: ReturnType<typeof attachOfflineTileBadge> | undefined;
    const cancel = () => { sequence++; clearTimeout(timer); session.invalidate(); shown?.stop(); shown = undefined; };
    const context = (appId: number, app: unknown, source: NonNullable<ReturnType<typeof offlineNativeSource>>) =>
      state.current === "idle" && (window.appStore as unknown) === source.store &&
      source.store.GetAppOverviewByAppID(appId) === app &&
      Array.isArray(Router.RunningApps) && Router.RunningApps.length === 0;
    const show = (view: Window, tile: Element, appId: number, badge: CachedBadge, valid: () => boolean) => {
      shown?.stop();
      shown = attachOfflineTileBadge(view, appId, offlineBadgeImages[badge.asset], badge.label, valid, tile);
    };
    const focus = (event: FocusEvent) => {
      cancel();
      if (state.current !== "idle") return;
      const target = event.target as Element | null;
      const tile = target?.closest?.(OFFLINE_TILE_SELECTOR);
      const appId = tile ? exactTileAppId(tile.getAttribute("data-id")) : null;
      const view = tile?.ownerDocument.defaultView;
      if (!tile || !view || appId === null) return;
      const source = offlineNativeSource();
      const app = source?.store.GetAppOverviewByAppID(appId);
      if (!source || !app || app.display_status === 4) return;
      const valid = () => context(appId, app, source) && tile.isConnected && exactTileAppId(tile.getAttribute("data-id")) === appId;
      const cached = cache.get(appId);
      if (cached && Date.now() - cached.at < CACHE_MS && valid()) { show(view, tile, appId, cached, valid); return; }
      const request = sequence;
      timer = setTimeout(async () => {
        if (request !== sequence || !valid()) return;
        const report = await session.request(appId, source.subscribe, valid);
        if (!report || request !== sequence) return;
        const result = await classify(report.details);
        if (!report.isValid() || request !== sequence || !valid()) return;
        const badge = offlineReportBadge(result);
        if (!badge) return;
        const saved: CachedBadge = { ...badge, at: Date.now() };
        cache.delete(appId); cache.set(appId, saved);
        while (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value!);
        show(view, tile, appId, saved, valid);
      }, SETTLE_MS);
    };
    const views = libraryWindows();
    for (const view of views) view.document.addEventListener("focusin", focus, true);
    return () => {
      cancel();
      for (const view of views) view.document.removeEventListener("focusin", focus, true);
    };
  }, []);
  return null;
}
