/** Public reason copy only. Never render a backend string as player guidance. */
const GUIDANCE: Record<string, string> = {
  cloud_save_conflict: "Resolve the Steam Cloud conflict for this game before going offline.",
  cloud_save_pending: "Wait for this game's Steam Cloud sync to finish before going offline.",
  game_not_installed: "Install this game on this handheld before going offline.",
  missing_local_content: "Finish installing this game's files before going offline.",
  local_storage_unavailable: "Check that this game's storage is available.",
  install_integrity_unconfirmed: "Check this game's installation in Steam before going offline.",
  update_pending: "Finish this game's update in Steam before going offline.",
  download_pending: "Finish this game's download in Steam before going offline.",
  offline_evidence_game_active: "Close the game, then check again.",
  offline_evidence_game_unknown: "Wait until Steam can confirm no game is running, then check again.",
  offline_evidence_context_changed: "Select the game you want to check and try again.",
  offline_evidence_stale: "This check is out of date. Check the selected game again.",
  third_party_launcher: "Open this game while online to check its launcher requirements.",
  drm: "This game's authorization may need an online check before offline play.",
  anti_cheat: "This game's anti-cheat may need an online check before offline play.",
  game_owned_online_requirement: "Check this game's internet requirements before going offline.",
  steam_entitlement_unknown: "Offline authorization could not be confirmed. Test this game in Steam Offline Mode before relying on it.",
  cloud_save_unknown: "Cloud save status could not be confirmed. Check this game's sync status in Steam.",
  install_unknown: "Local installation could not be confirmed. Check this game in Steam.",
  download_state_unknown: "Update status could not be confirmed. Check this game's downloads in Steam.",
  offline_evidence_source_unreviewed: "Offline checks are not available for this source yet.",
  offline_evidence_privacy_unreviewed: "Offline checks are not available for this source yet.",
  offline_evidence_cost_unbenchmarked: "Offline checks are not available for this source yet.",
  offline_evidence_cost_exceeds_budget: "The check could not finish within its performance limit. Check this game in Steam.",
  offline_evidence_unavailable: "This game's status is unavailable. Check it in Steam or try again.",
  local_readiness_confirmed: "Offline play is not guaranteed. Try this game in Steam Offline Mode before relying on it away from Wi-Fi.",
};

export function sanitizeOfflineReasonCodes(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 16) return [];
  return [...new Set(value.filter((item): item is string =>
    typeof item === "string" && Object.hasOwn(GUIDANCE, item)))];
}

export function offlineReadinessDetail(reasons: unknown): string | undefined {
  const allowed = new Set(sanitizeOfflineReasonCodes(reasons));
  // Preserve priority even if a transport changes the order of reason codes.
  const reason = Object.keys(GUIDANCE).find((key) => allowed.has(key));
  return reason === undefined ? undefined : GUIDANCE[reason];
}
