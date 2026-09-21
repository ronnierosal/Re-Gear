import type { ReactNode } from "react";
import { CommandCenterIcon, type CommandCenterIconId } from "../command-center-icons";
import { CommandActionRow, CommandDetailSurface, CommandNotice, CommandSection, CommandStatusRow, type DetailTone } from "./detail-ui";
import { ReGearPopup } from "./popup-ui";

export const egpuQuickActionIds = [
  "switch-handheld",
  "safe-disconnect",
  "resolution",
  "disconnect-sleep",
  "disconnect-shutdown",
  "status",
] as const;
export type EgpuQuickActionId = typeof egpuQuickActionIds[number];

export type EgpuActionPresentation = {
  id: EgpuQuickActionId;
  label: string;
  detail?: string;
  tone?: DetailTone;
  unavailable?: boolean;
  pending?: boolean;
  control?: ReactNode;
};

const actionIcons: Record<EgpuQuickActionId, CommandCenterIconId> = {
  "switch-handheld": "display",
  "safe-disconnect": "safe-disconnect",
  resolution: "refresh-rate",
  "disconnect-sleep": "safe-disconnect",
  "disconnect-shutdown": "safe-disconnect",
  status: "egpu",
};

const egpuActionStyles = `
[data-egpu-action-grid]{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;container-type:inline-size}
[data-egpu-action-card]{min-width:0;min-height:76px;padding:8px 9px;border-radius:10px;display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:minmax(0,1fr) auto;column-gap:8px;row-gap:6px;align-content:stretch;background:#0b2230;border:1px solid #315c75;box-shadow:inset 0 1px 0 #ffffff08}
[data-egpu-action-card][data-tone=warning]{border-color:#80672f;background:linear-gradient(145deg,#2b281a,#10202b 62%)}
[data-egpu-action-card][data-unavailable=true]{background:#0b1821;opacity:.62}
[data-egpu-action-icon]{grid-row:1;grid-column:1;display:grid;place-items:center;width:30px;height:30px;border-radius:8px;border:1px solid #315c75;background:#0a2232;color:#c9ecff}
[data-egpu-action-copy]{grid-row:1;grid-column:2;min-width:0}
[data-egpu-action-card] strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:10.5px;line-height:1.18;color:#e7f4fb;white-space:normal}
[data-egpu-action-card] [data-egpu-action-detail]{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-top:2px;font-size:9px;line-height:1.22;color:#8fb3cc}
[data-egpu-action-control]{grid-column:1/-1;grid-row:2;min-width:0}
[data-egpu-action-control]>button,[data-egpu-action-control] button{width:100%;min-height:29px;margin:0;padding:5px 8px;border:1px solid #417895;border-radius:7px;background:#12364b;color:#edf8ff;font:inherit;font-size:9.5px;font-weight:650;text-align:center;white-space:normal;line-height:1.15}
[data-egpu-action-control] button:hover{border-color:#63b7d9;background:#17455d}
[data-egpu-action-control] button:focus,[data-egpu-action-control] button:focus-visible,[data-egpu-action-control] button.gpfocus{outline:2px solid #39d8ff;outline-offset:-2px;background:#17455d!important}
[data-egpu-action-control] button:disabled{opacity:.55;cursor:default}
@container (max-width:520px){[data-egpu-action-grid]{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}[data-egpu-action-card]{min-height:70px;padding:7px 8px}}
@container (max-width:300px){[data-egpu-action-grid]{grid-template-columns:1fr}[data-egpu-action-card]{min-height:64px}}
@media(max-height:520px){[data-egpu-action-grid]{gap:6px}[data-egpu-action-card]{min-height:62px;padding:6px 7px;column-gap:6px}[data-egpu-action-icon]{width:26px;height:26px}[data-egpu-action-card] strong{font-size:9.5px}[data-egpu-action-card] [data-egpu-action-detail]{font-size:8px}[data-egpu-action-control]>button,[data-egpu-action-control] button{min-height:25px;padding:4px 6px;font-size:8.5px}}
`;

/**
 * Shared eGPU action surface for the eGPU module and Quick Access tab.
 * Runtime owners supply controls; this component does not dispatch actions.
 */
