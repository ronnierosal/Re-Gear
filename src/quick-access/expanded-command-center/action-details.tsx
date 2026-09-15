import type { ReactNode } from "react";
import { CommandActionRow, CommandDetailSurface, CommandNotice, CommandSection, CommandStatusRow, CommandValue, type DetailTone } from "./detail-ui";
import { CommandControlRow, CommandProgressSteps, CommandRangePreview, CommandSegmentedPreview, CommandTogglePreview } from "./control-ui";

export type ControlValue = { value: string; tone?: DetailTone; detail?: string };

export function PerformanceControlDetail({ profile, fps, manualTdp, autoTdp, resolution, refreshRate, controls, actions }: {
  profile: ControlValue; fps: ControlValue; manualTdp: ControlValue; autoTdp: ControlValue; resolution: ControlValue; refreshRate: ControlValue;
  controls?: Partial<Record<"profile" | "fps" | "manualTdp" | "autoTdp" | "resolution" | "refreshRate", ReactNode>>;
  actions?: ReactNode;
}) {
  return <CommandDetailSurface>
    <CommandSection title="Performance controls" hint="Compact controls belong here; unsupported providers stay visible but unavailable.">
      <CommandControlRow label="Profile" value={profile.value} tone={profile.tone} detail={profile.detail} control={controls?.profile ?? <CommandSegmentedPreview options={["Quiet", "Balanced", "Performance"]} selected={profile.value}/>} />
      <CommandControlRow label="FPS target" value={fps.value} tone={fps.tone} detail={fps.detail} control={controls?.fps} />
      <CommandControlRow label="Manual TDP" value={manualTdp.value} tone={manualTdp.tone} detail={manualTdp.detail} control={controls?.manualTdp ?? <CommandRangePreview value={Number.parseFloat(manualTdp.value) || 0} max={40} label="Manual TDP preview"/>} />
      <CommandControlRow label="Auto TDP" value={autoTdp.value} tone={autoTdp.tone} detail={autoTdp.detail} control={controls?.autoTdp ?? <CommandTogglePreview enabled={autoTdp.value.toLowerCase() === "on"}/>} />
    </CommandSection>
    <CommandSection title="Display target">
      <CommandControlRow label="Resolution" value={resolution.value} tone={resolution.tone} detail={resolution.detail} control={controls?.resolution}/>
      <CommandControlRow label="Refresh rate" value={refreshRate.value} tone={refreshRate.tone} detail={refreshRate.detail} control={controls?.refreshRate}/>
    </CommandSection>
    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}

export function SafeDisconnectDetail({ readiness, blockers, phase, steps, activeStep = 0, action, secondaryAction }: {
  readiness: ControlValue;
  blockers?: readonly ControlValue[];
  phase?: ControlValue;
  steps?: readonly string[];
  activeStep?: number;
  action?: ReactNode;
  secondaryAction?: ReactNode;
}) {
  const ready = readiness.tone === "success";
  return <CommandDetailSurface>
    <CommandNotice tone={readiness.tone ?? "warning"} title={`Safe Disconnect · ${readiness.value}`}>
      {readiness.detail ?? "Readiness, software removal, and physical unplug clearance are separate states."}
    </CommandNotice>
    <CommandSection title="Readiness" hint="Re-Gear should explain what is blocking the operation before offering the action.">
      {blockers?.length ? blockers.map((blocker, index) => <CommandStatusRow key={`${blocker.value}-${index}`} label={`Check ${index + 1}`} value={blocker.value} tone={blocker.tone} detail={blocker.detail}/>) : <CommandStatusRow label="Checks" value={ready ? "Ready" : "Pending"} tone={ready ? "success" : "warning"} detail="Runtime wiring supplies verified checks; presentation never infers them."/>}
    </CommandSection>
    {phase && <CommandSection title="Current operation">
      <CommandValue label="Phase" value={phase.value} tone={phase.tone}/>
      {phase.detail && <div style={{ fontSize: 10, color: "#91b7d1", lineHeight: 1.35 }}>{phase.detail}</div>}
      {steps?.length ? <CommandProgressSteps steps={steps} activeIndex={Math.max(0, Math.min(activeStep, steps.length - 1))}/> : null}
    </CommandSection>}
    <CommandNotice tone="warning" title="Physical unplug clearance is separate">
      A successful software command or return to the handheld display does not by itself certify that the cable may be unplugged.
    </CommandNotice>
    {(action || secondaryAction) && <CommandActionRow>{secondaryAction}{action}</CommandActionRow>}
  </CommandDetailSurface>;
}

export function ControllerControlDetail({ playerOne, battery, builtIn, priority, tvDockBehavior, controls, actions }: {
  playerOne: ControlValue; battery: ControlValue; builtIn: ControlValue; priority: ControlValue; tvDockBehavior: ControlValue;
  controls?: Partial<Record<"playerOne" | "builtIn" | "priority" | "tvDockBehavior", ReactNode>>;
  actions?: ReactNode;
}) {
  return <CommandDetailSurface>
    <CommandSection title="Player assignment">
      <CommandControlRow label="Player 1" value={playerOne.value} tone={playerOne.tone} detail={playerOne.detail} control={controls?.playerOne}/>
      <CommandStatusRow label="Battery" value={battery.value} tone={battery.tone} detail={battery.detail}/>
      <CommandControlRow label="Built-in controller" value={builtIn.value} tone={builtIn.tone} detail={builtIn.detail} control={controls?.builtIn ?? <CommandTogglePreview enabled={builtIn.value.toLowerCase() === "on"}/>} />
    </CommandSection>
    <CommandSection title="Dock behavior">
      <CommandControlRow label="Controller priority" value={priority.value} tone={priority.tone} detail={priority.detail} control={controls?.priority}/>
      <CommandControlRow label="TV dock behavior" value={tvDockBehavior.value} tone={tvDockBehavior.tone} detail={tvDockBehavior.detail} control={controls?.tvDockBehavior}/>
    </CommandSection>
    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}
