/** Three separate verdicts about a disconnect: pure, no I/O.
 *
 * They were one, and collapsing them produced two opposite bugs in two days.
 * First the block granted cable clearance outright once the GPU checks passed,
 * which was a claim about a dock none of them had looked at. (The exact wording
 * is deliberately not quoted here: it would then sit in the shipped bundle as a
 * comment and defeat any grep of a built archive, including the audit below.)
 * Then closing that gap by failing one check made *every* verdict false, so a
 * disconnect that worked perfectly told the player Re-Gear could not confirm
 * anything. Safe, and equally untrue.
 *
 * So they are kept apart, and each says exactly what it knows:
 *
 * - `removalVerified` -- the software removal did what it said, and nothing
 *   observed contradicts it. This can and should be true after a good
 *   disconnect. It is what the player just did.
 * - `busAbsenceVerified` -- the system positively attests the eGPU's functions
 *   are gone from the bus. **No v1 status can carry this.**
 *   `live_disconnect.egpu_unavailable` is also emitted when the observation
 *   throws and when attachment identity is missing, so it reports the absence
 *   of an answer, not the absence of a device. Note the asymmetry it turns on:
 *   *presence* can be positively observed, so a status that still reports a
 *   device contradicts the removal and counts against it -- absence simply
 *   cannot be read the same way round.
 * - `cableClearance` -- the whole dock is down and the cable may be pulled.
 *   Requires both of the above *plus* fresh, positive, bound dock teardown
 *   evidence, and is refused unless every one of them holds.
 *
 * WHY THE BINDING, AND NOT JUST A FLAG.
 *
 * A boolean saying "the dock came down" is satisfied by any teardown of any
 * dock at any time, including the one before the player swapped cables. So the
 * evidence has to name the device it is about and the transaction that produced
 * it, and both have to match the removal being reported. Unbound evidence, or
 * evidence bound to a different device or a different transaction, is refused
 * exactly as absent evidence is.
 *
 * The backend does not emit those fields yet. That is deliberate and it is the
 * point: clearance is closed **by construction** rather than by a hardcoded
 * false with a comment, and the shape below states precisely what the backend
 * must attest before it can open. This module can only ever refuse -- it cannot
 * manufacture clearance, and backend approval stays authoritative.
 *
 * If a check cannot be evaluated, it fails. Absent evidence is never a pass:
 * this is the one place in the product where an optimistic default would read
 * as permission to act on hardware.
 *
 * Safety invariant 10 and issue #147 remain the owning contract.
 */

import type { DisconnectOutcomePayload, DisconnectStatusPayload } from "../backend";

export type ClearanceCheck = {
  /** What was checked, in a player's terms. */
  label: string;
  passed: boolean;
  /** What was actually observed. Never a restatement of the label. */
  detail: string;
};

/** A backend attestation that the whole dock came down.
 *
 * Every field is required, and every one of them is a way this can be refused.
 * None of it is emitted today; the type is the contract the backend has to meet
 * before cable clearance can ever be granted.
 */
export type DockTeardownEvidence = {
  /** The dock's USB branch is gone from the bus, positively observed. */
  usbBranchRemoved: boolean;
  /** The Thunderbolt link is deauthorized, positively observed. */
  tunnelDeauthorized: boolean;
  /** Whether the observation behind those two finished. An unfinished look is
   * not an empty branch, and here that difference is somebody's files. */
  scanComplete: boolean;
  /** The device this evidence is about. Must equal the removal's. */
  attachmentBinding: string;
  /** The transaction that produced it. Must equal the removal's. */
  operationId: string;
};

/** What the removal being reported was bound to.
 *
 * Also not emitted by the backend yet. Without it there is nothing for the
 * evidence above to match against, so clearance stays closed.
 */
export type RemovalBinding = {
  attachmentBinding?: string;
  operationId?: string;
};

export type UnplugClearance = {
  /** The software removal did what it said. True after a good disconnect. */
  removalVerified: boolean;
  /** The system positively attests the functions are gone from the bus.
   * No v1 status can carry this, so it is false today. */
  busAbsenceVerified: boolean;
  /** The whole dock is down and the cable may be pulled. Never true today. */
  cableClearance: boolean;
  checks: ClearanceCheck[];
  /** The statement to show, matched to which of the three above hold. */
  statement: string;
  /** Always present. Names what a clean eGPU removal leaves behind. */
  caveat: string;
};

const REMOVED_STATEMENT =
  "The eGPU is detached in software and is no longer rendering. " +
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

/** Whether dock evidence is fresh, positive, and about this exact removal.
 *
 * Split out so the refusal reasons are one flat list rather than a nested
 * condition, and so a reader can see that binding is checked, not assumed.
 */
