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
  state: "active" | "inactive" | "unavailable" | "retired";
  blocking: boolean | null;
  attemptWarningAvailable: boolean;
  blockedAttemptCount: number;
  reason: PreflightObservation["kind"] | "required" | "verified_absent" | "observation_only";
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

// Admission must never execute a getter or borrow prototype data.
function ownData(value: unknown, key: string): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return undefined;
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  return descriptor && "value" in descriptor ? descriptor.value : undefined;
}

function snapshotAdmission(payload: unknown, nowMs: number, staleAfterMs: number): "supported-runtime" | "observation-only" | null {
  try {
    const snapshot = ownData(payload, "snapshot");
    const timestamp = ownData(snapshot, "observed_at");
    if (ownData(snapshot, "schema_version") !== 3 || typeof timestamp !== "string") return null;
    const age = nowMs - Date.parse(timestamp);
    if (!Number.isFinite(nowMs) || !Number.isFinite(staleAfterMs) || staleAfterMs <= 0 || !Number.isFinite(age) || age < 0 || age >= staleAfterMs) return null;
    const admission = ownData(payload, "runtime_admission");
    if (ownData(admission, "schema_version") !== 1) return null;
    const value = ownData(admission, "sleep_interceptor_admission");
    return value === "supported-runtime" || value === "observation-only" ? value : null;
  } catch { return null; }
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
  private readonly onRetired: () => void;
  private blockerRelease: (() => void) | null = null;
  private observerRelease: (() => void) | null = null;
  private observation: PreflightObservation = { kind: "loading" };
  private started = false;
  private stopped = false;
  private acquireFailed = false;
  private lifecycleError = "";
  private blockedAttemptCount = 0;
  private admission: "supported-runtime" | "observation-only" | null = null;
  private blockerUncertain = false;
  private cleanupUncertain = false;

  constructor(
    adapter: SteamSuspendAdapter | null,
    onBlockedAttempt: (warning: BlockedAttemptWarning) => void,
    onRetired: () => void = () => {},
  ) {
    this.adapter = adapter;
    this.onBlockedAttempt = onBlockedAttempt;
    this.onRetired = onRetired;
  }

  start(): SleepPreflightStatus {
    if (this.started || this.stopped || this.isRetired()) {
      return this.status();
    }
    this.started = true;

    // The blocker must exist before any asynchronous snapshot request starts.
    this.acquireBlocker();
    if (!this.stopped && !this.isRetired() && this.adapter && this.blockerRelease) {
      try {
        this.observerRelease = this.adapter.observeSuspendRequests(() => {
          if (!this.stopped && !this.isRetired() && this.blockerRelease) {
            this.blockedAttemptCount += 1;
            this.onBlockedAttempt(warningForBlockedAttempt(this.observation));
          }
        });
        if (this.stopped || this.isRetired()) this.releaseObserver();
      } catch (error) {
        this.lifecycleError = `Sleep is blocked, but the attempted-action warning is unavailable: ${messageFrom(error)}`;
      }
    }
    return this.status();
  }

  isRetired(): boolean {
    return this.admission === "observation-only";
  }

  // Host cleanup can complete after admission itself has returned. Record its
  // uncertainty without retrying any consumed native release/unpatch handle.
  reportWarningCleanupFailure(error: unknown): void {
    this.recordCleanupFailure(`Sleep warning cleanup failed: ${messageFrom(error)}`);
  }

  private recordCleanupFailure(message: string): void {
    this.cleanupUncertain = true;
    this.lifecycleError = this.lifecycleError ? `${this.lifecycleError}; ${message}` : message;
  }

  // Call only with a direct RPC reply after checking its current runtime generation.
  admitSnapshot(payload: unknown, nowMs: number, staleAfterMs: number): SleepPreflightStatus {
    if (this.stopped || this.admission !== null) return this.status();
    const admission = snapshotAdmission(payload, nowMs, staleAfterMs);
    if (admission === null) return this.status();
    this.admission = admission; // Terminal before any potentially reentrant cleanup.
    if (this.isRetired()) {
      try { this.onRetired(); }
      catch (error) { this.reportWarningCleanupFailure(error); }
      this.releaseObserver();
      this.releaseBlocker();
    }
    return this.status();
  }

  reconcile(observation: PreflightObservation): SleepPreflightStatus {
    if (this.stopped || this.isRetired()) {
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
    this.releaseObserver();
    this.releaseBlocker();
    return this.status();
  }

  private releaseObserver(): void {
    const releaseObserver = this.observerRelease;
    this.observerRelease = null;
    if (releaseObserver) {
      try {
        releaseObserver();
      } catch (error) {
        this.recordCleanupFailure(`Failed to remove the Steam sleep warning hook: ${messageFrom(error)}`);
      }
    }
  }

  status(): SleepPreflightStatus {
    const reason = this.isRetired() ? "observation_only" : this.observation.kind === "fresh"
      ? this.observation.guardRequired
        ? "required"
        : "verified_absent"
      : this.observation.kind;

    if (this.isRetired() && !this.acquireFailed && !this.cleanupUncertain) {
      return { state: "retired", blocking: false, attemptWarningAvailable: false,
        blockedAttemptCount: this.blockedAttemptCount, reason, error: "" };
    }

    if (!this.adapter || this.acquireFailed || this.cleanupUncertain) {
      return {
        state: "unavailable",
        blocking: this.blockerUncertain ? null : this.blockerRelease !== null,
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
      || this.isRetired()
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
      if (this.stopped || this.isRetired()) this.releaseBlocker();
    } catch (error) {
      // Do not retry in the same plugin lifecycle: a failed call may have
      // incremented Steam's blocker count without returning its release handle.
      this.acquireFailed = true;
      this.blockerUncertain = true;
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
      this.blockerUncertain = true;
      this.recordCleanupFailure(`Steam preflight release failed: ${messageFrom(error)}`);
    }
  }
}
