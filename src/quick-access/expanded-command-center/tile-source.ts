import {offlineTabTiles} from "./offline-tab";
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
import { egpuTiles, performanceTiles, controllerTiles, controllerSummaryTile, evidenceTone } from "./tiles";
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
  /** True ONLY for a SNAPSHOT observation recent enough to act on. Gates the
   * eGPU tab, the controller tab and the display target, which are all
   * derived from that one payload. Absent is treated as not fresh: the panel
   * keeps its previous payload on a failed read, and an age check lives with
   * the owner, so anything short of an explicit yes has to fail closed here.
   *
   * It does NOT gate performance. See `performanceFresh`. */
  fresh?: boolean;
  /** True ONLY for a performance reading its own owner still considers live.
   *
   * Performance arrives over a different transport whose schema carries no
   * device observation timestamp, so there is nothing here to age. Its owner
   * bounds the lifetime from the request that fetched it and reports null
   * once that expires.
   *
   * Grading it by `fresh` would mean a power limit that expired minutes ago
   * renders as the current limit because an unrelated GPU sample happened to
   * be recent -- two readings from two transports, one of them vouching for
   * the other. Absent fails closed, the same as `fresh`. */
  performanceFresh?: boolean;
  /** True ONLY for a controller reading its owner still considers live.
   *
   * `PeripheralStatusPayload` carries no observation timestamp at all -- only
   * `schema_version`, `controller` and `audio` -- so unlike the snapshot there
   * is nothing here to age, and unlike performance there is not even a request
   * clock in the payload. This flag therefore means "a reading was received",
   * not "a reading is recent"; the limitation is stated rather than papered
   * over with a timestamp the backend never sent.
   *
   * What it does buy is independence: gating this on `fresh` would blank the
   * controller tab because an unrelated GPU sample aged out, and would equally
   * present a controller reading as current because one happened to be
   * recent. Absent fails closed, the same as `fresh`. */
  controllerFresh?: boolean;
  /** Actual display target -- which panel is being driven -- kept separate
   * from whether an external display is merely attached. */
  displayTarget?: Evidence;
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
// These mirror the approved identity in docs/design/command-center-runtime-
// handoff.md exactly, because the live and unknown views must offer the same
// cards in the same order: a grid that reflows when a reading goes missing
// moves a target under a thumb mid-press.
const UNKNOWN_EGPU: ReadonlyArray<[string, string]> = [
  ["device", "External GPU"], ["dock", "Dock Mode"],
  ["display", "Display Output"], ["render", "Render GPU"], ["link", "Connection Link"],
];

/** The Safe Disconnect card when nothing has been observed.
 *
 * It keeps the one-cell slot and the warning tone it has when readings exist, so
 * the grid does not reflow around the one card a player looks for under
 * pressure, and it keeps saying that no clearance is granted. Unknown readiness
 * is a reason not to act, never an absence of the warning.
 */
function unknownDisconnectTile(): Tile {
  return {
    id: "disconnect", title: "Safe Disconnect", value: "Unknown",
    tone: "warning", wide: false,
    detail: "Readiness has not been observed. Re-Gear cannot confirm a safe disconnect, and this never makes unplugging safe.",
  };
}

/** The compact eGPU summary reports the connection lifecycle, not one of its
 * prerequisites.  In particular, a PCIe link can be up while the GPU driver,
 * television, audio or Gamescope integration is still pending.  Presenting
 * that link as the overall status is the exact conflation the detailed eGPU
 * view exists to avoid. */
function egpuStatusTile(presentation: EgpuPresentation | null | undefined): Tile {
  const lifecycle = presentation?.lifecycle;
  if (!lifecycle?.known) {
    return {
      id: "egpu", title: "eGPU Status", value: "Unknown", tone: "unavailable",
      detail: "No current connection lifecycle observation. Open for separate link, rendering and display details.",
    };
  }
  return {
    id: "egpu", title: "eGPU Status", value: lifecycle.text,
    tone: evidenceTone(lifecycle),
    detail: lifecycle.verified
      ? "Current connection lifecycle. Open for separate link, rendering and display details."
      : "Current connection lifecycle · observed, not verified. Open for separate link, rendering and display details.",
  };
}
const UNKNOWN_PERFORMANCE: ReadonlyArray<[string, string]> = [
  ["profile", "Performance Profile"], ["fps", "FPS Target"],
  ["manual", "Manual TDP"], ["auto", "Auto TDP"],
  ["display", "Resolution"], ["refresh", "Refresh Rate"],
];
const UNKNOWN_CONTROLLERS: ReadonlyArray<[string, string]> = [
  ["controller", "Player 1"], ["battery", "Controller Battery"],
  ["builtin", "Built-in Controller"], ["priority", "Controller Priority"],
  ["tv-controller", "TV Dock Behavior"], ["controller-settings", "Controller Settings"],
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
  const entry = (id: string, title: string, detail: string): Tile =>
    ({ id, title, value: "Not available", tone: "unavailable", detail });
  return [
    entry("quick-actions", "Quick Actions",
      "No customisable action set is stored; the rail has no verified ports."),
    // The real control is the native adapter row, not a tile. The approved
    // composition still carries a card here, so it says where the control is
    // rather than pretending none exists.
    entry("shortcut", "Command Center Shortcut",
      "Configured from the shortcut row above, not from this card."),
    entry("appearance", "Appearance", "No appearance preference is stored."),
    entry("updates", "Updates", "Re-Gear does not check for updates."),
    entry("diagnostics", "Diagnostics", "Diagnostics are configured from the main panel."),
    entry("about", "About Re-Gear", "No build detail is published to this view."),
  ];
}

