function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

/** Backend owns admission. Unknown versions, contradictory flags and old RPCs hide the action. */
export function recoveryOffered(value: unknown): boolean {
  const status = record(value);
  return status?.schema_version === 1 && status.offered === true
    && status.availability === "offered" && status.code === "link_recovery.available"
    && Array.isArray(status.strategies)
    && status.strategies.some(value => {
      const strategy = record(value);
      return strategy?.strategy === "session_restart" && strategy.implemented === true;
    });
}

export function recoveryResult(value: unknown): string {
  const result = record(value);
  if (result?.schema_version !== 1) return "Check the connection status before taking another action.";
  if (result.ok === true && result.code === "link_recovery.trained") {
    return "The GPU is available. Checking the remaining connection steps…";
  }
  if (result.code === "link_recovery.game_running" || result.code === "link_recovery.game_state_unknown") {
    return "Recovery was not started. Close your game and check the connection again.";
  }
  if (result.code === "link_recovery.pci_complete") return "The GPU is already available. Checking the connection…";
  if (result.code === "link_recovery.link_absent") return "The GPU is still unavailable. Keep the eGPU connected and open troubleshooting.";
  return "Recovery could not be confirmed. Check Gaming Mode and the connection status.";
}
