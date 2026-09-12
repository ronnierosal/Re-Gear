import type { ReactNode } from "react";
import { CommandDetailSurface, CommandSection, CommandStatusRow, CommandNotice, CommandActionRow, CommandValue, type DetailTone } from "./detail-ui";

export type DetailValue = { value: string; tone?: DetailTone; detail?: string };

export function PerformanceDetail({ profile, fps, manualTdp, autoTdp, resolution, refreshRate, actions }: { profile: DetailValue; fps: DetailValue; manualTdp: DetailValue; autoTdp: DetailValue; resolution: DetailValue; refreshRate: DetailValue; actions?: ReactNode }) {
  return <CommandDetailSurface>
    <CommandSection title="Performance" hint="Tune the current play mode without mixing unrelated system settings.">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 10 }}>
        <CommandValue label="Profile" value={profile.value} tone={profile.tone}/>
        <CommandValue label="FPS target" value={fps.value} tone={fps.tone}/>
        <CommandValue label="Manual TDP" value={manualTdp.value} tone={manualTdp.tone}/>
        <CommandValue label="Auto TDP" value={autoTdp.value} tone={autoTdp.tone}/>
      </div>
    </CommandSection>
    <CommandSection title="Display target">
      <CommandStatusRow label="Resolution" value={resolution.value} tone={resolution.tone} icon="display" detail={resolution.detail}/>
      <CommandStatusRow label="Refresh rate" value={refreshRate.value} tone={refreshRate.tone} icon="refresh-rate" detail={refreshRate.detail}/>
    </CommandSection>
    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}

export function EgpuDetail({ device, dockMode, displayOutput, renderGpu, connectionLink, safeDisconnect, actions }: { device: DetailValue; dockMode: DetailValue; displayOutput: DetailValue; renderGpu: DetailValue; connectionLink: DetailValue; safeDisconnect: DetailValue; actions?: ReactNode }) {
  return <CommandDetailSurface>
    <CommandSection title="eGPU status" hint="Connection, output, rendering and link state are separate observations.">
      <CommandStatusRow label="External GPU" value={device.value} tone={device.tone} icon="egpu" detail={device.detail}/>
      <CommandStatusRow label="Dock mode" value={dockMode.value} tone={dockMode.tone} icon="dock-mode" detail={dockMode.detail}/>
      <CommandStatusRow label="Display output" value={displayOutput.value} tone={displayOutput.tone} icon="display" detail={displayOutput.detail}/>
      <CommandStatusRow label="Render GPU" value={renderGpu.value} tone={renderGpu.tone} icon="manual-tdp" detail={renderGpu.detail}/>
      <CommandStatusRow label="Connection link" value={connectionLink.value} tone={connectionLink.tone} icon="connection-link" detail={connectionLink.detail}/>
    </CommandSection>
    <CommandNotice tone={safeDisconnect.tone ?? "warning"} title={`Safe Disconnect · ${safeDisconnect.value}`}>{safeDisconnect.detail ?? "Readiness and unplug clearance are separate."}</CommandNotice>
    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}

export function ControllerDetail({ playerOne, battery, builtIn, priority, tvDockBehavior, actions }: { playerOne: DetailValue; battery: DetailValue; builtIn: DetailValue; priority: DetailValue; tvDockBehavior: DetailValue; actions?: ReactNode }) {
  return <CommandDetailSurface>
    <CommandSection title="Controller status" hint="Player assignment and dock behavior stay visible without becoming a device-manager screen.">
      <CommandStatusRow label="Player 1" value={playerOne.value} tone={playerOne.tone} icon="controllers" detail={playerOne.detail}/>
      <CommandStatusRow label="Battery" value={battery.value} tone={battery.tone} icon="battery" detail={battery.detail}/>
      <CommandStatusRow label="Built-in controller" value={builtIn.value} tone={builtIn.tone} icon="controllers" detail={builtIn.detail}/>
    </CommandSection>
    <CommandSection title="Dock behavior">
      <CommandStatusRow label="Controller priority" value={priority.value} tone={priority.tone} icon="controller-priority" detail={priority.detail}/>
      <CommandStatusRow label="TV dock behavior" value={tvDockBehavior.value} tone={tvDockBehavior.tone} icon="tv-dock" detail={tvDockBehavior.detail}/>
    </CommandSection>
    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}

export function SettingsDetail({ quickActions, shortcut, appearance, updates, diagnostics, about, actions }: { quickActions: DetailValue; shortcut: DetailValue; appearance: DetailValue; updates: DetailValue; diagnostics: DetailValue; about: DetailValue; actions?: ReactNode }) {
  return <CommandDetailSurface>
    <CommandSection title="Command Center">
      <CommandStatusRow label="Quick Actions" value={quickActions.value} tone={quickActions.tone} icon="quick-actions" detail={quickActions.detail}/>
      <CommandStatusRow label="Shortcut" value={shortcut.value} tone={shortcut.tone} icon="shortcut" detail={shortcut.detail}/>
      <CommandStatusRow label="Appearance" value={appearance.value} tone={appearance.tone} icon="settings" detail={appearance.detail}/>
    </CommandSection>
    <CommandSection title="Support & updates">
      <CommandStatusRow label="Updates" value={updates.value} tone={updates.tone} icon="updates" detail={updates.detail}/>
      <CommandStatusRow label="Diagnostics" value={diagnostics.value} tone={diagnostics.tone} icon="diagnostics" detail={diagnostics.detail}/>
      <CommandStatusRow label="About Re-Gear" value={about.value} tone={about.tone} icon="about" detail={about.detail}/>
    </CommandSection>
    {actions && <CommandActionRow>{actions}</CommandActionRow>}
  </CommandDetailSurface>;
}
