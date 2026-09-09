/** Steam's own close, launch and suspend, for the disconnect and sleep flows.
 *
 * These are native interfaces, so they are checked at use time rather than
 * trusted: a Steam update may rename or remove either of them, and a flow that
 * assumed they were there would tell a player their game was closing while
 * nothing happened. Absent means absent, reported as such, never silently
 * treated as done.
 *
 * `TerminateApp` is deliberately called the way the player's own Exit does it,
 * so Steam runs its shutdown and its cloud sync. The second argument is the
 * force flag and it is always false here: forcing would skip exactly the part
 * that saves someone's game, which is the whole reason this flow exists.
 */

type AppsInterface = {
  TerminateApp?(appId: string, force: boolean): unknown;
  RunGame?(gameId: string, launch: string, unknown: number, source: number): unknown;
};

type SystemInterface = {
  SuspendPC?(): unknown;
};

function steamApps(): AppsInterface | null {
  const host = globalThis as unknown as { SteamClient?: { Apps?: AppsInterface } };
  return host?.SteamClient?.Apps ?? null;
}

function steamSystem(): SystemInterface | null {
  const host = globalThis as unknown as {
    SteamClient?: { System?: SystemInterface };
  };
  return host?.SteamClient?.System ?? null;
}

/** Ask Steam to close one app the way its own Exit button does.
 *
 * Rejects when Steam cannot be asked, because the caller has to be able to
 * tell "asked and waiting" from "never asked". It does not wait for the game
 * to be gone: only a fresh backend observation can say that.
 */
export async function terminateGame(appId: string): Promise<void> {
  const apps = steamApps();
  if (typeof apps?.TerminateApp !== "function") {
    throw new Error("SteamClient.Apps.TerminateApp is unavailable");
  }
  // Never force. Forcing skips the shutdown that saves the game.
  await apps.TerminateApp(appId, false);
}

/** Reopen a game this flow closed. */
export async function relaunchGame(appId: string): Promise<void> {
  const apps = steamApps();
  if (typeof apps?.RunGame !== "function") {
    throw new Error("SteamClient.Apps.RunGame is unavailable");
  }
  await apps.RunGame(appId, "", -1, 100);
}

/** Ask Steam to sleep the handheld.
 *
 * Re-Gear never suspends the machine itself. The backend has no suspend
 * adapter and deliberately never gained one: sleeping is the player's own
 * action, performed by the same code path their power button uses. What
 * Re-Gear does is get out of the way first, by releasing the eGPU.
 *
 * Rejects when Steam cannot be asked, so a caller can say the handheld did
 * not sleep rather than leaving a player staring at a screen that stayed on.
 */
export async function suspendHandheld(): Promise<void> {
  const system = steamSystem();
  if (typeof system?.SuspendPC !== "function") {
    throw new Error("SteamClient.System.SuspendPC is unavailable");
  }
  await system.SuspendPC();
}

/** Whether Steam can be asked to sleep the handheld. */
export function steamCanSuspend(): boolean {
  return typeof steamSystem()?.SuspendPC === "function";
}

/** Whether Steam can be asked to close a game at all.
 *
 * A panel uses this to avoid offering a close it cannot perform, rather than
 * discovering it at the moment the player has already committed.
 */
export function steamCanCloseGames(): boolean {
  return typeof steamApps()?.TerminateApp === "function";
}
