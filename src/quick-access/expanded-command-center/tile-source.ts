/** The bridge between the panel's state and the expanded menu: pure, no React,
 * no I/O, no requests.
 *
 * The expanded shell was built against `sampleTiles`, a synthetic set with
 * confident values like "Connected" and "RX 7600M XT" written into it. Those
 * are fine in a prototype and dangerous the moment the menu is connected,
 * because each one reads to a player as a reading of their own device. So this
 * bridge never falls back to them: a tab with nothing observed is supplied with
 * explicit Unknown tiles rather than left absent, because an absent tab is what
 * makes the shell render the confident samples instead.
 *
 * It also does not map readings itself. `tiles.ts` already turns each
 * presentation into tiles, and those presentations already refuse to collapse
 * independent evidence. Re-deriving any of that here would mean maintaining the
 * same safety argument twice, and the copy that drifts is the one nobody reads.
 *
 * ONE SOURCE. `index.tsx` owns snapshot polling. This holds no timer, opens no
 * connection and calls no backend function; it is handed readings and caches
 * the tiles built from them. Anything else would be a second source of truth
 * for state a player acts on, and there are already three snapshot loops in
 * this codebase without adding a fourth.
 *
 * STABLE IDENTITY IS A CORRECTNESS REQUIREMENT, not an optimisation. The native
 * adapter consumes this through `useSyncExternalStore`, which compares the
 * value it is given by reference. If `read()` built a fresh object per call,
 * React would re-render without end. So the cached view is replaced only when
 * `publish` is called, and a test pins it.
 */

import type { Tab, Tile } from "./model";
import { egpuTiles, performanceTiles, controllerTiles } from "./tiles";
import type { Evidence } from "../modules/egpu-presentation";
import type { EgpuPresentation } from "../modules/egpu-presentation";
import type { ControllerPresentation } from "../modules/controller-presentation";
import type { PerformanceState, TileValue } from "../performance-state";
import { fpsTile, wattsValue } from "../performance-state";

export type TileView = Partial<Record<Tab, readonly Tile[]>>;

/** What the panel hands over. Every field may be absent; absent means unknown,
 * never a default that happens to look plausible. */
export type Readings = {
  egpu?: EgpuPresentation | null;
  controller?: ControllerPresentation | null;
  performance?: PerformanceState | null;
  /** The configured power limit, not power draw. */
  manualWatts?: number | null;
  /** False while no observation has been received, or after a failed read.
   * The panel keeps its previous payload on error, so freshness has to be
   * passed in rather than inferred from the payload being non-null. */
  fresh?: boolean;
};

const UNKNOWN_VALUE: TileValue = { text: "Unknown", known: false };

/** A tab that has been observed but has nothing usable still renders tiles, so
 * the shell never falls back to confident sample data. */
function unknownTiles(entries: ReadonlyArray<[string, string]>): Tile[] {
  return entries.map(([id, title]) => ({
    id, title, value: "Unknown", tone: "unavailable" as const,
    detail: "No observation available.",
  }));
}

// IDs must match what tiles.ts emits exactly. The shell resolves the nested
// detail page by id, so a placeholder using a different id would drop the
// player out of the detail view the moment a reading became unknown.
const UNKNOWN_EGPU: ReadonlyArray<[string, string]> = [
  ["egpu", "Connection"], ["render", "Render GPU"],
  ["display", "External display"], ["game", "Game state"],
  ["disconnect", "Safe Disconnect"],
];
const UNKNOWN_PERFORMANCE: ReadonlyArray<[string, string]> = [
  ["manual", "Manual TDP"], ["auto", "Auto TDP"],
  ["fps", "FPS Target"], ["display", "Display context"],
];
const UNKNOWN_CONTROLLERS: ReadonlyArray<[string, string]> = [
  ["controller", "External controller"], ["builtin", "Built-in controller"],
  ["priority", "Controller priority"],
];

/** Settings placeholders.
 *
 * The real shortcut control is supplied natively by the adapter and is not a
 * tile, so it is deliberately absent here. What remains are entries the
 * prototype showed as if they were preferences; they are stated as unavailable
 * rather than dropped, because a control that silently disappears reads as a
 * bug and one that looks configurable but saves nothing is worse.
 */
function settingsTiles(): Tile[] {
  return [
    { id: "appearance", title: "Appearance", value: "Not available",
      tone: "unavailable", detail: "No appearance preference is stored." },
    { id: "diagnostics", title: "Diagnostics", value: "Not available",
      tone: "unavailable", detail: "Diagnostics are configured from the main panel." },
  ];
}

/** The first screen: the readings a player checks mid-game, drawn from the same
 * mapped tiles as their own tabs so the two can never disagree. */
function quickTiles(performance: Tile[], egpu: Tile[], controller: Tile[]): Tile[] {
  const pick = (tiles: Tile[], id: string, title?: string): Tile | null => {
    const found = tiles.find((tile) => tile.id === id);
    return found ? (title ? { ...found, title } : found) : null;
  };
  return [
    pick(performance, "fps"),
    pick(performance, "manual"),
    pick(performance, "auto"),
    pick(egpu, "display", "Display target"),
    pick(egpu, "egpu", "eGPU"),
    pick(controller, "controller", "Controller"),
  ].filter((tile): tile is Tile => tile !== null);
}

/** Build the full view. Every tab is supplied, always. */
export function buildTiles(readings: Readings): TileView {
  const fresh = readings.fresh !== false;

  const egpu = fresh && readings.egpu
    ? egpuTiles(readings.egpu) : unknownTiles(UNKNOWN_EGPU);
  const controller = fresh && readings.controller
    ? controllerTiles(readings.controller) : unknownTiles(UNKNOWN_CONTROLLERS);

  const performance = fresh && readings.performance
    ? performanceTiles({
        state: readings.performance,
        // The configured limit, never a power-draw reading.
        manualWatts: readings.manualWatts === undefined
          ? UNKNOWN_VALUE : wattsValue(readings.manualWatts),
        fps: fpsTile(),
        display: displayEvidence(readings.egpu),
      })
    : unknownTiles(UNKNOWN_PERFORMANCE);

  return {
    quick: quickTiles(performance, egpu, controller),
    performance, egpu, controllers: controller, settings: settingsTiles(),
  };
}

/** The performance tab shows display context; it takes the eGPU reading rather
 * than deriving a second opinion about the same display. */
function displayEvidence(presentation: EgpuPresentation | null | undefined): Evidence {
  return presentation?.displayConnected
    ?? { text: "Unknown", known: false, verified: false };
}

export type TileSource = {
  /** Current tiles. Never throws. Stable by reference between publishes. */
  read(): TileView;
  /** Register a listener; returns its own unsubscribe. */
  subscribe(listener: () => void): () => void;
};

export type TilePublisher = {
  source: TileSource;
  /** Replace the view and notify. Called by the panel that owns the readings. */
  publish(readings: Readings): void;
};

export function createTilePublisher(initial?: Readings): TilePublisher {
  // Starts unknown rather than empty: an empty view would let the shell fall
  // back to sample data before the first reading arrives.
  let view: TileView = buildTiles(initial ?? { fresh: false });
  const listeners = new Set<() => void>();
  return {
    source: {
      read: () => view,
      subscribe(listener) {
        listeners.add(listener);
        return () => { listeners.delete(listener); };
      },
    },
    publish(readings) {
      view = buildTiles(readings);
      // A listener that throws must not stop the others being told.
      for (const listener of [...listeners]) {
        try { listener(); } catch { /* the consumer owns its own failure */ }
      }
    },
  };
}
