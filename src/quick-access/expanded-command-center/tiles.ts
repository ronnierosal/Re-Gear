/** Build expanded Command Center tiles from real observations.
 *
 * The expanded shell was built against `sampleTiles` -- a synthetic set with
 * confident values like "Connected" and "RX 7600M XT" hard-coded into it. That
 * is fine for a prototype and dangerous the moment it is connected, because
 * every one of those strings reads to a player as a reading of their device.
 *
 * So nothing here invents a presentation rule. `egpuPresentation` already
 * derives each reading from exactly one source and refuses to collapse them,
 * and this file only chooses how those readings look as tiles. Re-deriving any
 * of it here would mean maintaining the same safety argument in two places,
 * and the one that drifts is the one nobody is reading.
 *
 * Two rules the mapping itself has to keep:
 *
 * - **Unknown is a tone, not a blank.** An absent reading renders `unavailable`
 *   with a value of "Unknown", never an empty tile and never a plausible
 *   default. A tile that shows nothing looks like a tile that is still loading.
 * - **Observed is not verified.** A reading the payload did not grade
 *   `verified` renders `quiet` and says so, because `active` is the tone the
 *   player reads as "this is true right now".
 *
 * The Safe Disconnect tile takes its text from `presentation.disconnect`, whose
 * `safeClaim` is typed as the literal `false` -- there is no value of the
 * payload that produces a tile claiming a cable may be pulled, and that is a
 * type error rather than a review comment.
 */

import type { ControllerPresentation } from "../modules/controller-presentation";
import type { EgpuPresentation, Evidence } from "../modules/egpu-presentation";
import type { PerformanceState, TileValue } from "../performance-state";
import type { Tile, Tone } from "./model";

/** Absent evidence is unavailable; ungraded evidence is quiet, never active. */
export function evidenceTone(evidence: Evidence): Tone {
  if (!evidence.known) return "unavailable";
  return evidence.verified ? "active" : "quiet";
}

/** Say which reading this is, and how well it is known. */
function detail(evidence: Evidence, source: string): string {
  if (!evidence.known) return `${source} · no observation available`;
  return evidence.verified ? source : `${source} · observed, not verified`;
}

/** The eGPU tab, built from one snapshot reading. */
export function egpuTiles(presentation: EgpuPresentation): Tile[] {
  const { connection, renderGpu, displayConnected, displayActive, game } = presentation;
  return [
    {
      id: "egpu",
      title: "Connection",
      value: connection.text,
      // The model name is presentation only and is null unless a single
      // external GPU was reported, so it never stands in for identity.
      detail: detail(connection, presentation.model ?? "Physical link"),
      tone: evidenceTone(connection),
    },
    {
      id: "render",
      title: "Render GPU",
      value: renderGpu.text,
      detail: detail(renderGpu, "Which GPU was selected to render"),
      tone: evidenceTone(renderGpu),
    },
    {
      id: "display",
      title: "External display",
      // Attachment and output are separate facts and are shown separately; a
      // connected display is not a display that is driving anything.
      value: displayConnected.text,
      detail: detail(displayActive, `Output: ${displayActive.text}`),
      tone: evidenceTone(displayConnected),
    },
    {
      id: "game",
      title: "Game state",
      value: game.text,
      detail: detail(game, "Running-game observation"),
      tone: evidenceTone(game),
    },
    {
      id: "disconnect",
      title: "Safe Disconnect",
      value: presentation.disconnect.text,
      detail: presentation.disconnect.reason,
      // Always warning. Not derived from the readings above, because no
      // combination of them grants a clearance this product cannot confirm.
      tone: "warning",
      wide: true,
    },
  ];
}

/** The performance tab.
 *
 * Values are passed in rather than computed here so this module stays free of
 * runtime imports and each tile can be tested against an exact reading.
 *
 * Every tile keeps a fixed position, including the FPS one that is always
 * unavailable. `fpsTile` gives the reason: a grid whose shape depends on live
 * evidence moves a target under a player's thumb mid-press.
 */
export function performanceTiles(input: {
  state: PerformanceState;
  manualWatts: TileValue;
  fps: { available: false; value: TileValue; reason: string };
  display: Evidence;
}): Tile[] {
  const { state, manualWatts, fps, display } = input;
  const auto = !state.autoKnown ? { text: "Unknown", tone: "unavailable" as Tone }
    : state.stopping ? { text: "Stopping…", tone: "quiet" as Tone }
    : state.active ? { text: "Running", tone: "active" as Tone }
    : { text: "Off", tone: "quiet" as Tone };
  return [
    {
      id: "manual",
      title: "Manual TDP",
      value: manualWatts.text,
      // wattsValue keeps an unreadable limit as "Unknown" rather than 0 W, so
      // there is nothing to second-guess here.
      detail: manualWatts.known ? "Current limit" : "No limit observed",
      tone: manualWatts.known ? "active" : "unavailable",
    },
    {
      id: "auto",
      title: "Auto TDP",
      value: auto.text,
      // `reason` already explains an unsupported device, a pending read or a
      // recovery requirement; it is the honest line whenever it is present.
      detail: state.reason ?? (state.active ? "Controller running" : "Not running"),
      tone: auto.tone,
    },
    {
      id: "fps",
      title: "FPS Target",
      value: fps.value.text,
      detail: fps.reason,
      // Proposed capability with no backend provider. Showing a number here
      // would be fabricating one.
      tone: "unavailable",
    },
    {
      id: "display",
      title: "Display context",
      value: display.text,
      detail: "Display target is separate from FPS control",
      tone: evidenceTone(display),
    },
  ];
}

/** The controllers tab.
 *
 * `ControllerFact` carries no verified grade, so tone comes from the payload's
 * own `precision`: an `exact` reading may use the confident tone, a `partial`
 * one may not, and `unknown` is unavailable like any other absence.
 */
export function controllerTiles(presentation: ControllerPresentation): Tile[] {
  const tone = (known: boolean): Tone => {
    if (!known || presentation.precision === "unknown") return "unavailable";
    return presentation.precision === "exact" ? "active" : "quiet";
  };
  const caveat = (base: string) =>
    presentation.precisionNote ? `${base} · ${presentation.precisionNote}` : base;
  return [
    {
      id: "controller",
      title: "External controller",
      value: presentation.external.text,
      detail: presentation.available
        ? caveat("Reported by the peripheral status")
        : presentation.reason ?? "No controller reading available",
      tone: tone(presentation.external.known),
    },
    {
      id: "builtin",
      title: "Built-in controller",
      value: presentation.builtin.text,
      detail: presentation.available
        ? caveat("Reported by the peripheral status")
        : presentation.reason ?? "No controller reading available",
      tone: tone(presentation.builtin.known),
    },
    {
      id: "priority",
      title: "Controller priority",
      // Named in the plan and not implemented. Stated as unavailable so its
      // absence is explicit rather than a gap a player has to notice, and
      // never rendered as a working control.
      value: "Not available",
      detail: `Planned, not implemented: ${presentation.planned.join(", ")}`,
      tone: "unavailable",
    },
  ];
}