function teardownDetail(
  evidence: DockTeardownEvidence | null | undefined,
  binding: RemovalBinding | null | undefined,
): { passed: boolean; detail: string } {
  if (!evidence) {
    return {
      passed: false,
      detail: "Not checked. A software removal leaves the dock attached.",
    };
  }
  if (!evidence.scanComplete) {
    return { passed: false, detail: "The dock observation did not finish." };
  }
  if (!evidence.usbBranchRemoved) {
    return { passed: false, detail: "The dock's USB branch is still attached." };
  }
  if (!evidence.tunnelDeauthorized) {
    return { passed: false, detail: "The Thunderbolt link is still authorized." };
  }
  // Binding last, so a reader learns the substantive state of the dock before
  // learning that the evidence did not belong to this removal.
  const device = binding?.attachmentBinding;
  const operation = binding?.operationId;
  if (!device || !operation) {
    return {
      passed: false,
      detail: "This removal reports no device or transaction to bind evidence to.",
    };
  }
  if (!evidence.attachmentBinding || !evidence.operationId) {
    return { passed: false, detail: "The dock evidence names no device or transaction." };
  }
  if (evidence.attachmentBinding !== device) {
    return { passed: false, detail: "The dock evidence is about a different device." };
  }
  if (evidence.operationId !== operation) {
    return { passed: false, detail: "The dock evidence is from a different disconnect." };
  }
  return { passed: true, detail: "The dock's USB branch and Thunderbolt link are down." };
}

export function unplugClearance(
  status: DisconnectStatusPayload | null | undefined,
  outcome: DisconnectOutcomePayload | null | undefined,
  teardown?: DockTeardownEvidence | null,
  binding?: RemovalBinding | null,
): UnplugClearance {
  const removalChecks: ClearanceCheck[] = [];

  // 1. The attempt itself.
  removalChecks.push(check(
    "Removal completed",
    outcome?.ok === true && outcome.released === true,
    !outcome ? "No disconnect has been run."
      : outcome.ok && outcome.released ? "The disconnect reported success."
      : "The disconnect did not report a completed release.",
  ));

  // 2. Not left half attached. This outranks a success flag: a device moved
  //    somewhere it has never been is the worst state to pull a cable from.
  removalChecks.push(check(
    "Device not left half detached",
    outcome != null && outcome.device_disturbed === false,
    !outcome ? "No disconnect has been run."
      : outcome.device_disturbed ? "The device was left partly detached."
      : "The device was not left in a partial state.",
  ));

  // 3. Functions actually came out and stayed out.
  const removedCount = outcome?.removed.length ?? 0;
  const restoredCount = outcome?.restored.length ?? 0;
  removalChecks.push(check(
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
  removalChecks.push(check(
    "Nothing still using the eGPU",
    holders !== null && holders.length === 0 && scanComplete,
    holders === null ? "No current status reading."
      : !scanComplete ? "The check of running processes did not finish."
      : holders.length > 0 ? `Still held by ${holders.length} unit${holders.length === 1 ? "" : "s"}.`
      : "No process is holding the eGPU.",
  ));

  // 5. Re-Gear released its own hold.
  removalChecks.push(check(
    "Re-Gear's device filter disarmed",
    outcome?.filter_disarmed === true,
    outcome?.filter_disarmed === true ? "The filter was disarmed."
      : "The filter was not reported as disarmed.",
  ));

  // 6. The asymmetry that makes this checkable at all: **presence can be
  //    positively observed even though absence cannot.** `unavailable` tells
  //    us nothing either way, but any other availability means the backend
  //    still sees a device -- which contradicts the removal being reported,
  //    and a contradiction is evidence.
  const stillReported = status != null && status.availability !== "unavailable";
  removalChecks.push(check(
    "No eGPU still reported present",
    status != null && !stillReported,
    !status ? "No current status reading."
      : stillReported ? "The system still reports an eGPU present."
      : "The system reports no eGPU, though that alone does not prove absence.",
  ));

  // These six are about the removal, and they are the ones that can pass.
  const removalVerified = removalChecks.every((entry) => entry.passed);

  // 7. Positive bus absence. v1 reports egpu_unavailable for observation
  //    exceptions and for missing attachment identity as well, so it carries
  //    no post-removal proof at all. Closed until the backend attests it.
  const busAbsenceVerified = false;
  const busCheck = check(
    "eGPU absence confirmed on the bus",
    busAbsenceVerified,
    !status ? "No current status reading."
      : "The current status cannot verify that the eGPU is absent from the bus.",
  );

  // 8. The whole dock, bound to this device and this transaction.
  const teardownResult = teardownDetail(teardown, binding);
  const dockCheck = check(
    "Dock USB and Thunderbolt link brought down",
    teardownResult.passed,
    teardownResult.detail,
  );

  const cableClearance =
    removalVerified && busAbsenceVerified && teardownResult.passed;

  return {
    removalVerified,
    busAbsenceVerified,
    cableClearance,
    checks: [...removalChecks, busCheck, dockCheck],
    // Never a clearance branch: `cableClearance` cannot be true while
    // `busAbsenceVerified` is false, and no statement here grants an unplug.
    statement: removalVerified ? REMOVED_STATEMENT : UNVERIFIED_STATEMENT,
    caveat: DOCK_CAVEAT,
  };
}
