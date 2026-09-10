/** Bind the game-close wiring to the real backend and the real Steam client.
 *
 * Deliberately the only thing in this module. `game-close-wiring.ts` holds the
 * gates and takes its effects as an argument, so the gates can be tested
 * against a recording rig without a backend, a Steam session or a device. What
 * is left over is this: a list of which real function answers which port, with
 * no decisions in it. If a decision ever appears here it is in the wrong file.
 *
 * The two reads swallow their own failures into `null` because that is what
 * both callers mean by a failed read: the flow treats null as "not yet" while
 * it waits for a game to close, and the wiring treats it as unknown and
 * refuses. Neither ever reads null as "ready".
 */

import {
  executeEgpuDisconnect,
  getEgpuDisconnectStatus,
  getSleepReadiness,
  rememberGameCloseChoice,
  takePendingRelaunch,
} from "../backend";
import type { DisconnectStatusPayload, SleepReadinessPayload } from "../backend";
import {
  relaunchGame,
  suspendHandheld,
  terminateGame,
} from "../steam-game-control";
import type { GameCloseWiringPorts } from "./game-close-wiring";

export function liveGameClosePorts(): GameCloseWiringPorts {
  return {
    terminateGame,
    relaunchGame,
    // Steam's own suspend. Re-Gear never suspends the machine itself.
    suspend: suspendHandheld,
    async readStatus(): Promise<DisconnectStatusPayload | null> {
      try {
        return await getEgpuDisconnectStatus();
      } catch {
        return null;
      }
    },
    async readSleepReadiness(): Promise<SleepReadinessPayload | null> {
      try {
        return await getSleepReadiness();
      } catch {
        return null;
      }
    },
    disconnect: (releaseDisplay, relaunchAppId, relaunchIntent) =>
      executeEgpuDisconnect(releaseDisplay, relaunchAppId, relaunchIntent),
    takePendingRelaunch: () => takePendingRelaunch(),
    rememberChoice: (appId, skipConfirmation, relaunchAfter) =>
      rememberGameCloseChoice(appId, skipConfirmation, relaunchAfter),
    wait: (ms) =>
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, ms);
      }),
    now: () => Date.now(),
  };
}
