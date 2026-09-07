import ready from "./assets/offline-readiness/offline-ready-compact.svg";
import attention from "./assets/offline-readiness/offline-attention-compact.svg";
import verify from "./assets/offline-readiness/offline-verify-compact.svg";
import type { OfflineBadge } from "./offline-badge-state";

export const offlineBadgeImages = { "offline-ready": ready, "offline-attention": attention, "offline-verify": verify };

export function OfflineReadinessBadge({ badge }: { badge: OfflineBadge }) {
  return <img src={offlineBadgeImages[badge.asset]} alt={badge.label} title={badge.label}
    width={24} height={24} style={{ display: "block", flexShrink: 0 }} />;
}
