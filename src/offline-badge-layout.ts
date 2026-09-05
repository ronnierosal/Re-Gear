export type BadgeRect = { left: number; top: number; width: number; height: number };
/** Match the supplied SVG's 80/128 status-circle ratio to Steam's symbol. */
export function offlineBadgeLayout(host: BadgeRect, clientWidth: number, clientHeight: number, icon: BadgeRect, group: BadgeRect = icon) {
  const values = [host.left, host.top, host.width, host.height, clientWidth, clientHeight, icon.left, icon.top, icon.width, icon.height, group.left, group.top, group.width, group.height];
  if (!values.every(Number.isFinite) || Math.min(host.width, host.height, clientWidth, clientHeight, icon.width, icon.height, group.width, group.height) <= 0) return null;
  const sx = host.width / clientWidth, sy = host.height / clientHeight;
  const height = icon.height / sy * 128 / 80;
  if (height < 12 || height > 48) return null;
  const width = height * 2;
  // Stack above Steam on every cover shape, with a four CSS-pixel gap.
  const left = (group.left + group.width - host.left) / sx - width;
  const bottom = (host.top + host.height - group.top) / sy + 4;
  if (left < 0 || bottom < 0 || bottom + height > clientHeight || left + width > clientWidth) return null;
  return { width, height, left, bottom };
}
