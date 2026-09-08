import { DialogButton, Focusable } from "@decky/ui";
import type { QuickAccessNavIcon, QuickAccessNavView } from "./quick-access-nav";
import type { QuickAccessSectionId } from "./quick-access-sections";

/** Section chooser for the ~310px Quick Access panel: one row of icon targets.
 *
 * Rendering only. Which sections exist, which are usable and what a blocked one
 * says all come from the view model, so this file holds no policy.
 */

const C = { cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca", border: "#294665" };

// Two kinds the shared dashboard set does not carry yet. Kept local so wiring
// this row does not touch a file another change is editing.
const PATHS: Record<QuickAccessNavIcon, string> = {
  connection: "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v4",
  controller: "M7 12H3.5a2 2 0 0 1 0-4H7 M17 12h3.5a2 2 0 0 0 0-4H17 M7 8h10l2 9a2 2 0 0 1-3.6 1.4L12 15l-3.4 3.4A2 2 0 0 1 5 17z M9.5 10v2 M8.5 11h2 M15 10.5h.1 M16.5 12h.1",
  gauge: "M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M13.4 10.6L17 7 M4 18a9 9 0 1 1 16 0",
  monitor: "M3 4h18v13H3z M8 21h8 M12 17v4",
  tools: "M14 3a6 6 0 0 0-7 7L2 15l7 7 5-5a6 6 0 0 0 7-7l-4 4-5-5z",
};

function NavIcon({ kind, size = 22 }: { kind: QuickAccessNavIcon; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    style={{ flexShrink: 0 }}><path d={PATHS[kind]} /></svg>;
}

export function QuickAccessNav({ view, onSelect }: {
  view: QuickAccessNavView;
  onSelect(id: QuickAccessSectionId): void;
}) {
  return <div style={{ color: C.text, minWidth: 0 }}>
    <Focusable style={{ display: "flex", gap: 4, marginBottom: 10 }} flow-children="horizontal">
      {view.items.map((item) => (
        <DialogButton
          key={item.id}
          onClick={() => onSelect(item.id)}
          // Unavailable targets stay focusable: selecting one is how a player
          // reads why the section cannot be used.
          aria-label={item.label}
          aria-current={item.active ? "true" : undefined}
          style={{
            flex: "1 1 0", minWidth: 0, width: "auto", height: 44, minHeight: 44,
            margin: 0, padding: 0, borderRadius: 12,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: item.active
              ? "linear-gradient(135deg, rgba(8,56,81,.94), rgba(8,24,41,.98))"
              : "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))",
            border: `1px solid ${item.active ? "#2c89a6" : C.border}`,
            color: item.active ? C.cyan : item.available ? C.muted : "#5d7a99",
            opacity: item.available ? 1 : 0.55,
          }}>
          <NavIcon kind={item.icon} />
        </DialogButton>
      ))}
    </Focusable>
    <div style={{ margin: "0 2px 10px" }}>
      <div style={{ fontSize: 15, fontWeight: 760, marginBottom: 2 }}>{view.heading}</div>
      <div style={{ fontSize: 12, lineHeight: "16px", color: view.blocked ? "#ffc247" : C.muted }}>
        {view.detail}
      </div>
    </div>
  </div>;
}
