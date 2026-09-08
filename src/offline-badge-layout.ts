export type BadgeRect = { left: number; top: number; width: number; height: number };
/** Compact gear matches the native symbol height, capped at 24 CSS pixels. */
export function offlineBadgeLayout(host: BadgeRect, clientWidth: number, clientHeight: number, icon: BadgeRect, group: BadgeRect = icon) {
  const values = [host.left, host.top, host.width, host.height, clientWidth, clientHeight, icon.left, icon.top, icon.width, icon.height, group.left, group.top, group.width, group.height];
  if (!values.every(Number.isFinite) || Math.min(host.width, host.height, clientWidth, clientHeight, icon.width, icon.height, group.width, group.height) <= 0) return null;
  const sx = host.width / clientWidth, sy = host.height / clientHeight;
  const height = Math.min(24, icon.height / sy);
  if (height < 12) return null;
  const width = height, left = 6;
  const bottom = (host.top + host.height - icon.top - icon.height / 2) / sy - height / 2;
  if (bottom < 0 || bottom + height > clientHeight || left + width + 4 > (group.left - host.left) / sx) return null;
  return { width, height, left, bottom };
}
