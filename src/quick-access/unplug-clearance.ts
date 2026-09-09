/** Whether the evidence supports disconnecting the eGPU cable: pure, no I/O.
 *
 * This is the gate behind the only screen in Re-Gear that tells a player they
 * may physically disconnect the eGPU. It exists so that statement is *earned
 * from evidence* rather than asserted, and so the exact evidence is shown next
 * to it and can be argued with.
 *
 * WHY THIS IS NOT THE OPERATION INVARIANT 10 FORBIDS.
 *
 * Invariant 10 was written about a live unplug: pulling the cable while the
 * eGPU is bound, with a driver attached and transactions possible. That is the
 * operation with no containment for in-flight DMA, and it stays forbidden.
 *
 * A safe disconnect is a different operation. The sequence removes both PCI
 * functions and verifies they are gone, so by the time a cable is touched
 * there is no bound device left to disconnect from. The checks below are what
 * make that a fact about this machine rather than a claim about the design:
 * clearance is refused unless the system itself reports no eGPU connected.
 *
 * Every check must pass. They are deliberately not collapsed into one boolean
 * from the backend, because a player deciding whether to pull a cable deserves
 * to see which specific facts were established, and because a single opaque
 * flag is impossible to audit when it is wrong.
 *
 * The decisive check is the last one. "Remove ran and returned success" is a
 * statement about a command; "no eGPU is connected" is a statement about the
 * bus. Only the second one justifies touching the cable, and the difference is
 * between trusting an action and observing its result.
 *
 * Scope: the eGPU. NOT the dock as a whole. Issue #105 records an xhci
 * recovery failure on the USB branch, a separate device path that a clean GPU
 * removal says nothing about, so the caveat below is always carried.
 *
 * If a check cannot be evaluated, it fails. Absent evidence is never a pass:
 * this is the one place in the product where an optimistic default would read
 * as permission to act on hardware.
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

const CLEARED_STATEMENT =
  "The eGPU is detached and no longer connected to the Ally. You can now disconnect the eGPU cable.";

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

  // 6. The decisive one: the bus, not the command. This is what makes the
  //    disconnect safe rather than live -- there is nothing bound to pull from.
  const gone = status?.availability === "unavailable"
    && status.code === "live_disconnect.egpu_unavailable";
  checks.push(check(
    "eGPU no longer connected to the system",
    gone,
    !status ? "No current status reading."
      : gone ? "The system reports no eGPU connected."
      : "The system still reports an eGPU present.",
  ));

  const cleared = checks.every((entry) => entry.passed);
  return {
    cleared,
    checks,
    statement: cleared ? CLEARED_STATEMENT : NOT_CLEARED_STATEMENT,
    caveat: DOCK_CAVEAT,
  };
}
