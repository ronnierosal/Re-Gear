/** Local clues, not proof of DRM authorization or complete game-file integrity. */
export type OfflinePreparation = {
  buildId: number | null;
  hasLocalContent: boolean | null;
  subscribed: boolean | null;
  thirdParty: boolean | null;
  displayStatus: number | null;
  cloudStatus: number | null;
  cloudAvailable: boolean | null;
  cloudEnabledAccount: boolean | null;
  cloudEnabledApp: boolean | null;
  internetSingleplayer: boolean | null;
  internetSetup: boolean | null;
};

export type OfflineConfidence = {
  status: "needs_preparation" | "likely_offline_ready" | "tested_offline" | "unverified";
  label: string;
  reasons: string[];
  canConfirm: boolean;
};

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}
function boolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}
function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

/** Explicit allowlist: never retain account, game identity, paths, or free text. */
export function projectOfflinePreparation(raw: unknown): OfflinePreparation {
  const source = record(raw);
  const derived = record(source.deckDerivedProperties);
  const build = integer(source.nBuildID);
  return {
    buildId: build !== null && build > 0 ? build : null,
    hasLocalContent: boolean(source.bHasAnyLocalContent),
    subscribed: boolean(source.bIsSubscribedTo),
    thirdParty: boolean(source.bIsThirdPartyUpdater),
    displayStatus: integer(source.eDisplayStatus),
    cloudStatus: integer(source.eCloudStatus),
    cloudAvailable: boolean(source.bCloudAvailable),
    cloudEnabledAccount: boolean(source.bCloudEnabledForAccount),
    cloudEnabledApp: boolean(source.bCloudEnabledForApp),
    internetSingleplayer: boolean(derived.requires_internet_for_singleplayer),
    internetSetup: boolean(derived.requires_internet_for_setup),
  };
}

export function assessOfflineConfidence(
  preparation: OfflinePreparation, installed: unknown, tested: boolean = false, singleplayer: unknown = null,
): OfflineConfidence {
  const p = preparation;
  const blockers: string[] = [];
  const unknowns: string[] = [];
  const ready: string[] = [];
  const display = p.displayStatus;
  if (installed === false || p.hasLocalContent === false || display === 9 || display === 10)
    blockers.push("Install the game before offline play.");
  if ([3, 6, 7, 18, 19, 20, 21, 22, 23, 24, 25, 38, 39].includes(display as number))
    blockers.push("Finish pending downloads or updates.");
  if (p.subscribed === false || display === 26 || display === 27)
    blockers.push("Steam license needs attention online.");
  if (display === 34 || display === 35 || [4, 5, 6, 7, 8, 9, 10].includes(p.cloudStatus as number))
    blockers.push("Resolve pending or failed cloud-save synchronization.");
  if (p.internetSingleplayer === true)
    blockers.push("Steam reports internet is required for single-player play.");
  if (p.internetSetup === true)
    blockers.push("Steam reports an internet setup requirement; completion is unverified.");
  if (p.thirdParty === true)
    blockers.push("A third-party launcher needs a separate offline check.");

  if (installed !== true) unknowns.push("Local installation is not confirmed.");
  if (p.hasLocalContent !== true) unknowns.push("Local game content is not confirmed.");
  if (!(typeof p.buildId === "number" && Number.isSafeInteger(p.buildId) && p.buildId > 0))
    unknowns.push("Installed game version is unknown.");
  if (display !== 11) unknowns.push("Steam has not reported the game ready to launch.");
  else ready.push("Steam reports ready to launch with no pending download reported.");
  if (p.subscribed !== true) unknowns.push("Steam subscription is not confirmed.");
  const cloudDisabled = p.cloudAvailable === false || p.cloudEnabledAccount === false || p.cloudEnabledApp === false;
  const cloudSynced = p.cloudStatus === 3 && p.cloudAvailable === true &&
    p.cloudEnabledAccount === true && p.cloudEnabledApp === true;
  if (!cloudDisabled && !cloudSynced) unknowns.push("Cloud-save preparation is unknown.");
  else ready.push(cloudDisabled ? "Steam Cloud is unavailable or disabled; this does not verify save freshness." : "Steam reports cloud saves synchronized.");
  if (installed === true && p.hasLocalContent === true) ready.unshift("Installation and local content are reported present; file integrity is not verified.");

  const canConfirm = blockers.length === 0 && unknowns.length === 0;
  if (blockers.length) return { status: "needs_preparation", label: "Needs preparation", reasons: blockers, canConfirm: false };
  if (tested === true && canConfirm) return {
    status: "tested_offline", label: "Tested offline", canConfirm,
    reasons: ["You confirmed offline gameplay for this installed version.", ...ready, "A previous test does not guarantee future offline authorization."],
  };
  if (singleplayer !== true) unknowns.push("Single-player support is not confirmed by Steam categories.");
  if (p.thirdParty !== false) unknowns.push("Third-party launcher requirements are unknown.");
  if (p.internetSingleplayer !== false) unknowns.push("Offline single-player compatibility is unverified.");
  if (p.internetSetup !== false) unknowns.push("Internet setup requirements are unverified.");
  if (canConfirm && unknowns.length === 0) return {
    status: "likely_offline_ready", label: "Likely offline-ready", canConfirm,
    reasons: [...ready, "Steam compatibility metadata reports no internet requirement for single-player or setup.", "Offline license authorization is not guaranteed."],
  };
  return { status: "unverified", label: "Unverified", canConfirm, reasons: [...ready, ...unknowns] };
}
