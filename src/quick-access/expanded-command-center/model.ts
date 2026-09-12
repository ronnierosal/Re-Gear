/** Synthetic presentation only. No production state or hardware requests. */
export const tabs = ["quick", "performance", "egpu", "controllers", "settings"] as const;
export type Tab = typeof tabs[number];
export const tabLabels: Record<Tab, string> = {
  quick: "Quick Access", performance: "Performance", egpu: "eGPU",
  controllers: "Controllers", settings: "Settings",
};
export type Tone = "active" | "unavailable" | "warning" | "quiet";
export type Tile = { id: string; title: string; value: string; detail: string; tone?: Tone; wide?: boolean };

/**
 * Approved UI-only sample compositions. These are visual/navigation fixtures,
 * never production fallbacks. Runtime owners replace values with observed state
 * and keep unavailable/unknown explicit when an adapter is absent.
 */
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
    { id: "profile", title: "Performance Profile", value: "Balanced", detail: "Per-mode performance preferences", tone: "active" },
    { id: "fps", title: "FPS Target", value: "Unavailable", detail: "No verified provider", tone: "unavailable" },
    { id: "manual", title: "Manual TDP", value: "18 W", detail: "Current power limit", tone: "active" },
    { id: "auto", title: "Auto TDP", value: "Off", detail: "Configure target and limits" },
    { id: "display", title: "Resolution", value: "1080p", detail: "Current display target" },
    { id: "refresh", title: "Refresh Rate", value: "60 Hz", detail: "Observed display refresh" },
  ],
  egpu: [
    { id: "device", title: "External GPU", value: "Connected", detail: "RX 7600M XT · sample identity", tone: "active" },
    { id: "dock", title: "Dock Mode", value: "TV Docked", detail: "Current Re-Gear mode" },
    { id: "display", title: "Display Output", value: "TV", detail: "1080p · 60 Hz" },
    { id: "render", title: "Render GPU", value: "Unknown", detail: "Connection alone does not identify rendering", tone: "unavailable" },
    { id: "link", title: "Connection Link", value: "Available", detail: "Transport details when observed" },
    { id: "disconnect", title: "Safe Disconnect", value: "Readiness check required", detail: "Connection, display and command success do not establish unplug readiness.", tone: "warning", wide: true },
  ],
  controllers: [
    { id: "controller", title: "Player 1", value: "External controller", detail: "Current assignment" },
    { id: "battery", title: "Controller Battery", value: "Unknown", detail: "Battery shown only when observed", tone: "unavailable" },
    { id: "builtin", title: "Built-in Controller", value: "Off", detail: "Current handheld controller state" },
    { id: "priority", title: "Controller Priority", value: "External first", detail: "Player assignment preference" },
    { id: "tv-controller", title: "TV Dock Behavior", value: "Automatic", detail: "Controller behavior while docked" },
    { id: "controller-settings", title: "Controller Settings", value: "Open", detail: "More controller preferences" },
  ],
  settings: [
    { id: "quick-actions", title: "Quick Actions", value: "4 actions", detail: "Choose supported right-rail shortcuts" },
    { id: "shortcut", title: "Command Center Shortcut", value: "Configured", detail: "Choose how Re-Gear opens" },
    { id: "appearance", title: "Appearance", value: "Re-Gear", detail: "Approved Command Center presentation" },
    { id: "updates", title: "Updates", value: "Unknown", detail: "Update state when a verified source exists", tone: "unavailable" },
    { id: "diagnostics", title: "Diagnostics", value: "Available", detail: "Support and troubleshooting details" },
    { id: "about", title: "About Re-Gear", value: "Project info", detail: "Version, licenses and project details" },
  ],
};

export function nextTab(tab: Tab, direction: -1 | 1): Tab {
  return tabs[(tabs.indexOf(tab) + direction + tabs.length) % tabs.length];
}
export function columnsForWidth(width: number): number {
  return width >= 400 ? 4 : width >= 300 ? 3 : width >= 280 ? 2 : 1;
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
