import type { Tab } from "./model";

export const CUSTOMIZE_HOLD_MS = 550;

export type CustomizeGesture =
  | { kind: "swap"; tab: "quick" }
  | { kind: "move"; tab: Tab };

/**
 * Presentation/input helper for the Y-button contract.
 *
 * The Decky/native adapter owns the actual controller event mapping. This
 * helper only distinguishes a short press from a hold so native wiring does not
 * have to reproduce UI timing semantics.
 *
 * Quick Access:
 * - tap Y -> swap/customize available buttons
 * - hold Y -> move/reorder mode
 * Other tabs:
 * - tap Y -> no action
 * - hold Y -> move/reorder mode only
 */
export function createCustomizeGestureRecognizer({
  tab,
  now = () => Date.now(),
  holdMs = CUSTOMIZE_HOLD_MS,
  onGesture,
}: {
  tab: () => Tab;
  now?: () => number;
  holdMs?: number;
  onGesture: (gesture: CustomizeGesture) => void;
}) {
  let downAt: number | null = null;
  let activeTab: Tab | null = null;

  return {
    down() {
      if (downAt !== null) return;
      downAt = now();
      activeTab = tab();
    },
    up() {
      if (downAt === null || activeTab === null) return;
      const elapsed = Math.max(0, now() - downAt);
      const target = activeTab;
      downAt = null;
      activeTab = null;
      if (elapsed >= holdMs) onGesture({ kind: "move", tab: target });
      else if (target === "quick") onGesture({ kind: "swap", tab: "quick" });
    },
    cancel() {
      downAt = null;
      activeTab = null;
    },
    isPressed() { return downAt !== null; },
  };
}
