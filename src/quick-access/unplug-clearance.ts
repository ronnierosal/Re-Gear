/** What a completed disconnect actually established: pure, no I/O.
 *
 * This is the block shown after a disconnect, and it exists so that what a
 * player is told is *earned from evidence* rather than asserted, with the exact
 * evidence beside it so it can be argued with.
 *
 * WHAT THESE CHECKS COVER, AND WHAT THEY DO NOT.
 *
 * They cover the eGPU: both PCI functions removed, nothing still holding them,
 * the filter disarmed, and -- decisively -- the bus itself reporting no eGPU
 * connected. That last one is the difference between trusting an action and
 * observing its result, and it is why the removal is a fact about this machine
 * rather than a claim about the design.
 *
 * They do **not** cover the dock. A software removal detaches `0000:08:00.0`
 * and `0000:08:00.1`. It leaves the dock's own Thunderbolt USB controller on a
 * sibling port of the same switch, the bridges above it, and the tunnel itself
 * -- all still enumerated, all still live. Issue #105 records that this exact
 * branch carries uncorrectable ACS violations with `xhci_hcd` unable to
 * recover, against zero on the GPU branch.
 *
 * SO NOTHING HERE CLEARS THE CABLE. An earlier version of this module said
 * "You can now disconnect the eGPU cable" once every check passed. Every one of
 * those checks was about the GPU, so the sentence was a claim about devices
 * none of them had looked at. Safety invariant 10 stands, and issue #147 --
 * whether that invariant covers unplug-while-bound and unplug-after-verified-
 * removal as one operation or two -- is undecided. It is not this module's to
 * decide, and copy is not the place to decide it.
 *
 * The honest answer today is the one below: say what was detached, say what is
 * still attached, and give the player the route that is known to be safe.
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
  "The eGPU is detached in software and the Ally no longer sees it. " +
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

  // 6. The decisive one for the GPU: the bus, not the command. Note what it
  //    does and does not say -- "no eGPU is connected" is a statement about
  //    the graphics device, not about the dock it arrived through.
  const gone = status?.availability === "unavailable"
    && status.code === "live_disconnect.egpu_unavailable";
  checks.push(check(
    "eGPU no longer connected to the system",
    gone,
    !status ? "No current status reading."
      : gone ? "The system reports no eGPU connected."
      : "The system still reports an eGPU present.",
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
