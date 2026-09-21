import type { ElementType } from "react";
import { EgpuQuickActions, type EgpuActionPresentation, type EgpuQuickActionId } from "./egpu-actions-ui";

export type EgpuActionState = {
  available: boolean;
  pending?: boolean;
  detail?: string;
  warning?: boolean;
};

export type EgpuActionStateMap = Partial<Record<EgpuQuickActionId, EgpuActionState>>;

const labels: Record<EgpuQuickActionId, string> = {
  "switch-handheld": "Switch to Handheld",
  "safe-disconnect": "Safe Disconnect",
  resolution: "Resolution",
  "disconnect-sleep": "Sleep — Keep eGPU Connected",
  "disconnect-shutdown": "Safe Disconnect + Shutdown",
  status: "eGPU Status",
};

const defaultDetails: Record<EgpuQuickActionId, string> = {
  "switch-handheld": "Use the handheld display and keep the eGPU connected",
  "safe-disconnect": "Start the verified eGPU disconnect flow",
  resolution: "Change the active display target",
  "disconnect-sleep": "Normal sleep keeps the eGPU connected",
  "disconnect-shutdown": "Disconnect safely, then request shutdown",
  status: "View connection, display, render, and readiness status",
};

/**
 * Wiring-ready action panel shared by Quick Access and the eGPU tab.
 *
 * The runtime owns whether each action is available and what happens when it is
 * invoked. This component owns labels, ordering, equal card geometry, pending
 * presentation, and unavailable behavior.
 */
export function EgpuActionPanel({
  state,
  onAction,
  Button = "button",
}: {
  state?: EgpuActionStateMap;
  onAction?: (id: EgpuQuickActionId) => void | Promise<void>;
  Button?: ElementType;
}) {
  const order: readonly EgpuQuickActionId[] = [
    "switch-handheld",
    "safe-disconnect",
    "resolution",
    "status",
    "disconnect-sleep",
    "disconnect-shutdown",
  ];

  const actions: EgpuActionPresentation[] = order.map(id => {
    const current = state?.[id];
    const available = current?.available === true;
    const pending = current?.pending === true;
    const disabled = !available || pending || !onAction;
    return {
      id,
      label: labels[id],
      detail: current?.detail ?? defaultDetails[id],
      tone: current?.warning ? "warning" : "neutral",
      unavailable: !available,
      pending,
      control: <Button
        type="button"
        data-egpu-action-control={id}
        disabled={disabled}
        aria-busy={pending || undefined}
        aria-label={`${labels[id]}${pending ? ", working" : !available ? ", unavailable" : ""}`}
        onClick={() => { if (!disabled) void onAction(id); }}
      >
        {pending ? "Working…" : available ? "Open" : "Unavailable"}
      </Button>,
    };
  });

  return <EgpuQuickActions actions={actions}/>;
}
