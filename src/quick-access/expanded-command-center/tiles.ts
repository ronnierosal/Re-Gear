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

import type { EgpuPresentation, Evidence } from "../modules/egpu-presentation";
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
