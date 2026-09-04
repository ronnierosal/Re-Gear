/**
 * Pure, transport-free explanation policy for categorical recovery evidence.
 * It neither observes state nor sends a notification.
 */

export type RecoveryExplanationKind = "link" | "sleep" | "portable_recovery";

export interface RecoveryExplanationInput {
  kind: RecoveryExplanationKind;
  state: string;
}

export interface RecoveryExplanationMemory {
  key: string;
}

export interface RecoveryExplanation {
  title: string;
  body: string;
  critical: false;
}

export interface RecoveryExplanationDecision {
  memory: RecoveryExplanationMemory | null;
  explanation: RecoveryExplanation | null;
}

type ExplanationTemplate = [title: string, body: string];

const EXPLANATIONS: Record<RecoveryExplanationKind, Record<string, ExplanationTemplate>> = {
  link: {
    instability_observed: [
      "eGPU link changed",
      "Re-Gear observed a link state change. It is preserving the current setup; review display and controls before changing anything.",
    ],
    evidence_insufficient: [
      "eGPU link needs verification",
      "Re-Gear could not confirm the current link state. It is not drawing a link-quality or removal conclusion.",
    ],
  },
  sleep: {
    portable_verified: [
      "Interrupted sleep request closed",
      "Re-Gear observed the handheld path after restart. Sleep was not continued, and game/session outcome remains unknown.",
    ],
    action_required: [
      "Interrupted sleep needs attention",
      "Re-Gear did not continue sleep or claim handheld recovery. Review the current status before trying again.",
    ],
    unavailable: [
      "Sleep recovery status unavailable",
      "Re-Gear did not continue sleep. Recovery evidence is unavailable.",
    ],
  },
  portable_recovery: {
    portable_fallback_verified: [
      "Handheld fallback observed",
      "Re-Gear observed internal display, input, and audio evidence. This does not claim hardware recovery or game survival.",
    ],
    recovery_incomplete: [
      "Handheld recovery incomplete",
      "Re-Gear observed incomplete fallback evidence. Keep the current setup and review the status.",
    ],
    needs_supervised_diagnosis: [
      "Handheld recovery needs diagnosis",
      "Re-Gear could not reconcile the current recovery evidence. It is not taking a recovery action.",
    ],
  },
};

/**
 * Return one explanation per public kind/state episode. Stable link evidence
 * clears a prior episode silently; an unknown state never leaks a raw code.
 */
export function decideRecoveryExplanation(
  previous: RecoveryExplanationMemory | null,
  input: RecoveryExplanationInput,
): RecoveryExplanationDecision {
  if (input.kind === "link" && input.state === "stable_observed") {
    return { memory: null, explanation: null };
  }
  const template = EXPLANATIONS[input.kind][input.state];
  if (!template) {
    return {
      memory: { key: `${input.kind}:evidence_insufficient` },
      explanation: previous?.key === `${input.kind}:evidence_insufficient`
        ? null
        : {
          title: "Recovery evidence needs verification",
          body: "Re-Gear could not classify the current evidence. It is not taking an action.",
          critical: false,
        },
    };
  }
  const key = `${input.kind}:${input.state}`;
  return {
    memory: { key },
    explanation: previous?.key === key
      ? null
      : { title: template[0], body: template[1], critical: false },
  };
}
