import type { ReactNode } from "react";
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
  control?: ReactNode;
};

const egpuActionStyles = `
[data-egpu-action-grid]{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;container-type:inline-size}
[data-egpu-action-card]{min-width:0;min-height:72px;padding:8px 9px;border-radius:10px;display:grid;grid-template-rows:minmax(0,1fr) auto;align-content:stretch;gap:6px}
[data-egpu-action-card] strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:10.5px;line-height:1.18;color:#e7f4fb;white-space:normal}
[data-egpu-action-card] [data-egpu-action-detail]{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-top:2px;font-size:9px;line-height:1.22;color:#8fb3cc}
@container (max-width:520px){[data-egpu-action-grid]{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}[data-egpu-action-card]{min-height:66px;padding:7px 8px}}
@container (max-width:300px){[data-egpu-action-grid]{grid-template-columns:1fr}[data-egpu-action-card]{min-height:60px}}
@media(max-height:520px){[data-egpu-action-grid]{gap:6px}[data-egpu-action-card]{min-height:58px;padding:6px 7px}[data-egpu-action-card] strong{font-size:9.5px}[data-egpu-action-card] [data-egpu-action-detail]{font-size:8px}}
`;

/**
 * Shared eGPU action surface for the eGPU module and Quick Access tab.
 * Runtime owners supply controls; this component does not dispatch actions.
 */
export function EgpuQuickActions({ actions }: { actions: readonly EgpuActionPresentation[] }) {
  return <CommandSection title="eGPU actions" hint="The same verified actions may be surfaced in Quick Access and the eGPU module without changing their meaning.">
    <style>{egpuActionStyles}</style>
    <div data-egpu-action-grid>
      {actions.map(action => <div key={action.id} data-egpu-action-card data-egpu-action-id={action.id} style={{ border: `1px solid ${action.tone === "warning" ? "#80672f" : "#315c75"}`, background: action.unavailable ? "#0b1821" : "#0b2230", opacity: action.unavailable ? .62 : 1 }}>
        <div style={{ minWidth: 0 }}>
          <strong>{action.label}</strong>
          {action.detail && <span data-egpu-action-detail>{action.detail}</span>}
        </div>
        {action.control}
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
 * Sleep choice shown only when runtime reports an eGPU is attached.
 * Sleeping with the eGPU connected is a first-class option; safe-disconnect-first is optional.
 */
export function EgpuSleepChoicePopup({ connectionLabel, sleepAttachedAction, safeDisconnectSleepAction, cancelAction, detail }: {
  connectionLabel: string;
  sleepAttachedAction?: ReactNode;
  safeDisconnectSleepAction?: ReactNode;
  cancelAction?: ReactNode;
  detail?: string;
}) {
  return <ReGearPopup title="Sleep with eGPU connected" status={connectionLabel} tone="active" footer={<>{cancelAction}{safeDisconnectSleepAction}{sleepAttachedAction}</>}>
    <CommandDetailSurface>
      <CommandNotice tone="active" title="Choose how to sleep">
        {detail ?? "You can sleep while the eGPU remains connected and resume normally, or ask Re-Gear to perform Safe Disconnect before sleeping."}
      </CommandNotice>
      <CommandSection title="Options">
        <CommandStatusRow label="Sleep" value="Keep eGPU connected" tone="active" detail="Resume with the existing physical connection still attached."/>
        <CommandStatusRow label="Safe Disconnect + Sleep" value="Disconnect first" tone="warning" detail="Runs the verified Safe Disconnect flow before the sleep request."/>
      </CommandSection>
    </CommandDetailSurface>
  </ReGearPopup>;
}

export function EgpuPowerActions({ safeDisconnectSleepAction, safeDisconnectShutdownAction }: {
  safeDisconnectSleepAction?: ReactNode;
  safeDisconnectShutdownAction?: ReactNode;
}) {
  return <CommandDetailSurface>
    <CommandSection title="Power actions" hint="Power requests remain separate from Safe Disconnect completion and physical unplug clearance.">
      <CommandStatusRow label="Safe Disconnect + Sleep" value="Optional" tone="warning" detail="Runs Safe Disconnect, then requests sleep only when runtime permits it."/>
      <CommandStatusRow label="Safe Disconnect + Shutdown" value="Optional" tone="warning" detail="Runs Safe Disconnect, then requests shutdown only when runtime permits it."/>
    </CommandSection>
    {(safeDisconnectSleepAction || safeDisconnectShutdownAction) && <CommandActionRow>{safeDisconnectSleepAction}{safeDisconnectShutdownAction}</CommandActionRow>}
  </CommandDetailSurface>;
}
