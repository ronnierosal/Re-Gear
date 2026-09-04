import attention from "./assets/offline-readiness/offline-attention.svg";
import verify from "./assets/offline-readiness/offline-verify.svg";
import type { OfflineBadge } from "./offline-badge-state";

export const offlineBadgeImages = { "offline-attention": attention, "offline-verify": verify };

export function OfflineReadinessBadge({ badge }: { badge: OfflineBadge }) {
  return <img src={offlineBadgeImages[badge.asset]} alt={badge.label} title={badge.label}
    width={72} height={32} style={{ display: "block", flexShrink: 0 }} />;
}
