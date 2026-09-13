import type { Tab } from "./model";
import type { UtilityId } from "./utility-layout";

/** UI-only navigation intents. Runtime owners may bind these to verified
 * platform adapters without changing Command Center layout or labels. */
export type CommandCenterNavigationIntent =
  | { kind: "open-tab"; tab: Tab }
  | { kind: "open-tile"; tab: Tab; tileId: string }
  | { kind: "adjust-utility"; id: "brightness" | "volume"; percent: number }
  | { kind: "quick-action"; id: "mic" | "wifi" | "overlay" | "recording" }
  | { kind: "customize" }
  | { kind: "back" }
  | { kind: "close" };

export const commandCenterButtonContract = {
  topTabs: ["quick", "performance", "egpu", "controllers", "settings"] as const satisfies readonly Tab[],
  utilities: ["brightness", "volume"] as const satisfies readonly UtilityId[],
  quickActions: ["mic", "wifi", "overlay", "recording"] as const satisfies readonly UtilityId[],
} as const;

/** Future runtime wiring should dispatch through one adapter seam instead of
 * embedding hardware/platform behavior in the visual components. */
export type CommandCenterNavigationDispatch = (intent: CommandCenterNavigationIntent) => void | Promise<void>;
