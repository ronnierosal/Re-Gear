import type { ReactNode } from "react";
import type { UtilityId } from "./utility-layout";
import { quickActionIds, optionalQuickActionIds } from "./utility-layout";
import { CommandDetailSurface, CommandNotice, CommandSection } from "./detail-ui";

export type QuickActionChoice = {
  id: UtilityId;
  label: string;
  available: boolean;
  selected: boolean;
  control?: ReactNode;
};

const approved = new Set<UtilityId>([...quickActionIds, ...optionalQuickActionIds]);

/**
 * Presentation-only customization surface. Runtime owners may supply real
 * controls and persistence, but this surface owns the approved composition:
 * Brightness and Volume are not customizable here and the detached rail stays
 * a compact list of supported quick actions.
 */
export function QuickActionsCustomization({ choices }: { choices: readonly QuickActionChoice[] }) {
  const visible = choices.filter(choice => approved.has(choice.id));
  return <CommandDetailSurface>
    <CommandNotice tone="neutral" title="Quick Actions">
      Choose which supported actions appear in the right rail. Brightness and Volume remain part of the main Command Center.
    </CommandNotice>
    <CommandSection title="Right rail" hint="Unavailable actions stay visible so support is explicit; runtime code decides whether they can be enabled.">
      <div style={{ display: "grid", gap: 6 }}>
        {visible.map(choice => <div key={choice.id} data-quick-action={choice.id} data-selected={choice.selected ? "true" : "false"} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 10, alignItems: "center", minHeight: 38, padding: "6px 8px", border: `1px solid ${choice.selected ? "#39d8ff" : "#315f79"}`, borderRadius: 9, background: choice.selected ? "#0c3145" : "#0a2030", opacity: choice.available ? 1 : .62 }}>
          <span style={{ minWidth: 0 }}>
            <strong style={{ display: "block", fontSize: 11.5, color: choice.selected ? "#55e0ff" : "#e5f3fb", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{choice.label}</strong>
            <small style={{ display: "block", marginTop: 2, fontSize: 9.5, color: "#91b7d1" }}>{choice.available ? (choice.selected ? "Shown in Quick Access" : "Available") : "Unavailable on this system"}</small>
          </span>
          {choice.control}
        </div>)}
      </div>
    </CommandSection>
  </CommandDetailSurface>;
}
