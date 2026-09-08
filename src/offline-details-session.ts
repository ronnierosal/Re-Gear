import { projectOfflinePreparation, type OfflinePreparation } from "./offline-confidence.ts";
import { requestSteamAppDetails, type SubscribeAppDetails } from "./steam-app-details-request.ts";

// Only fields consumed by the Python projector may cross the private reader seam.
export function minimizeOfflineDetails(value: unknown): Record<string, number | boolean> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  const result: Record<string, number | boolean> = {};
  for (const key of ["iInstallFolder", "eDisplayStatus", "eCloudStatus"]) {
    const field = source[key];
    if (typeof field === "number" && Number.isSafeInteger(field)) result[key] = field;
  }
  for (const key of ["bCloudAvailable", "bCloudEnabledForAccount", "bCloudEnabledForApp", "bIsThirdPartyUpdater"]) {
    if (typeof source[key] === "boolean") result[key] = source[key];
  }
  return result;
}

/** Private view lifetime; invalidate on selection, Steam session, or game-state changes.
 * No polling or persistence. Supplies minimized RPC fields and private preparation clues.
 */
export class OfflineDetailsSession {
  private generation = 0;
  private pending?: AbortController;

  invalidate(): void {
    this.generation++;
    this.pending?.abort();
    this.pending = undefined;
  }

  async request(
    appId: number,
    subscribe: SubscribeAppDetails,
    isCurrentAndIdle: () => boolean,
    now: () => number = () => performance.now(),
  ): Promise<{ details: Record<string, number | boolean>; preparation: OfflinePreparation; isValid(): boolean } | null> {
    this.invalidate();
    const generation = this.generation;
    const controller = new AbortController();
    this.pending = controller;
    try {
      const started = now();
      if (!Number.isFinite(started) || !isCurrentAndIdle()) return null;
      const raw = await requestSteamAppDetails(appId, subscribe, controller.signal);
      const received = now();
      if (!Number.isFinite(received) || received < started || received - started > 1000) return null;
      let expired = false;
      const valid = () => {
        try {
          const current = now();
          const accepted = !expired && generation === this.generation && !controller.signal.aborted &&
            Number.isFinite(current) && current >= received && current - received < 1000 &&
            isCurrentAndIdle();
          if (!accepted) expired = true;
          return accepted;
        } catch { expired = true; return false; }
      };
      if (!valid()) return null;
      const details = minimizeOfflineDetails(raw);
      return details ? { details, preparation: projectOfflinePreparation(raw), isValid: valid } : null;
    } catch {
      return null;
    } finally {
      if (this.pending === controller) this.pending = undefined;
    }
  }
}
