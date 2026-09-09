import { ApprovedIcon } from "./approved-icons";
import { DialogButton, Focusable } from "@decky/ui";
import type { CommandCenterTile, TileId } from "./command-center";
import { TILE_COLUMNS } from "./command-center";
import type { HealthPresentation } from "./health-presentation";

/** Command Center first screen: rendering only, no policy, no requests.
 *
 * Which tiles exist, whether they are usable, what they say and what pressing
 * one means all come from command-center.ts. This file cannot disagree with
 * that model, and it performs no operation of its own.
 *
 * Two columns at roughly 268px of information width. Tiles keep a fixed size
 * and a fixed position: an unusable tile is dimmed and still focusable rather
 * than removed, so a target never moves under a player's thumb when a snapshot
 * arrives. Native left/right and up/down traversal is supplied by the
 * Focusable grid; stepGrid models the same movement for tests.
 */

const C = {
  cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca",
  border: "#294665", amber: "#ffc247", dim: "#5d7a99",
};

const SURFACE = "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))";

/** Health tone to colour. The model names no colours, so the mapping lives
 * here and the palette can change without touching the model. */
const TONE_COLOR: Record<HealthPresentation["tone"], string> = {
  quiet: C.muted, progress: C.cyan, attention: C.amber, unknown: C.dim,
};

/** Compact status header. A healthy system says only "Ready" and stops. */
export function CommandCenterStatus({ health, placement, game }: {
  health: HealthPresentation; placement: string; game?: string;
}) {
  return <div style={{ margin: "0 2px 10px", color: C.text, minWidth: 0 }}>
    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
      <span style={{ fontSize: 15, fontWeight: 760 }}>{placement}</span>
      <span style={{ fontSize: 12, color: TONE_COLOR[health.tone] }}>{health.textEquivalent}</span>
      {game && <span style={{ fontSize: 12, color: C.muted }}>{game}</span>}
    </div>
    {/* Quiet when healthy: a reassurance nobody asked for costs the same room
        as a warning somebody needs. */}
    {!health.quiet && health.reasons.slice(0, 2).map((reason) => (
      <div key={reason} style={{ fontSize: 12, lineHeight: "16px", color: C.amber, marginTop: 2 }}>
        {reason}
      </div>
    ))}
    {health.placementReasons.slice(0, 1).map((reason) => (
      <div key={reason} style={{ fontSize: 12, lineHeight: "16px", color: C.muted, marginTop: 2 }}>
        {reason}
      </div>
    ))}
  </div>;
}

function Tile({ tile, onActivate }: {
  tile: CommandCenterTile; onActivate(id: TileId): void;
}) {
  const usable = tile.available;
  return <DialogButton
    className="rg-quick-control"
    data-regear-tile={tile.id}
    data-regear-focus={`tile:${tile.id}`}
    onClick={() => onActivate(tile.id)}
    // Unusable tiles stay focusable: pressing one is how its reason is read.
    aria-label={`${tile.title}: ${tile.value.text}`}
    style={{
      minWidth: 0, width: "auto", minHeight: 112, margin: 0, padding: "8px 10px",
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", gap: 6, textAlign: "center", borderRadius: 12,
      background: SURFACE,
      border: `1px solid ${usable ? C.border : "#22374f"}`,
      color: usable ? C.text : C.dim,
      opacity: 1,
    }}>
    <ApprovedIcon id={tile.id === "display" ? "mode-tv-docked" : tile.id === "safe-disconnect" ? "module-egpu" : "module-auto-tdp"} />
    <span style={{ fontSize: 18, fontWeight: 700, order: 0,
      color: tile.developmental ? C.amber : tile.value.known ? C.cyan : C.muted,
      whiteSpace: "normal", overflowWrap: "anywhere", maxWidth: "100%" }}>
      {tile.value.text}
    </span>
    <span style={{ fontSize: 12, color: C.text, whiteSpace: "normal", maxWidth: "100%" }}>
      {tile.title}
    </span>
    {tile.actionLabel && (
      <span style={{ fontSize: 11, color: C.muted }}>{tile.actionLabel}</span>
    )}
  </DialogButton>;
}

export function CommandCenterGrid({ tiles, onActivate }: {
  tiles: CommandCenterTile[]; onActivate(id: TileId): void;
}) {
  return <Focusable
    style={{
      display: "grid",
      gridTemplateColumns: `repeat(${TILE_COLUMNS}, minmax(0, 1fr))`,
      gap: 8, minWidth: 0, marginBottom: 10,
    }}
    // Native two-dimensional traversal: left/right within a row, up/down
    // between rows. The lone fifth tile is reachable from either cell above.
    flow-children="grid"
  >
    {tiles.map((tile) => <Tile key={tile.id} tile={tile} onActivate={onActivate} />)}
  </Focusable>;
}

/** Reason for the tile a player just selected, shown under the grid rather
 * than inside it so tile heights stay uniform and the grid does not reflow. */
export function TileReason({ tile }: { tile: CommandCenterTile | undefined }) {
  if (!tile || !tile.reason) return null;
  return <div style={{ margin: "0 2px 10px", fontSize: 12, lineHeight: "16px", color: C.amber }}>
    {tile.reason}
  </div>;
}
