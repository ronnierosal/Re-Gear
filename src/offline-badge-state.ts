import { sanitizeOfflineReasonCodes } from "./offline-readiness-detail.ts";

export type OfflineBadge = { asset: "offline-attention" | "offline-verify"; label: string };

/** Badges for the limited Steam-report source. It cannot certify offline launch. */
export function offlineReportBadge(value: unknown): OfflineBadge | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const report = value as Record<string, unknown>;
  if (report.schema_version !== 1 || !sanitizeOfflineReasonCodes(report.reason_codes).length) return null;
  switch (report.status) {
    case "needs_attention": return { asset: "offline-attention", label: "Offline needs attention" };
    case "online_check_needed": return { asset: "offline-verify", label: "Online check needed" };
    // Ready and Internet required require stronger evidence than this source provides.
    default: return null;
  }
}
