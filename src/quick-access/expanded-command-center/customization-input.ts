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
  schedule = (callback, delay) => setTimeout(callback, delay),
  unschedule = handle => clearTimeout(handle),
}: {
  tab: () => Tab;
  now?: () => number;
  holdMs?: number;
  onGesture: (gesture: CustomizeGesture) => void;
  schedule?: (callback:()=>void,delay:number)=>ReturnType<typeof setTimeout>;
  unschedule?: (handle:ReturnType<typeof setTimeout>)=>void;
}) {
  let downAt: number | null = null;
  let activeTab: Tab | null = null;
  let timer:ReturnType<typeof setTimeout>|undefined;
  let generation=0;
  let held=false;
  const clear=()=>{if(timer!==undefined)unschedule(timer);timer=undefined;generation++;};

  return {
    down() {
      if (downAt !== null) return;
      downAt = now();
      activeTab = tab();
      held=false;
      const current=++generation;
      timer=schedule(()=>{
        if(current!==generation||downAt===null||activeTab===null)return;
        held=true;timer=undefined;onGesture({kind:"move",tab:activeTab});
      },holdMs);
    },
    up() {
      if (downAt === null || activeTab === null) return;
      const elapsed = Math.max(0, now() - downAt);
      const target = activeTab;
      const wasHeld=held;
      clear();held=false;
      downAt = null;
      activeTab = null;
      if(wasHeld)return;
      if (elapsed >= holdMs) onGesture({ kind: "move", tab: target });
      else if (target === "quick") onGesture({ kind: "swap", tab: "quick" });
    },
    cancel() {
      clear();held=false;
      downAt = null;
      activeTab = null;
    },
    isPressed() { return downAt !== null; },
  };
}