export function EgpuQuickActions({ actions }: { actions: readonly EgpuActionPresentation[] }) {
  return <CommandSection title="eGPU actions" hint="The same verified actions may be surfaced in Quick Access and the eGPU module without changing their meaning.">
    <style>{egpuActionStyles}</style>
    <div data-egpu-action-grid>
      {actions.map(action => <div key={action.id} data-egpu-action-card data-egpu-action-id={action.id} data-tone={action.tone ?? "neutral"} data-unavailable={action.unavailable ? "true" : undefined} aria-busy={action.pending || undefined}>
        <span data-egpu-action-icon><CommandCenterIcon id={actionIcons[action.id]} size={20}/></span>
        <div data-egpu-action-copy>
          <strong>{action.label}</strong>
          {action.detail && <span data-egpu-action-detail>{action.detail}</span>}
        </div>
        {action.control && <div data-egpu-action-control>{action.control}</div>}
      </div>)}
    </div>
  </CommandSection>;
}

/** USB authorization is explicit and device-scoped; the UI never invents permanent trust. */
export function UsbAuthorizationPopup({ deviceLabel, detail, authorizeAction, notNowAction, detailsAction }: {
  deviceLabel: string;
  detail?: string;
  authorizeAction?: ReactNode;
  notNowAction?: ReactNode;
  detailsAction?: ReactNode;
}) {
  return <ReGearPopup title="USB authorization required" status={deviceLabel} tone="warning" footer={<>{notNowAction}{detailsAction}{authorizeAction}</>}>
    <CommandDetailSurface>
      <CommandNotice tone="warning" title="Allow this USB device?">
        {detail ?? "Re-Gear detected a USB device that requires authorization before the eGPU workflow can continue."}
      </CommandNotice>
      <CommandSection title="What happens next">
        <CommandStatusRow label="Authorize" value="Continue this connection" tone="active" detail="Runtime decides the exact authorization scope and verifies the result."/>
        <CommandStatusRow label="Not now" value="Leave blocked" tone="neutral" detail="The connection remains incomplete; Re-Gear does not silently trust the device."/>
      </CommandSection>
    </CommandDetailSurface>
  </ReGearPopup>;
}

/**
 * Sleep surface shown only when runtime reports an eGPU is attached.
 * Disconnect-before-sleep is disabled; runtime owns attached sleep.
 */
export function EgpuSleepChoicePopup({ connectionLabel, sleepAttachedAction, cancelAction, detail }: {
  connectionLabel: string;
  sleepAttachedAction?: ReactNode;
  cancelAction?: ReactNode;
  detail?: string;
}) {
  return <ReGearPopup title="Sleep with eGPU connected" status={connectionLabel} tone="active" footer={<>{cancelAction}{sleepAttachedAction}</>}>
    <CommandDetailSurface>
      <CommandNotice tone="active" title="Sleep with the connection attached">
        {detail ?? "Normal sleep keeps the eGPU physically connected and leaves lifecycle policy with the runtime."}
      </CommandNotice>
      <CommandSection title="Options">
        <CommandStatusRow label="Sleep" value="Keep eGPU connected" tone="active" detail="Resume with the existing physical connection still attached."/>
      </CommandSection>
    </CommandDetailSurface>
  </ReGearPopup>;
}

export function EgpuPowerActions({ sleepConnectedAction, safeDisconnectShutdownAction }: {
  sleepConnectedAction?: ReactNode;
  safeDisconnectShutdownAction?: ReactNode;
}) {
  return <CommandDetailSurface>
    <CommandSection title="Power actions" hint="Power requests remain separate from Safe Disconnect completion and physical unplug clearance.">
      <CommandStatusRow label="Sleep" value="Keep eGPU connected" tone="active" detail="Requests normal sleep without running Safe Disconnect."/>
      <CommandStatusRow label="Safe Disconnect + Shutdown" value="Optional" tone="warning" detail="Runs Safe Disconnect, then requests shutdown only when runtime permits it."/>
    </CommandSection>
    {(sleepConnectedAction || safeDisconnectShutdownAction) && <CommandActionRow>{sleepConnectedAction}{safeDisconnectShutdownAction}</CommandActionRow>}
  </CommandDetailSurface>;
}
