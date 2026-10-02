import { assessOfflineConfidence, type OfflinePreparation, type OfflineConfidence } from "./offline-confidence.ts";
import { offlineTestMemory, type OfflineTestBinding } from "./offline-test-memory.ts";
import type { OfflineNativeSource } from "./offline-native-source";
import { offlineReportBadge, type OfflineBadge } from "./offline-badge-state.ts";

/** Account identity stays inside this private, session-only frontend boundary. */
export function offlineAccountScope(): string | null {
  try {
    const value = (window as unknown as { loginStore?: { m_strAccountName?: unknown } }).loginStore?.m_strAccountName;
    return typeof value === "string" && value.length > 0 && value.length <= 128 ? value : null;
  } catch { return null; }
}
export function offlineConfirmationBinding(preparation: OfflinePreparation, source: OfflineNativeSource, appId: number): OfflineTestBinding | null {
  const app = source.store.GetAppOverviewByAppID(appId); const account = offlineAccountScope();
  return app && account && preparation.buildId ? { appId, buildId: preparation.buildId, account, store: source.store, app } : null;
}
export function offlineConfidenceForGame(
  preparation: OfflinePreparation, source: OfflineNativeSource, appId: number, report: unknown, confirm: OfflineTestBinding | null = null,
): OfflineConfidence {
  const legacy = offlineReportBadge(report);
  if (!legacy) { offlineTestMemory.forget(appId); return {status: "unverified", label: "Unverified", reasons: ["The check is unavailable or the game context changed."], canConfirm: false}; }
  const app = source.store.GetAppOverviewByAppID(appId);
  const installed = app?.local_per_client_data?.installed;
  let singleplayer: unknown = null;
  try { singleplayer = app?.BHasStoreCategory?.(2); } catch { /* Missing cached category stays unknown. */ }
  const base = assessOfflineConfidence(preparation, installed, false, singleplayer);
  if (["needs_attention", "online_check_needed"].includes(String((report as {status?: unknown}).status)) && base.status !== "needs_preparation") {
    offlineTestMemory.forget(appId);
    return {status: "needs_preparation", label: "Needs preparation", reasons: ["Steam reports a preparation or authorization issue. Resolve it before relying on offline play."], canConfirm: false};
  }
  const account = offlineAccountScope();
  const binding: OfflineTestBinding | null = app && account && preparation.buildId
    ? { appId, buildId: preparation.buildId, account, store: source.store, app } : null;
  if (!base.canConfirm || !binding) { offlineTestMemory.forget(appId); return { ...base, canConfirm: false }; }
  if (confirm) {
    if (confirm.appId !== binding.appId || confirm.buildId !== binding.buildId || confirm.account !== binding.account ||
        confirm.store !== binding.store || confirm.app !== binding.app) {
      offlineTestMemory.forget(appId);
      return {status: "unverified", label: "Unverified", reasons: ["The game version or account changed. Check and test the current version again."], canConfirm: false};
    }
    offlineTestMemory.confirm(binding);
  }
  return assessOfflineConfidence(preparation, installed, offlineTestMemory.has(binding), singleplayer);
}
export function offlineConfidenceBadge(value: OfflineConfidence): OfflineBadge {
  return { asset: value.status === "needs_preparation" ? "offline-attention" :
    value.status === "likely_offline_ready" || value.status === "tested_offline" ? "offline-ready" : "offline-verify", label: value.label };
}
