export type BadgeRect = { left: number; top: number; width: number; height: number };
/** The supplied SVG's status circle is 80 units high in a 128-unit canvas. */
export function offlineBadgeLayout(host: BadgeRect, clientWidth: number, clientHeight: number, icon: BadgeRect, reservedLeft = icon.left - icon.width * 1.5) {
  const values = [host.left, host.top, host.width, host.height, clientWidth, clientHeight, icon.left, icon.top, icon.width, icon.height];
  if (!values.every(Number.isFinite) || Math.min(host.width, host.height, clientWidth, clientHeight, icon.width, icon.height) <= 0) return null;
  const sx = host.width / clientWidth, sy = host.height / clientHeight;
  const height = icon.height / sy * 128 / 80;
  if (height < 12 || height > 48) return null;
  const width = height * 2;
  const left = 6;
  let bottom = (host.top + host.height - icon.top - icon.height / 2) / sy - height / 2;
  if (bottom < 0 || bottom + height > clientHeight) return null;
  // Preserve matching size on unusually narrow tiles by moving above the
  // native badge rather than overlapping its controls or shrinking our icon.
  if (left + width + 4 > (reservedLeft - host.left) / sx)
    bottom = (host.top + host.height - icon.top) / sy + 4;
  if (bottom + height > clientHeight || left + width > clientWidth) return null;
  return { width, height, left, bottom };
}
