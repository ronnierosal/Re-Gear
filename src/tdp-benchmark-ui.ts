import type { TdpBenchmarkStatus } from "./backend";

const code = (value: unknown): value is string => typeof value === "string" && /^(auto_tdp|tdp)\.[a-z_]{1,80}$/.test(value);
const integer = (value: unknown, maximum: number): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= maximum;

export function sanitizeTdpBenchmark(value: unknown): TdpBenchmarkStatus | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (v.schema_version !== 1 || typeof v.running !== "boolean" || typeof v.cancelling !== "boolean" || (v.cancelling && !v.running) || !code(v.code)) return null;
  if (v.result !== null) {
    if (!v.result || typeof v.result !== "object") return null;
    const r = v.result as Record<string, unknown>;
    if (!code(r.code) || !integer(r.attempts, 30) || !integer(r.usable_samples, r.attempts) || !integer(r.consecutive_samples, r.usable_samples)
        || !integer(r.elapsed_ms, Number.MAX_SAFE_INTEGER) || !integer(r.interval_ms, 2000) || r.interval_ms < 1000
        || (r.maximum_collection_and_revalidation_ms !== null && !integer(r.maximum_collection_and_revalidation_ms, Number.MAX_SAFE_INTEGER))) return null;
  }
  return v as unknown as TdpBenchmarkStatus;
}

export function tdpBenchmarkMessage(status: TdpBenchmarkStatus | null): string {
  if (!status) return "Benchmark status unavailable. Refresh to check again.";
  if (status.cancelling) return "Cancelling after the current read finishes…";
  if (status.running) return "Measuring frame and sensor collection…";
  return ({
    "auto_tdp.benchmark_idle": "No benchmark has run in this session.",
    "auto_tdp.benchmark_within_budget": "This run met the collection time budget. Auto TDP has not been enabled.",
    "auto_tdp.benchmark_budget_exceeded": "Collection exceeded the time budget for Auto TDP.",
    "auto_tdp.benchmark_cancelled": "Benchmark cancelled.",
    "auto_tdp.benchmark_stop_auto_first": "Stop Auto TDP before running a benchmark.",
    "auto_tdp.benchmark_context_changed": "The game, power source or device context changed. Run again when stable.",
    "auto_tdp.benchmark_samples_insufficient": "Not enough usable frame samples. Check the running game and try again.",
    "auto_tdp.benchmark_context_unavailable": "Game, sensor or device evidence is unavailable. Check readiness and try again.",
    "auto_tdp.benchmark_time_limit": "The benchmark reached its time limit.",
    "auto_tdp.configuration_missing": "Device configuration is required before measurement.",
    "auto_tdp.configuration_invalid": "Device configuration needs correction before measurement.",
    "auto_tdp.game_or_render_unverified": "A verified game running on the internal GPU is required.",
    "tdp.disabled": "Enable manual power control before measurement.",
    "tdp.busy": "Power control is busy. Refresh and try again after it finishes.",
    "tdp.closing": "Power control is shutting down.",
  } as Record<string, string>)[status.code] ?? "Benchmark unavailable. Check power control readiness and refresh.";
}
