/** Software removal evidence is not physical cable clearance.
 * The v1 status contract uses egpu_unavailable for observation failures as well
 * as missing attachment identity. It cannot attest that every PCI function is
 * absent. Keep clearance closed pending an explicit verified backend contract
 * and the recorded safety decision in issue #147. No hardware authority here.
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
  /** True only when every check passed. */
  cleared: boolean;
  checks: ClearanceCheck[];
  /** The statement to show. Grants nothing unless `cleared`. */
  statement: string;
  /** Always present. A clean eGPU removal says nothing about the USB branch. */
  caveat: string;
};

const NOT_CLEARED_STATEMENT =
  "Do not disconnect the eGPU yet. Re-Gear could not confirm every check below. Shut the handheld down first, then disconnect it.";

const DOCK_CAVEAT =
  "This covers the eGPU only. Other devices behind the dock, such as USB controllers and storage, are not checked here.";

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

  // 6. No v1 status code positively attests PCI absence. In particular,
  // egpu_unavailable also covers an exception while observing the device.
  checks.push(check(
    "eGPU no longer connected to the system",
    false,
    "The current status cannot verify physical disconnect readiness.",
  ));

  const cleared = checks.every((entry) => entry.passed);
  return {
    cleared,
    checks,
    statement: NOT_CLEARED_STATEMENT,
    caveat: DOCK_CAVEAT,
  };
}
