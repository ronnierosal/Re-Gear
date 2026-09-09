import { DialogButton, Focusable } from "@decky/ui";
import type { DisconnectResult } from "./disconnect-result";

/** Post-disconnect result notice: rendering only, no policy, no requests.
 *
 * Placed at the top of Command Center because it answers the question a player
 * has the moment the panel comes back after the session restart, and an answer
 * they have to scroll to find is one they will act without.
 *
 * The unplug line is styled as the most prominent thing in the block on
 * purpose. It is the one sentence that must survive being skim-read.
 */

const C = {
  cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca",
  border: "#294665", amber: "#ffc247", red: "#ff6b6b",
};

const TONE_COLOR: Record<DisconnectResult["tone"], string> = {
  done: "#39d8ff", attention: "#ffc247", failed: "#ff6b6b",
};

export function DisconnectResultNotice({ result, onDismiss }: {
  result: DisconnectResult;
  onDismiss(): void;
}) {
  if (!result.show) return null;
  const accent = TONE_COLOR[result.tone];
  return <div style={{
    margin: "0 2px 10px", padding: "10px", borderRadius: 12, minWidth: 0,
    background: "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))",
    border: `1px solid ${accent}`,
  }}>
    <div style={{ fontSize: 14, fontWeight: 760, color: accent, marginBottom: 4 }}>
      {result.headline}
    </div>
    {result.detail.map((line) => (
      <div key={line} style={{ fontSize: 12, lineHeight: "17px", color: C.muted }}>
        {line}
      </div>
    ))}
    {/* The evidence, then the verdict it earned. Shown in that order on
        purpose: a player can check the reasoning before acting on the answer,
        and a failed check names itself rather than hiding behind a refusal. */}
    <div style={{ marginTop: 8 }}>
      {result.clearance.checks.map((entry) => (
        <div key={entry.label} style={{
          display: "flex", gap: 6, alignItems: "baseline",
          fontSize: 11, lineHeight: "16px", minWidth: 0,
        }}>
          <span style={{ color: entry.passed ? C.cyan : C.red, fontWeight: 760 }}>
            {entry.passed ? "✓" : "✗"}
          </span>
          <span style={{ color: C.muted, minWidth: 0 }}>
            <span style={{ color: entry.passed ? C.text : C.red }}>{entry.label}</span>
            {" · "}{entry.detail}
          </span>
        </div>
      ))}
    </div>

    {/* The sentence that must survive a skim. */}
    <div style={{
      marginTop: 8, padding: "7px 9px", borderRadius: 9,
      background: result.clearance.cleared ? "rgba(57,216,255,.10)" : "rgba(255,194,71,.10)",
      border: `1px solid ${result.clearance.cleared ? C.cyan : C.amber}`,
      fontSize: 13, fontWeight: 760, lineHeight: "18px",
      color: result.clearance.cleared ? C.cyan : C.amber,
    }}>
      {result.clearance.statement}
    </div>
    <div style={{ marginTop: 6, fontSize: 11, lineHeight: "15px", color: C.muted }}>
      {result.clearance.caveat}
    </div>
    <Focusable style={{ marginTop: 8 }}>
      <DialogButton
        onClick={onDismiss}
        style={{
          width: "100%", minHeight: 36, margin: 0, padding: "5px 10px",
          borderRadius: 9, fontSize: 12, fontWeight: 700, color: C.text,
          background: "rgba(41,70,101,.5)", border: `1px solid ${C.border}`,
        }}>
        Dismiss
      </DialogButton>
    </Focusable>
  </div>;
}
