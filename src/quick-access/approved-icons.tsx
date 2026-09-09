/** Mechanical JSX adapters of approved assets/v1; geometry is pinned by tests. */
export type ApprovedIconId = "module-auto-tdp" | "module-egpu" | "module-controller" | "mode-tv-docked";
export function ApprovedIcon({ id, size = 24 }: { id: ApprovedIconId; size?: number }) {
  const props = { width: size, height: size, fill: "none", "aria-hidden": true as const, style: { flexShrink: 0 } };
  switch (id) {
    case "module-auto-tdp": return <svg viewBox="0 0 64 64" {...props}><path d="M13 43a21 21 0 1 1 38 0" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
  <path d="M18 38l4-2M23 27l3 3M32 22v4M41 27l-3 3M46 38l-4-2" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
  <path d="M32 40 43 29" stroke="currentColor" strokeWidth="4" strokeLinecap="round"/>
  <circle cx="32" cy="40" r="4" fill="currentColor"/>
  <path d="M20 49h24" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/></svg>;
    case "module-egpu": return <svg viewBox="0 0 64 64" {...props}><rect x="8" y="14" width="48" height="36" rx="8" stroke="currentColor" strokeWidth="3"/>
  <circle cx="37" cy="32" r="11" stroke="currentColor" strokeWidth="3"/>
  <circle cx="37" cy="32" r="3" fill="currentColor"/>
  <path d="M37 21c4 2 5 5 4 8M48 32c-2 4-5 5-8 4M37 43c-4-2-5-5-4-8M26 32c2-4 5-5 8-4" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
  <path d="M15 24h5M15 32h5M15 40h5" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
  <path d="M20 50v4M44 50v4" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/></svg>;
    case "module-controller": return <svg viewBox="0 0 64 64" {...props}><path d="M19 25h26c5 0 8 3 9 8l3 12c1 5-5 8-8 4l-7-8H22l-7 8c-3 4-9 1-8-4l3-12c1-5 4-8 9-8Z" stroke="currentColor" strokeWidth="3" strokeLinejoin="round"/>
  <path d="M20 31v8M16 35h8" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
  <circle cx="43" cy="33" r="2.5" fill="currentColor"/><circle cx="49" cy="38" r="2.5" fill="currentColor"/></svg>;
    case "mode-tv-docked": return <svg viewBox="0 0 96 64" {...props}><rect x="8" y="10" width="54" height="34" rx="5" stroke="currentColor" strokeWidth="3"/>
  <path d="M30 44v8M20 54h30" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
  <rect x="68" y="19" width="18" height="26" rx="4" stroke="currentColor" strokeWidth="3"/>
  <circle cx="77" cy="31" r="5" stroke="currentColor" strokeWidth="2.5"/>
  <path d="M68 32h-6" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
  <path d="M20 20h30v14H20z" stroke="currentColor" strokeWidth="2.5"/></svg>;
  }
}
