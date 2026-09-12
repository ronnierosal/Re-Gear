import type { ReactNode } from "react";
import { CommandActionRow, CommandDetailSurface, CommandNotice, CommandSection, CommandStatusRow, CommandValue, type DetailTone } from "./detail-ui";
import { CommandProgressSteps } from "./control-ui";

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

/**
 * Compact lifecycle presentation for connect / dock / return-to-handheld popups.
 * Runtime supplies the exact state machine phase and steps; the UI never infers
 * progress or fabricates percentages.
 */
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
