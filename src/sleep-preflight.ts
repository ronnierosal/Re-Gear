export type PreflightObservation =
  | { kind: "loading" | "stale" | "unavailable" }
  | {
      kind: "fresh";
      guardRequired: boolean;
      guardConfidence: "unknown" | "observed" | "verified";
      gameState: string;
      gameUsesEgpu: boolean;
    };

export interface BlockedAttemptWarning {
  kind: "game" | "standard" | "unknown";
  title: string;
  body: string;
  critical: boolean;
}

export interface SteamSuspendAdapter {
  acquireBlocker(): () => void;
  observeSuspendRequests(handler: () => void): () => void;
}

export interface SleepPreflightStatus {
  state: "active" | "inactive" | "unavailable";
  blocking: boolean;
  attemptWarningAvailable: boolean;
  blockedAttemptCount: number;
  reason: PreflightObservation["kind"] | "required" | "verified_absent";
  error: string;
}

export interface SnapshotPreflightEvidence {
  schemaVersion: number;
  observedAt: string;
  guardRequired: boolean;
  guardConfidence: "unknown" | "observed" | "verified";
  gameState: string;
  gameUsesEgpu: boolean;
}

function messageFrom(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Unknown Steam preflight error";
}

export function requiresPreflightBlocker(observation: PreflightObservation): boolean {
  return !(
    observation.kind === "fresh"
    && observation.guardRequired === false
    && observation.guardConfidence === "verified"
  );
}

export function observationFromSnapshotEvidence(
  evidence: SnapshotPreflightEvidence,
  nowMs: number,
  staleAfterMs: number,
): PreflightObservation {
  const observedAtMs = Date.parse(evidence.observedAt);
  const ageMs = nowMs - observedAtMs;
  if (
    evidence.schemaVersion !== 3
    || !Number.isFinite(observedAtMs)
    || ageMs > staleAfterMs
    || ageMs < -staleAfterMs
  ) {
    return { kind: "stale" };
  }
  return {
    kind: "fresh",
    guardRequired: evidence.guardRequired,
    guardConfidence: evidence.guardConfidence,
    gameState: evidence.gameState,
    gameUsesEgpu: evidence.gameUsesEgpu,
  };
}

export function warningForBlockedAttempt(
  observation: PreflightObservation,
): BlockedAttemptWarning {
  if (
    observation.kind === "fresh"
    && observation.guardRequired
    && observation.gameUsesEgpu
  ) {
    return {
      kind: "game",
      title: "Sleep blocked — game is using the eGPU",
      body: "Close the game and restore Portable before disconnecting the eGPU. The sleep request was not started.",
      critical: true,
    };
  }

  if (
    observation.kind === "fresh"
    && observation.guardRequired
    && observation.gameState !== "unknown"
  ) {
    return {
      kind: "standard",
      title: "Sleep blocked while an eGPU is attached",
      body: "This eGPU is known to wake the handheld immediately. Restore Portable and shut down before disconnecting it.",
      critical: false,
    };
  }

  return {
    kind: "unknown",
    title: "Sleep blocked — safety state is unknown",
    body: "Re-Gear could not verify that the eGPU is safely absent, so the sleep request was not started.",
    critical: true,
  };
}

export class SleepPreflightCoordinator {
  private readonly adapter: SteamSuspendAdapter | null;
  private readonly onBlockedAttempt: (warning: BlockedAttemptWarning) => void;
  private blockerRelease: (() => void) | null = null;
  private observerRelease: (() => void) | null = null;
  private observation: PreflightObservation = { kind: "loading" };
  private started = false;
  private stopped = false;
  private acquireFailed = false;
  private lifecycleError = "";
  private blockedAttemptCount = 0;

  constructor(
    adapter: SteamSuspendAdapter | null,
    onBlockedAttempt: (warning: BlockedAttemptWarning) => void,
  ) {
    this.adapter = adapter;
    this.onBlockedAttempt = onBlockedAttempt;
  }

  start(): SleepPreflightStatus {
    if (this.started || this.stopped) {
      return this.status();
    }
    this.started = true;

    // The blocker must exist before any asynchronous snapshot request starts.
    this.acquireBlocker();
    if (this.adapter && this.blockerRelease) {
      try {
        this.observerRelease = this.adapter.observeSuspendRequests(() => {
          if (this.blockerRelease) {
            this.blockedAttemptCount += 1;
            this.onBlockedAttempt(warningForBlockedAttempt(this.observation));
          }
        });
      } catch (error) {
        this.lifecycleError = `Sleep is blocked, but the attempted-action warning is unavailable: ${messageFrom(error)}`;
      }
    }
    return this.status();
  }

  reconcile(observation: PreflightObservation): SleepPreflightStatus {
    if (this.stopped) {
      return this.status();
    }
    this.observation = observation;
    if (requiresPreflightBlocker(observation)) {
      this.acquireBlocker();
    } else {
      this.releaseBlocker();
    }
    return this.status();
  }

  stop(): SleepPreflightStatus {
    if (this.stopped) {
      return this.status();
    }
    this.stopped = true;

    const releaseObserver = this.observerRelease;
    this.observerRelease = null;
    if (releaseObserver) {
      try {
        releaseObserver();
      } catch (error) {
        this.lifecycleError = `Failed to remove the Steam sleep warning hook: ${messageFrom(error)}`;
      }
    }
    this.releaseBlocker();
    return this.status();
  }

  status(): SleepPreflightStatus {
    const reason = this.observation.kind === "fresh"
      ? this.observation.guardRequired
        ? "required"
        : "verified_absent"
      : this.observation.kind;

    if (!this.adapter || this.acquireFailed) {
      return {
        state: "unavailable",
        blocking: false,
        attemptWarningAvailable: false,
        blockedAttemptCount: this.blockedAttemptCount,
        reason,
        error: this.lifecycleError || "Steam's native suspend blocker could not be resolved.",
      };
    }
    if (this.blockerRelease) {
      return {
        state: "active",
        blocking: true,
        attemptWarningAvailable: this.observerRelease !== null,
        blockedAttemptCount: this.blockedAttemptCount,
        reason,
        error: this.lifecycleError,
      };
    }
    return {
      state: "inactive",
      blocking: false,
      attemptWarningAvailable: false,
      blockedAttemptCount: this.blockedAttemptCount,
      reason,
      error: this.lifecycleError,
    };
  }

  private acquireBlocker(): void {
    if (
      !this.started
      || this.stopped
      || !this.adapter
      || this.blockerRelease
      || this.acquireFailed
    ) {
      return;
    }
    try {
      const release = this.adapter.acquireBlocker();
      if (typeof release !== "function") {
        throw new Error("Steam did not return a suspend-blocker release callback");
      }
      this.blockerRelease = release;
    } catch (error) {
      // Do not retry in the same plugin lifecycle: a failed call may have
      // incremented Steam's blocker count without returning its release handle.
      this.acquireFailed = true;
      this.lifecycleError = `Steam preflight acquisition failed: ${messageFrom(error)}`;
    }
  }

  private releaseBlocker(): void {
    const release = this.blockerRelease;
    this.blockerRelease = null;
    if (!release) {
      return;
    }
    try {
      release();
    } catch (error) {
      this.acquireFailed = true;
      this.lifecycleError = `Steam preflight release failed: ${messageFrom(error)}`;
    }
  }
}
