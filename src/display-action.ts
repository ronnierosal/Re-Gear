/** Presentation only: execution still requires the backend approval token. */
export function displayAction(mode: string | undefined, busy: boolean,
  acknowledgementRequired: boolean, journalBlocked: boolean, shortcutAvailable: boolean) {
  const target = mode === "tv_docked" || mode === "docked_egpu" ? "ally"
    : mode === "portable" ? "tv" : null;
  const reason = busy ? "Wait for the current display request to finish."
    : acknowledgementRequired ? "Acknowledge the prior display transition result below to continue."
    : journalBlocked ? "Resolve the prior operation shown below before switching."
    : !target ? "Current display mode is unverified. Open Troubleshoot to inspect readiness."
    : null;
  return {
    target,
    title: busy ? "Switching…" : target === "ally" ? "Switch to handheld"
      : target === "tv" ? "Switch to TV" : "Display switch unavailable",
    disabled: reason !== null,
    description: reason ?? (shortcutAvailable
      ? "Hold Back/View + Y for 3 seconds to switch."
      : "Checks readiness before switching. Controller shortcut unavailable."),
  };
}