/** The first screen: the readings a player checks mid-game, drawn from the same
 * mapped tiles as their own tabs so the two can never disagree.
 *
 * Two things here are not a copy of another tab, and both matter.
 *
 * Safe Disconnect keeps its approved one-cell card on Quick Access. Dropping it
 * when readings are missing would remove the one control a player reaches for
 * when something has gone wrong, at the exact moment it went wrong.
 *
 * Display target is an independent observation, not the eGPU tab's "External
 * display" card. That card reports attachment; the target reports which panel
 * is actually being driven. Collapsing them would let a connected-but-inactive
 * television read as the current target, which is the independence rule this
 * codebase keeps for connection, rendering and display.
 */
function quickTiles(
  performance: Tile[], egpu: Tile[], controller: Tile[],
  displayTarget: Evidence | undefined,
  controllerSummary: Tile | null,
  egpuStatus: Tile,
): Tile[] {
  // `as` re-ids a summary card: Quick shows the same reading as another tab
  // under the identity the approved Quick composition gives it, so the two can
  // never disagree about the value while still matching their own contracts.
  const pick = (tiles: Tile[], id: string, title?: string, as?: string): Tile | null => {
    const found = tiles.find((tile) => tile.id === id);
    if (!found) return null;
    return { ...found, ...(title ? { title } : {}), ...(as ? { id: as } : {}) };
  };
  // Graded like every other reading: absent is unavailable, ungraded is
  // quiet and says so, and only `verified` earns the tone a player reads as
  // "this is true right now".
  const target: Tile = {
    id: "display", title: "Display Target",
    value: displayTarget?.known ? displayTarget.text : "Unknown",
    tone: displayTarget ? evidenceTone(displayTarget) : "unavailable",
    detail: !displayTarget?.known
      ? "No display target observation available."
      : displayTarget.verified
        ? "The panel currently being driven."
        : "The panel currently being driven · observed, not verified",
  };
  const disconnect = pick(egpu, "disconnect") ?? unknownDisconnectTile();
  return [
    pick(performance, "fps"),
    pick(performance, "manual"),
    pick(performance, "auto"),
    target,
    egpuStatus,
    // Presence, projected from the same presentation. NOT the Controllers
    // tab's Player 1 card, which is an assignment question with no provider.
    controllerSummary ?? pick(controller, "controller", "Controller Status"),
    // Last, and one cell, matching the approved layout.
    { ...disconnect, wide: false },
  ].filter((tile): tile is Tile => tile !== null);
}

/** Build the full view. Every tab is supplied, always. */
export function buildTiles(readings: Readings): TileView {
  // Fail closed: only an explicit true is fresh.
  const fresh = readings.fresh === true;

  const egpu = fresh && readings.egpu
    ? egpuTiles(readings.egpu)
    : [...unknownTiles(UNKNOWN_EGPU), unknownDisconnectTile()];
  // Its own owner's freshness, never the snapshot's: peripheral status arrives
  // over a different transport and neither may vouch for the other.
  const controllerFresh = readings.controllerFresh === true;
  const controller = controllerFresh && readings.controller
    ? controllerTiles(readings.controller) : unknownTiles(UNKNOWN_CONTROLLERS);

  // Its own owner's freshness, never the snapshot's: these two readings come
  // from different transports and neither may vouch for the other.
  const performanceFresh = readings.performanceFresh === true;
  const performance = performanceFresh && readings.performance
    ? performanceTiles({
        state: readings.performance,
        // The configured limit, never a power-draw reading.
        manualWatts: readings.manualWatts === undefined
          ? UNKNOWN_VALUE : wattsValue(readings.manualWatts),
        fps: fpsTile(),
      })
    : unknownTiles(UNKNOWN_PERFORMANCE);

  return {
    quick: quickTiles(performance, egpu, controller, fresh ? readings.displayTarget : undefined,
      controllerFresh && readings.controller ? controllerSummaryTile(readings.controller) : null,
      egpuStatusTile(fresh ? readings.egpu : null)),
    performance, egpu, controllers: controller, offline: offlineTabTiles, settings: settingsTiles(),
  };
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

/** How old an observation is allowed to be before it stops counting as fresh.
 *
 * The age that matters is when the DEVICE was observed, not when the response
 * reached us. Those differ: a reply can arrive instantly carrying a reading
 * taken minutes ago, and treating receipt as freshness publishes known eGPU and
 * display state from an observation that has since stopped being true. A player
 * acting on that is the failure this whole bridge exists to prevent.
 */
export type ObservationAge = {
  /** True only for an observation that is parseable, not in the future, and
   * still within its lifetime. */
  fresh: boolean;
  /** Milliseconds of lifetime left, for scheduling the next re-check. Zero
   * whenever the observation is not fresh. */
  remainingMs: number;
};

export function observationAge(
  observedAt: string | undefined | null, now: number, maxAgeMs: number,
): ObservationAge {
  if (typeof observedAt !== "string" || observedAt === "") return { fresh: false, remainingMs: 0 };
  const observed = Date.parse(observedAt);
  // An unparseable timestamp is not evidence of recency.
  if (!Number.isFinite(observed)) return { fresh: false, remainingMs: 0 };
  const age = now - observed;
  // A future timestamp means the clocks disagree, and a disagreement is not a
  // reason to trust the reading more than a stale one.
  if (age < 0) return { fresh: false, remainingMs: 0 };
  if (age >= maxAgeMs) return { fresh: false, remainingMs: 0 };
  // The remaining lifetime, so a re-check happens when this observation
  // actually expires rather than a full interval after some unrelated render.
  return { fresh: true, remainingMs: maxAgeMs - age };
}
