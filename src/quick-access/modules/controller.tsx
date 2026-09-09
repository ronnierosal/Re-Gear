import type { ControllerFact, ControllerPresentation } from "./controller-presentation";

/** Controller module page: rendering only, no policy, no requests.
 *
 * Read-only. Every value comes from controller-presentation, which reports only
 * what the backend observed, so this file cannot invent a device name, a
 * Player 1 badge, or a presence claim derived from the shortcut source.
 *
 * Planned capabilities are listed as not yet available rather than drawn as
 * disabled switches. A greyed-out toggle still reads as a control that exists
 * and is temporarily off; a line of text saying "not yet available" does not.
 */

const C = {
  cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca",
  border: "#294665", amber: "#ffc247", dim: "#5d7a99",
};

function Row({ label, fact }: { label: string; fact: ControllerFact }) {
  return <div style={{
    display: "flex", justifyContent: "space-between", alignItems: "baseline",
    gap: 8, padding: "5px 0", borderBottom: `1px solid ${C.border}`, minWidth: 0,
  }}>
    <span style={{ fontSize: 12, color: C.muted, flex: "0 1 auto" }}>{label}</span>
    <span style={{
      fontSize: 13, fontWeight: 700, textAlign: "right", minWidth: 0,
      // An unknown reading is dimmed, never coloured as though it were a result.
      color: fact.known ? C.text : C.dim,
    }}>{fact.text}</span>
  </div>;
}

export function ControllerModule({ presentation }: { presentation: ControllerPresentation }) {
  return <div style={{ color: C.text, minWidth: 0, margin: "0 2px" }}>
    {presentation.reason && (
      <div style={{ fontSize: 12, lineHeight: "16px", color: C.amber, marginBottom: 8 }}>
        {presentation.reason}
      </div>
    )}

    <Row label="Built-in controls" fact={presentation.builtin} />
    <Row label="External controller" fact={presentation.external} />
    {/* Separated on purpose: this is Re-Gear's input source, not a controller. */}
    <Row label="Shortcut input" fact={presentation.shortcut} />

    {presentation.precisionNote && (
      <div style={{ fontSize: 11, lineHeight: "15px", color: C.muted, marginTop: 8 }}>
        {presentation.precisionNote}
      </div>
    )}

    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: C.muted, marginBottom: 4 }}>
        Not yet available
      </div>
      {presentation.planned.map((feature) => (
        <div key={feature} style={{ fontSize: 12, lineHeight: "17px", color: C.dim }}>
          {feature}
        </div>
      ))}
    </div>
  </div>;
}
