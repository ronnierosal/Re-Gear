/** Steam's own close and launch, for the disconnect flow.
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

function steamApps(): AppsInterface | null {
  const host = globalThis as unknown as { SteamClient?: { Apps?: AppsInterface } };
  return host?.SteamClient?.Apps ?? null;
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

/** Whether Steam can be asked to close a game at all.
 *
 * A panel uses this to avoid offering a close it cannot perform, rather than
 * discovering it at the moment the player has already committed.
 */
export function steamCanCloseGames(): boolean {
  return typeof steamApps()?.TerminateApp === "function";
}
