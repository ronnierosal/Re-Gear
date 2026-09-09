import { DialogButton, Focusable } from "@decky/ui";
import type { EgpuPresentation, Evidence } from "./egpu-presentation";

/** eGPU module page: rendering only, no policy, no requests, no device action.
 *
 * Every reading comes from egpu-presentation, which derives each one from
 * exactly one source. They are drawn as separate rows on purpose: a single
 * "eGPU: connected" summary is what makes a player believe the link, the
 * renderer and the display agree when they do not.
 *
 * This page performs nothing. Recovery is surfaced as an entry that calls back
 * into the panel control that already owns its guards and confirmation; this
 * file neither starts a transition nor removes a device.
 *
 * The disconnect row never claims a safe unplug, whatever the readings say.
 */

const C = {
  cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca",
  border: "#294665", amber: "#ffc247", dim: "#5d7a99",
};

const SURFACE = "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))";

function Row({ label, value }: { label: string; value: Evidence }) {
  return <div style={{
    display: "flex", justifyContent: "space-between", alignItems: "baseline",
    gap: 8, padding: "5px 0", borderBottom: `1px solid ${C.border}`, minWidth: 0,
  }}>
    <span style={{ fontSize: 12, color: C.muted, flex: "0 1 auto" }}>{label}</span>
    <span style={{
      fontSize: 13, fontWeight: 700, textAlign: "right", minWidth: 0,
      // Absent evidence is dimmed, never coloured as though it were a result.
      color: value.known ? C.text : C.dim,
    }}>
      {value.text}
      {/* An observed reading is not a verified one, and the difference matters
          when a player is deciding whether to trust it. */}
      {value.known && !value.verified && (
        <span style={{ fontSize: 11, fontWeight: 400, color: C.muted }}> · observed</span>
      )}
    </span>
  </div>;
}

export function EgpuModule({ presentation, onOpenRecovery }: {
  presentation: EgpuPresentation;
  /** Routes to the panel's existing guarded recovery control. This page owns
   * no recovery logic and starts nothing itself. */
  onOpenRecovery?(): void;
}) {
  const p = presentation;
  return <div style={{ color: C.text, minWidth: 0, margin: "0 2px" }}>
    {p.model && (
      <div style={{ fontSize: 13, fontWeight: 760, marginBottom: 6 }}>{p.model}</div>
    )}

    <Row label="Connection" value={p.connection} />
    <Row label="Rendering" value={p.renderGpu} />
    <Row label="External display" value={p.displayConnected} />
    <Row label="Display output" value={p.displayActive} />
    <Row label="Session" value={p.session} />
    <Row label="Game" value={p.game} />
    <Row label="Lifecycle" value={p.lifecycle} />

    {/* Unconditional. No combination of readings turns this into a safe claim. */}
    <div style={{
      marginTop: 12, padding: "8px 10px", borderRadius: 10,
      background: SURFACE, border: `1px solid ${C.border}`,
    }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: C.amber, marginBottom: 2 }}>
        Safe to disconnect: {p.disconnect.text}
      </div>
      <div style={{ fontSize: 12, lineHeight: "16px", color: C.muted }}>
        {p.disconnect.reason}
      </div>
    </div>

    {p.recovery.note && (
      <div style={{ fontSize: 12, lineHeight: "16px", color: C.muted, marginTop: 8 }}>
        {p.recovery.note}
      </div>
    )}

    {onOpenRecovery && (
      <Focusable style={{ marginTop: 10 }}>
        <DialogButton
          onClick={onOpenRecovery}
          style={{
            width: "100%", minHeight: 40, margin: 0, padding: "6px 10px",
            borderRadius: 10, background: SURFACE, border: `1px solid ${C.border}`,
            color: C.cyan, fontSize: 13, fontWeight: 700,
          }}>
          Recovery and troubleshooting
        </DialogButton>
      </Focusable>
    )}
  </div>;
}
