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

export type QuickActionSlot = {
  slot: number;
  id: UtilityId;
  label: string;
  control?: ReactNode;
};

const approved = new Set<UtilityId>([...quickActionIds, ...optionalQuickActionIds]);

/**
 * X on the Quick Access root opens this right-rail editor. It is intentionally
 * separate from Y customization: X changes the detached quick-action rail,
 * while Y changes/reorders the main Command Center cards.
 */
export function QuickActionRailEditor({ slots, choices }: {
  slots: readonly QuickActionSlot[];
  choices: readonly QuickActionChoice[];
}) {
  const visible = choices.filter(choice => approved.has(choice.id));
  return <CommandDetailSurface>
    <CommandNotice tone="neutral" title="Quick Action Buttons">
      Change the four buttons on the right side of Quick Access. Brightness and Volume stay fixed on the left.
    </CommandNotice>
    <CommandSection title="Current buttons" hint="Choose a slot, then select a supported action below.">
      <div data-quick-action-slots style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 7 }}>
        {slots.slice(0,4).map(slot => <div key={slot.slot} data-quick-action-slot={slot.slot} style={{ minWidth: 0, minHeight: 58, display: "grid", alignContent: "space-between", gap: 5, padding: "7px 8px", border: "1px solid #315f79", borderRadius: 9, background: "#0a2030" }}>
          <span style={{ display: "block", fontSize: 8.5, color: "#7899ad" }}>Slot {slot.slot + 1}</span>
          <strong style={{ display: "block", minWidth: 0, fontSize: 10.5, lineHeight: 1.15, color: "#e5f3fb", overflow: "hidden", textOverflow: "ellipsis" }}>{slot.label}</strong>
          {slot.control}
        </div>)}
      </div>
    </CommandSection>
    <CommandSection title="Available actions" hint="Unavailable actions remain visible but cannot be assigned.">
      <div style={{ display: "grid", gap: 6 }}>
        {visible.map(choice => <div key={choice.id} data-quick-action={choice.id} data-selected={choice.selected ? "true" : "false"} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 10, alignItems: "center", minHeight: 38, padding: "6px 8px", border: `1px solid ${choice.selected ? "#39d8ff" : "#315f79"}`, borderRadius: 9, background: choice.selected ? "#0c3145" : "#0a2030", opacity: choice.available ? 1 : .62 }}>
          <span style={{ minWidth: 0 }}>
            <strong style={{ display: "block", fontSize: 11.5, color: choice.selected ? "#55e0ff" : "#e5f3fb", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{choice.label}</strong>
            <small style={{ display: "block", marginTop: 2, fontSize: 9.5, color: "#91b7d1" }}>{choice.available ? (choice.selected ? "Currently assigned" : "Available") : "Unavailable on this system"}</small>
          </span>
          {choice.control}
        </div>)}
      </div>
    </CommandSection>
  </CommandDetailSurface>;
}

/** Legacy/Settings entry point for the same approved right-rail choices. */
export function QuickActionsCustomization({ choices }: { choices: readonly QuickActionChoice[] }) {
  const visible = choices.filter(choice => approved.has(choice.id));
  return <CommandDetailSurface>
    <CommandNotice tone="neutral" title="Quick Actions">
      Choose which supported actions may appear in the right rail. Brightness and Volume remain part of the main Command Center.
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
