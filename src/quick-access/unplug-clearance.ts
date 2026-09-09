/** Software-removal evidence, without physical cable clearance.
 * The v1 status has no positive post-removal PCI observation. In particular,
 * egpu_unavailable also means observation failed or attachment identity is
 * missing. Neither verifies absence. Dock teardown is separately unverified;
 * safety invariant 10 and issue #147 remain the owning contract.
 */

import type { DisconnectOutcomePayload, DisconnectStatusPayload } from "../backend";

export type ClearanceCheck = {
  /** What was checked, in a player's terms. */
  label: string;
  passed: boolean;
  /** What was actually observed. Never a restatement of the label. */
  detail: string;
};

export type UnplugClearance = {
  /** True when every check about the **eGPU** passed.
   *
   * Deliberately not called `cleared`: it says the GPU removal is verified,
   * which is not the same as the cable being safe to pull, and a field named
   * for the stronger claim is how the two get confused. */
  removalVerified: boolean;
  checks: ClearanceCheck[];
  /** The statement to show. Grants no cable clearance in either branch. */
  statement: string;
  /** Always present. Names what a clean eGPU removal leaves behind. */
  caveat: string;
};

const VERIFIED_STATEMENT =
  "The eGPU is detached in software and the handheld no longer sees it. " +
  "The dock is still connected, so this is not yet clearance to unplug the cable.";

const UNVERIFIED_STATEMENT =
  "Do not disconnect anything yet. Re-Gear could not confirm every check " +
  "below. Shut the handheld down first, then disconnect it.";

const DOCK_CAVEAT =
  "These checks cover the eGPU only. The dock's own USB controller, the bridges " +
  "above it and the Thunderbolt link stay attached after a software removal, and " +
  "nothing here checks them. To disconnect the cable, shut the handheld down first.";

function check(label: string, passed: boolean, detail: string): ClearanceCheck {
  return { label, passed, detail };
}

export function unplugClearance(
  status: DisconnectStatusPayload | null | undefined,
  outcome: DisconnectOutcomePayload | null | undefined,
): UnplugClearance {
  const checks: ClearanceCheck[] = [];

  // 1. The attempt itself.
  checks.push(check(
    "Removal completed",
    outcome?.ok === true && outcome.released === true,
    !outcome ? "No disconnect has been run."
      : outcome.ok && outcome.released ? "The disconnect reported success."
      : "The disconnect did not report a completed release.",
  ));

  // 2. Not left half attached. This outranks a success flag: a device moved
  //    somewhere it has never been is the worst state to pull a cable from.
  checks.push(check(
    "Device not left half detached",
    outcome != null && outcome.device_disturbed === false,
    !outcome ? "No disconnect has been run."
      : outcome.device_disturbed ? "The device was left partly detached."
      : "The device was not left in a partial state.",
  ));

  // 3. Functions actually came out and stayed out.
  const removedCount = outcome?.removed.length ?? 0;
  const restoredCount = outcome?.restored.length ?? 0;
  checks.push(check(
    "PCI functions removed",
    removedCount > 0 && restoredCount === 0,
    removedCount === 0 ? "No functions were reported removed."
      : restoredCount > 0
        ? `${removedCount} removed, but ${restoredCount} were restored again.`
        : `${removedCount} eGPU function${removedCount === 1 ? "" : "s"} removed.`,
  ));

  // 4. Nothing still holds it. An empty holder list is only meaningful with a
  //    completed scan: an unfinished scan that found nothing found nothing.
  const holders = status?.holders ?? null;
  const scanComplete = status?.scan_complete === true;
  checks.push(check(
    "Nothing still using the eGPU",
    holders !== null && holders.length === 0 && scanComplete,
    holders === null ? "No current status reading."
      : !scanComplete ? "The check of running processes did not finish."
      : holders.length > 0 ? `Still held by ${holders.length} unit${holders.length === 1 ? "" : "s"}.`
      : "No process is holding the eGPU.",
  ));

  // 5. Re-Gear released its own hold.
  checks.push(check(
    "Re-Gear's device filter disarmed",
    outcome?.filter_disarmed === true,
    outcome?.filter_disarmed === true ? "The filter was disarmed."
      : "The filter was not reported as disarmed.",
  ));

  // v1 reports egpu_unavailable for observation exceptions and missing
  // attachment identity too. It contains no positive post-removal bus proof.
  // Keep this check closed until the backend exposes that explicit evidence.
  checks.push(check(
    "eGPU no longer connected to the system",
    false,
    !status ? "No current status reading."
      : "The current status cannot verify that the eGPU is absent from the bus.",
  ));

  // Computed before the outstanding check below is appended, rather than over
  // a slice: an index would silently take in whatever a later edit inserts.
  const removalVerified = checks.every((entry) => entry.passed);

  // Named as an outstanding check rather than left out of the list, so a
  // player sees that something is unverified instead of inferring it from
  // prose. It cannot pass until the dock teardown exists and has run, and it
  // is deliberately outside `removalVerified`: the eGPU removal did succeed.
  checks.push(check(
    "Dock USB and Thunderbolt link brought down",
    false,
    "Not checked. A software removal leaves them attached.",
  ));

  return {
    removalVerified,
    checks,
    statement: removalVerified ? VERIFIED_STATEMENT : UNVERIFIED_STATEMENT,
    caveat: DOCK_CAVEAT,
  };
}
