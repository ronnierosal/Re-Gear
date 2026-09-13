import type { Tab } from "./model";
import type { UtilityId } from "./utility-layout";
import type { EgpuQuickActionId } from "./egpu-actions-ui";

/** UI-only navigation intents. Runtime owners may bind these to verified
 * platform adapters without changing Command Center layout or labels. */
export type CommandCenterNavigationIntent =
  | { kind: "open-tab"; tab: Tab }
  | { kind: "open-tile"; tab: Tab; tileId: string }
  | { kind: "adjust-utility"; id: "brightness" | "volume"; percent: number }
  | { kind: "quick-action"; id: "mic" | "wifi" | "overlay" | "recording" }
  | { kind: "egpu-action"; id: EgpuQuickActionId }
  | { kind: "customize"; tab: "quick" }
  | { kind: "edit-quick-actions"; active: boolean }
  | { kind: "set-quick-action"; slot: number; id: UtilityId }
  | { kind: "move-mode"; tab: Tab; active: boolean; tileId?: string }
  | { kind: "move-tile"; tab: Tab; tileId: string; toIndex: number }
  | { kind: "back" }
  | { kind: "close" };

export const commandCenterButtonContract = {
  topTabs: ["quick", "performance", "egpu", "controllers", "settings"] as const satisfies readonly Tab[],
  utilities: ["brightness", "volume"] as const satisfies readonly UtilityId[],
  quickActions: ["mic", "wifi", "overlay", "recording"] as const satisfies readonly UtilityId[],
  egpuActions: ["switch-handheld", "safe-disconnect", "resolution", "disconnect-sleep", "disconnect-shutdown", "status"] as const satisfies readonly EgpuQuickActionId[],
  directActions: {
    /** One A press starts the existing guarded Safe Disconnect workflow.
     * Do not open an intermediate detail page or second confirmation screen.
     * Runtime may still refuse/abort if safety gates are not satisfied. */
    safeDisconnect: "single-press",
  },
  customize: {
    quickTapY: "swap-main-actions",
    holdY: "move-mode",
    otherTabsTapY: "none",
    otherTabsHoldY: "move-mode",
    quickTapX: "edit-right-rail",
    otherTabsTapX: "none",
  },
} as const;

/** Runtime wiring should dispatch through one adapter seam instead of embedding
 * persistence or feature logic in the visual components. */
export type CommandCenterNavigationDispatch = (intent: CommandCenterNavigationIntent) => void | Promise<void>;
