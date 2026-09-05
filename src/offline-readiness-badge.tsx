import ready from "./assets/offline-readiness/offline-ready-gear.svg";
import attention from "./assets/offline-readiness/offline-attention-gear.svg";
import verify from "./assets/offline-readiness/offline-verify-gear.svg";
import type { OfflineBadge } from "./offline-badge-state";

export const offlineBadgeImages = { "offline-ready": ready, "offline-attention": attention, "offline-verify": verify };

export function OfflineReadinessBadge({ badge }: { badge: OfflineBadge }) {
  return <img src={offlineBadgeImages[badge.asset]} alt={badge.label} title={badge.label}
    width={64} height={32} style={{ display: "block", flexShrink: 0 }} />;
}
