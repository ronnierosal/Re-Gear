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

/** An approved card whose provider does not exist yet.
 *
 * The composition is fixed by the UI contract, so a card with no provider is
 * STATED rather than omitted. Dropping it would reflow every card after it --
 * moving a target under a thumb mid-press -- and would quietly hide that the
 * capability is missing, which reads as "not applicable" rather than "not
 * built". `unavailable` is the tone that says so. */
function missingProvider(id: string, title: string, detail: string): Tile {
  return { id, title, value: "Not available", detail, tone: "unavailable" };
}

/** The eGPU tab, built from one snapshot reading. */
export function egpuTiles(presentation: EgpuPresentation): Tile[] {
  const { connection, renderGpu, displayConnected, displayActive, game, session } = presentation;
  return [
    {
      id: "device",
      title: "External GPU",
      // The payload documents `model_name` as presentation only and never an
      // identity input, and it is null unless exactly one external GPU was
      // reported. Putting it in the VALUE of a card titled "Detected device"
      // is precisely presenting it as identity, so it stays in the detail and
      // the reading itself stays Unknown: no field observes device identity.
      value: "Unknown",
      detail: presentation.model
        ? `Reported model name: ${presentation.model}. Presentation only, not device identity.`
        : "No single external GPU was reported.",
      tone: "unavailable",
    },
    missingProvider("dock", "Dock Mode",
      "No dock-mode reading reaches this view yet."),
    {
      id: "display",
      title: "Display Output",
      // Attachment and output are separate facts and are shown separately; a
      // connected display is not a display that is driving anything.
      value: displayConnected.text,
      detail: detail(displayActive, `Output: ${displayActive.text}`),
      tone: evidenceTone(displayConnected),
    },
    {
      id: "render",
      title: "Render GPU",
      value: renderGpu.text,
      detail: detail(renderGpu, "Which GPU was selected to render"),
      tone: evidenceTone(renderGpu),
    },
    {
      id: "link",
      title: "Connection Link",
      value: connection.text,
      detail: detail(connection, "Physical link"),
      tone: evidenceTone(connection),
    },
    {
      id: "disconnect",
      title: "Safe Disconnect",
      value: presentation.disconnect.text,
      // The approved composition has no card for the running-game or session
      // observations, and both bear directly on whether a disconnect is safe,
      // so they are carried here rather than dropped off the screen.
      detail: [
        presentation.disconnect.reason,
        // Carried through `detail` rather than as raw text: these are
        // observations, and an unverified one must not read as confirmed
        // just because the card it now lives on is already a warning.
        detail(game, `Game: ${game.text}`),
        detail(session, `Session: ${session.text}`),
      ].join(" · "),
      // Always warning. Not derived from the readings above, because no
      // combination of them grants a clearance this product cannot confirm.
      tone: "warning",
      wide: false,
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
}): Tile[] {
  const { state, manualWatts, fps } = input;
  const auto = !state.autoKnown ? { text: "Unknown", tone: "unavailable" as Tone }
    : state.stopping ? { text: "Stopping…", tone: "quiet" as Tone }
    : state.active ? { text: "Running", tone: "active" as Tone }
    : { text: "Off", tone: "quiet" as Tone };
  return [
    missingProvider("profile", "Performance Profile",
      "No performance profile provider exists on this device."),
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
    // This card used to carry the eGPU display-attachment evidence, which
    // reads "Connected" -- a connection fact under a resolution heading. No
    // mode geometry is observed anywhere in the payload, so there is nothing
    // truthful to put here yet.
    missingProvider("display", "Resolution",
      "No display mode is observed; resolution is not reported."),
    missingProvider("refresh", "Refresh Rate",
      "No display mode is observed; refresh rate is not reported."),
  ];
}

/** The controllers tab.
 *
 * `ControllerFact` carries no verified grade, so tone comes from the payload's
 * own `precision`: an `exact` reading may use the confident tone, a `partial`
 * one may not, and `unknown` is unavailable like any other absence.
 */
/** Tone from the payload's own precision: `exact` may use the confident tone,
 * `partial` may not, and `unknown` is unavailable like any other absence. */
function controllerTone(presentation: ControllerPresentation, known: boolean): Tone {
  if (!known || presentation.precision === "unknown") return "unavailable";
  return presentation.precision === "exact" ? "active" : "quiet";
}

function controllerCaveat(presentation: ControllerPresentation, base: string): string {
  return presentation.precisionNote ? `${base} · ${presentation.precisionNote}` : base;
}

/** Quick Access's one-line controller summary.
 *
 * The Controllers tab's `controller` card is Player 1, which has no provider
 * and stays Unknown. Quick's approved card is Controller Status, and PRESENCE
 * is observed -- so it is projected from the same ControllerPresentation
 * rather than inheriting the assignment card's Unknown. Dropping a truthful
 * reading because a different question is unanswerable would be its own kind
 * of dishonesty.
 *
 * It is a projection, not a second opinion: same presentation, same precision
 * rule, so Quick and the Controllers tab cannot disagree about what was
 * observed. The detail says plainly that player order is not established, so
 * the summary never implies it answers the assignment question. */
export function controllerSummaryTile(presentation: ControllerPresentation): Tile {
  const { external, builtin } = presentation;
  const known = external.known || builtin.known;
  const value = external.known ? external.text : builtin.known ? builtin.text : "Unknown";
  return {
    id: "controller",
    title: "Controller Status",
    value,
    detail: presentation.available
      ? controllerCaveat(presentation,
          `External: ${external.text} · Built-in: ${builtin.text} · player order not established`)
      : presentation.reason ?? "No controller reading available",
    tone: controllerTone(presentation, known),
  };
}

export function controllerTiles(presentation: ControllerPresentation): Tile[] {
  const tone = (known: boolean): Tone => controllerTone(presentation, known);
  const caveat = (base: string) => controllerCaveat(presentation, base);
  // The approved card is Player 1, and external presence does not establish
  // Steam's player order -- player order is unimplemented backend-side. The
  // presence reading is real, so it is carried in the detail line rather than
  // promoted into an answer it cannot support.
  const presence = presentation.available
    ? `External controller: ${presentation.external.text}`
    : presentation.reason ?? "No controller reading available";
  return [
    missingProvider("controller", "Player 1",
      caveat(`${presence} · presence does not establish player order`)),
    missingProvider("battery", "Controller Battery",
      "No controller battery reading is reported to Re-Gear."),
    {
      id: "builtin",
      title: "Built-in Controller",
      value: presentation.builtin.text,
      detail: presentation.available
        ? caveat("Reported by the peripheral status")
        : presentation.reason ?? "No controller reading available",
      tone: tone(presentation.builtin.known),
    },
    {
      id: "priority",
      title: "Controller Priority",
      // Named in the plan and not implemented. Stated as unavailable so its
      // absence is explicit rather than a gap a player has to notice, and
      // never rendered as a working control.
      value: "Not available",
      detail: presentation.planned.length > 0
        ? `Planned, not implemented: ${presentation.planned.join(", ")}`
        : "Planned, not implemented.",
      tone: "unavailable",
    },
    missingProvider("tv-controller", "TV Dock Behavior",
      "No TV-dock controller reading is reported to Re-Gear."),
    missingProvider("controller-settings", "Controller Settings",
      "No controller preferences are stored by Re-Gear."),
  ];
}
