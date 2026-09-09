/** Shared health presentation for Command Center and the status pages: pure,
 * no React, no I/O, no requests.
 *
 * Three rules the approved design leans on, all of them easy to get wrong:
 *
 * 1. A healthy system is quiet. "Ready" earns no banner, no reason list and no
 *    colour. Space on a 268px first screen is scarce, and a reassurance nobody
 *    asked for costs the same room as a warning somebody needs.
 *
 * 2. Unknown is not healthy. Absent evidence renders as its own state, never
 *    collapsed into Ready and never inferred from placement. This repeats the
 *    repository rule that unknown state is not a capability claim.
 *
 * 3. Health is not placement, and it is not recovery workflow. The same payload
 *    carries blockers about where the device is docked and about Re-Gear's own
 *    recovery state; presenting them as one list makes a docking question look
 *    like a hardware fault. They are separated here so a caller can place them
 *    in the surfaces that own each.
 *
 * Reasons come from the existing sanitized `healthAttentionMessages` mapping,
 * so no raw or future backend code reaches a player.
 */

import type { SnapshotPayload } from "../backend";
import { healthAttentionMessages, healthStatusLabel } from "../health-ui";

/** How prominently a state should read. Never a colour name: the renderer owns
 * the palette, and a model that names colours cannot be re-themed. */
export type HealthTone = "quiet" | "progress" | "attention" | "unknown";

export type HealthPresentation = {
  /** Short label, e.g. "Ready". Reused verbatim as the text equivalent. */
  label: string;
  tone: HealthTone;
  /** True only for a healthy system: render nothing beyond the label. */
  quiet: boolean;
  /** Sanitized health reasons, excluding placement and workflow. Max 3. */
  reasons: string[];
  /** Reasons about where the device is docked, for the placement surface. */
  placementReasons: string[];
  /** Reasons about Re-Gear's own recovery state. */
  workflowReasons: string[];
  /** One line safe to announce or render without colour. */
  textEquivalent: string;
};

const PLACEMENT_BLOCKERS = new Set(["health.placement_degraded", "health.placement_unknown"]);
const WORKFLOW_BLOCKERS = new Set(["health.workflow_unknown"]);

function toneFor(state: string | undefined, loading: boolean): HealthTone {
  if (loading) return "unknown";
  switch (state) {
    case "ready": return "quiet";
    case "recovering": return "progress";
    case "degraded": return "attention";
    case "attention_required": return "attention";
    // Absent, unrecognised, or a state added after this build: not healthy.
    default: return "unknown";
  }
}

/** Reasons for one blocker subset, reusing the shared sanitized mapping. */
function reasonsFor(
  health: SnapshotPayload["health"] | undefined,
  keep: (blocker: string) => boolean,
): string[] {
  if (!health || !Array.isArray(health.blockers)) return [];
  const subset = health.blockers.filter(keep);
  if (subset.length === 0) return [];
  return healthAttentionMessages({ ...health, blockers: subset });
}

export function healthPresentation(
  health: SnapshotPayload["health"] | undefined,
  loading = false,
): HealthPresentation {
  const tone = toneFor(health?.state, loading);
  const quiet = tone === "quiet";
  // A healthy or still-loading system lists nothing: there is nothing to act on
  // yet, and a reason shown while loading would be evidence we do not have.
  const listing = !quiet && !loading;
  const label = healthStatusLabel(health, loading);
  return {
    label,
    tone,
    quiet,
    reasons: listing
      ? reasonsFor(health, (b) => !PLACEMENT_BLOCKERS.has(b) && !WORKFLOW_BLOCKERS.has(b))
      : [],
    placementReasons: listing ? reasonsFor(health, (b) => PLACEMENT_BLOCKERS.has(b)) : [],
    workflowReasons: listing ? reasonsFor(health, (b) => WORKFLOW_BLOCKERS.has(b)) : [],
    textEquivalent: label,
  };
}

/** True when the caller should surface something. Healthy and loading are
 * silent; unknown is not, because absent evidence is itself worth saying. */
export function healthNeedsSurface(presentation: HealthPresentation): boolean {
  return !presentation.quiet;
}
