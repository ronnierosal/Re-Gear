import type { SubscribeAppDetails } from "./steam-app-details-request.ts";

type Overview = { appid: number; app_type: number; display_name: string; display_status: number; BHasStoreCategory?(category: number): boolean; local_per_client_data?: { installed?: boolean } };
export type OfflineNativeSource = {
  store: { m_mapApps: { values(): IterableIterator<Overview> }; GetAppOverviewByAppID(id: number): Overview | null };
  subscribe: SubscribeAppDetails;
};

// Native interfaces are checked at use time: Steam updates may remove them.
export function offlineNativeSource(): OfflineNativeSource | null {
  const native = window as unknown as {
    appStore?: OfflineNativeSource["store"];
    SteamClient?: { Apps?: { RegisterForAppDetails?: SubscribeAppDetails } };
  };
  const store = native.appStore;
  const apps = native.SteamClient?.Apps;
  if (!store || typeof store.m_mapApps?.values !== "function" ||
      typeof store.GetAppOverviewByAppID !== "function" ||
      typeof apps?.RegisterForAppDetails !== "function") return null;
  return { store, subscribe: apps.RegisterForAppDetails.bind(apps) };
}

export function offlineGameChoices(source: OfflineNativeSource) {
  const games: Array<{ data: number; label: string }> = [];
  let examined = 0;
  for (const app of source.store.m_mapApps.values()) {
    if (++examined > 256) break;
    if (app.app_type !== 1 || app.local_per_client_data?.installed !== true ||
        !Number.isInteger(app.appid) || app.appid <= 0 || app.appid >= 2 ** 32 ||
        typeof app.display_name !== "string") continue;
    games.push({ data: app.appid, label: app.display_name.slice(0, 160) });
  }
  return games;
}
