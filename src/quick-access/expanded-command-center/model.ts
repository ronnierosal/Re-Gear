/** Synthetic presentation only. No production state or hardware requests. */
export const tabs = ["quick", "performance", "egpu", "controllers", "settings"] as const;
export type Tab = typeof tabs[number];
export const tabLabels: Record<Tab, string> = {
  quick: "Quick Access", performance: "Performance", egpu: "eGPU",
  controllers: "Controllers", settings: "Settings",
};
export type Tone = "active" | "unavailable" | "warning" | "quiet";
export type Tile = { id: string; title: string; value: string; detail: string; tone?: Tone; wide?: boolean };
export const sampleTiles: Record<Tab, readonly Tile[]> = {
  quick: [
    { id: "fps", title: "FPS Target", value: "Unavailable", detail: "No provider detected", tone: "unavailable" },
    { id: "manual", title: "Manual TDP", value: "18 W", detail: "Current limit", tone: "active" },
    { id: "auto", title: "Auto TDP", value: "Off", detail: "Configure to start" },
    { id: "display", title: "Display Target", value: "1080p · 60Hz", detail: "Internal Display", tone: "active" },
    { id: "egpu", title: "eGPU Status", value: "Connected", detail: "RX 7600M XT" },
    { id: "controller", title: "Controller Status", value: "External (P1)", detail: "Built-in off" },
    { id: "disconnect", title: "Safe Disconnect", value: "Readiness check required", detail: "Review apps using the eGPU. No unplug clearance.", tone: "warning", wide: true },
  ],
  performance: [
    { id: "manual", title: "Manual TDP", value: "18 W", detail: "View limit configuration", tone: "active" },
    { id: "auto", title: "Auto TDP", value: "Off", detail: "Not configured · Configure to start" },
    { id: "fps", title: "FPS Target", value: "Unavailable", detail: "No provider detected", tone: "unavailable" },
    { id: "display", title: "Display context", value: "1080p · 60 Hz", detail: "Display target is separate from FPS control" },
  ],
  egpu: [
    { id: "egpu", title: "Connection", value: "Connected", detail: "RX 7600M XT · sample identity" },
    { id: "render", title: "Render GPU", value: "Unknown", detail: "Connection does not identify the render GPU", tone: "unavailable" },
    { id: "display", title: "Display target", value: "Internal", detail: "1080p · 60 Hz" },
    { id: "game", title: "Game state", value: "Unknown", detail: "No running-game observation", tone: "unavailable" },
    { id: "disconnect", title: "Safe Disconnect", value: "Readiness check required", detail: "Connection, display and command success do not establish unplug readiness.", tone: "warning", wide: true },
  ],
  controllers: [
    { id: "controller", title: "Player 1", value: "External controller", detail: "Sample assignment" },
    { id: "builtin", title: "Built-in controller", value: "Off", detail: "Sample state · no device operation" },
    { id: "priority", title: "Controller priority", value: "Preview only", detail: "Configuration is not connected", tone: "unavailable" },
  ],
  settings: [
    { id: "appearance", title: "Appearance", value: "Expanded concept", detail: "Prototype placeholder · no preference saved" },
    { id: "diagnostics", title: "Diagnostics", value: "Not connected", detail: "No diagnostics collected in this preview", tone: "unavailable" },
    { id: "about", title: "About", value: "Re-Gear", detail: "Expanded Command Center · synthetic prototype" },
  ],
};

export function nextTab(tab: Tab, direction: -1 | 1): Tab {
  return tabs[(tabs.indexOf(tab) + direction + tabs.length) % tabs.length];
}
export function columnsForWidth(width: number): number {
  return width >= 640 ? 4 : width >= 430 ? 3 : width >= 280 ? 2 : 1;
}
export function restoreTarget(ids: readonly string[], remembered?: string): string | undefined {
  return ids.includes(remembered ?? "") ? remembered : ids[0];
}
export type Cell = { id: string; row: number; column: number; span: number };
/** Same packing as the CSS grid, including the prominent two-column tile. */
export function gridCells(tiles: readonly Tile[], columns: number): Cell[] {
  let row = 0, column = 0;
  return tiles.map(tile => {
    const span = tile.wide ? (columns === 4 ? 2 : columns) : 1;
    if (column + span > columns) { row++; column = 0; }
    const cell = { id: tile.id, row, column, span };
    column += span;
    if (column === columns) { row++; column = 0; }
    return cell;
  });
}
export function moveInGrid(cells: readonly Cell[], id: string, direction: "left" | "right" | "up" | "down"): string | undefined {
  const current = cells.find(cell => cell.id === id) ?? cells[0];
  if (!current) return undefined;
  const horizontal = direction === "left" || direction === "right";
  const sign = direction === "left" || direction === "up" ? -1 : 1;
  const candidates = cells.filter(cell => horizontal
    ? cell.row === current.row && (cell.column - current.column) * sign > 0
    : cell.row === current.row + sign);
  const distance = (cell: Cell) => horizontal ? Math.abs(cell.column - current.column)
    : Math.max(cell.column - (current.column + current.span - 1), current.column - (cell.column + cell.span - 1), 0);
  candidates.sort((a, b) => distance(a) - distance(b) || a.column - b.column);
  return candidates[0]?.id ?? current.id;
}
