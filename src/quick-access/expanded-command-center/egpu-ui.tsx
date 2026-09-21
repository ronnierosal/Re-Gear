import type { ReactNode } from "react";
import { CommandActionRow, CommandDetailSurface, CommandNotice, CommandSection, CommandStatusRow, CommandValue, type DetailTone } from "./detail-ui";
import { CommandProgressSteps } from "./control-ui";
import { PopupDetailsToggle, PopupStatusList, PopupStatusRow, ReGearPopup } from "./popup-ui";

export type EgpuUiValue = {
  value: string;
  tone?: DetailTone;
  detail?: string;
};

export type EgpuLifecyclePhase = {
  title: string;
  detail?: string;
  tone?: DetailTone;
  steps?: readonly string[];
  activeStep?: number;
};

export type EgpuPopupStep = {
  label: string;
  value: string;
  tone?: DetailTone;
  active?: boolean;
};

export type EgpuPopupMode = "progress" | "delayed" | "failed" | "success";

/**
 * Presentation-only eGPU module surface.
 *
 * Runtime owners provide observed values and real action controls. This component
 * deliberately owns no polling, RPC, device selection, disconnect policy, USB4,
 * PCI, DRM, Gamescope, or safety logic.
 */
export function EgpuControlDetail({
  device,
  dockMode,
  displayOutput,
  renderGpu,
  connectionLink,
  readiness,
  lifecycle,
  controls,
  actions,
}: {
  device: EgpuUiValue;
  dockMode: EgpuUiValue;
  displayOutput: EgpuUiValue;
  renderGpu: EgpuUiValue;
  connectionLink: EgpuUiValue;
  readiness: EgpuUiValue;
  lifecycle?: EgpuLifecyclePhase;
  controls?: Partial<Record<"dockMode" | "displayOutput" | "safeDisconnect" | "details", ReactNode>>;
  actions?: ReactNode;
}) {
  const activeStep = lifecycle?.steps?.length
    ? Math.max(0, Math.min(lifecycle.activeStep ?? 0, lifecycle.steps.length - 1))
    : 0;

  return <CommandDetailSurface>
    <CommandSection title="eGPU" hint="Connection, output, rendering, and disconnect readiness are separate states.">
      <CommandStatusRow label="External GPU" value={device.value} tone={device.tone} icon="egpu" detail={device.detail}/>
      <CommandStatusRow label="Dock mode" value={dockMode.value} tone={dockMode.tone} icon="dock-mode" detail={dockMode.detail}/>
      <CommandStatusRow label="Display output" value={displayOutput.value} tone={displayOutput.tone} icon="display" detail={displayOutput.detail}/>
      <CommandStatusRow label="Render GPU" value={renderGpu.value} tone={renderGpu.tone} icon="manual-tdp" detail={renderGpu.detail}/>
      <CommandStatusRow label="Connection link" value={connectionLink.value} tone={connectionLink.tone} icon="connection-link" detail={connectionLink.detail}/>
    </CommandSection>

    {lifecycle && <CommandSection title="Current operation">
      <CommandValue label="State" value={lifecycle.title} tone={lifecycle.tone}/>
      {lifecycle.detail && <div style={{ fontSize: 10, color: "#91b7d1", lineHeight: 1.35 }}>{lifecycle.detail}</div>}
      {lifecycle.steps?.length ? <CommandProgressSteps steps={lifecycle.steps} activeIndex={activeStep}/> : null}
    </CommandSection>}

    <CommandNotice tone={readiness.tone ?? "warning"} title={`Safe Disconnect · ${readiness.value}`}>
      {readiness.detail ?? "Readiness, software removal, and physical unplug clearance are separate states."}
    </CommandNotice>

    {(controls?.dockMode || controls?.displayOutput || controls?.safeDisconnect || controls?.details) && <CommandSection title="Actions" hint="Only verified runtime actions belong here; unsupported actions stay unavailable rather than disappearing.">
      {controls?.dockMode}
      {controls?.displayOutput}
      {controls?.safeDisconnect}
      {controls?.details}
    </CommandSection>}

    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}

/** Compact lifecycle presentation for connect / dock / return-to-handheld detail views. */
export function EgpuLifecycleDetail({
  title,
  elapsed,
  summary,
  steps,
  activeStep,
  tone = "active",
  warning,
  details,
  actions,
}: {
  title: string;
  elapsed?: string;
  summary?: string;
  steps: readonly string[];
  activeStep: number;
  tone?: DetailTone;
  warning?: string;
  details?: ReactNode;
  actions?: ReactNode;
}) {
  const safeStep = steps.length ? Math.max(0, Math.min(activeStep, steps.length - 1)) : 0;
  return <CommandDetailSurface>
    <CommandSection title={title} hint={elapsed ? `${elapsed} elapsed` : undefined}>
      {summary && <CommandValue label="Current step" value={summary} tone={tone}/>}
      {steps.length ? <CommandProgressSteps steps={steps} activeIndex={safeStep}/> : null}
    </CommandSection>
    {warning && <CommandNotice tone="warning" title="Taking longer than expected">{warning}</CommandNotice>}
    {details && <CommandSection title="Connection details">{details}</CommandSection>}
    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}

/**
 * Fast-path popup for the normal 7–10 second eGPU connection flow.
 *
 * Runtime owns when state becomes delayed/failed/retryable. The UI never derives
 * Retry from elapsed time and never restarts a connection on its own.
 */
export function EgpuConnectionPopup({
  mode,
  elapsed,
  status,
  steps,
  details,
  hideAction,
  detailsAction,
  retryAction,
  keepWaitingAction,
}: {
  mode: EgpuPopupMode;
  elapsed?: string;
  status: string;
  steps: readonly EgpuPopupStep[];
  details?: ReactNode;
  hideAction?: ReactNode;
  detailsAction?: ReactNode;
  retryAction?: ReactNode;
  keepWaitingAction?: ReactNode;
}) {
  const tone: DetailTone = mode === "success" ? "success" : mode === "failed" ? "error" : mode === "delayed" ? "warning" : "active";
  const title = mode === "success" ? "eGPU connected" : mode === "failed" ? "eGPU connection failed" : "Connecting eGPU";
  const footer = <>{hideAction}{detailsAction}{mode === "failed" ? retryAction : null}{mode === "delayed" ? keepWaitingAction : null}</>;

  return <ReGearPopup title={title} status={status} tone={tone} elapsed={elapsed} footer={footer}>
    <PopupStatusList>
      {steps.slice(0, 4).map((step) => <PopupStatusRow key={step.label} label={step.label} value={step.value} tone={step.tone} active={step.active}/>)}
    </PopupStatusList>

    {mode === "delayed" && <CommandNotice tone="warning" title="Taking longer than usual">Re-Gear is still waiting on the runtime state. Keep the eGPU connected. Retry is intentionally unavailable until runtime explicitly reports a retry-safe failure.</CommandNotice>}
    {mode === "failed" && <CommandNotice tone="error" title="Connection stopped">Retry appears only when the runtime has explicitly classified the operation as safe to retry.</CommandNotice>}
    {mode === "success" && <CommandNotice tone="success" title="TV Docked">Connection is complete. The host may dismiss this popup after the short success confirmation.</CommandNotice>}

    {details && <PopupDetailsToggle>{details}</PopupDetailsToggle>}
  </ReGearPopup>;
}
