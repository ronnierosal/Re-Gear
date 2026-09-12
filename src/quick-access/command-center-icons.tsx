/** Re-Gear Command Center icon pack.
 * Monochrome currentColor SVGs so focus/state colors remain controlled by the UI.
 * Keep geometry simple and readable at handheld sizes.
 */
export type CommandCenterIconId =
  | "quick-access" | "performance" | "egpu" | "controllers" | "settings"
  | "fps" | "manual-tdp" | "auto-tdp" | "display" | "safe-disconnect"
  | "profile" | "refresh-rate" | "dock-mode" | "connection-link"
  | "battery" | "controller-priority" | "tv-dock" | "controller-settings"
  | "quick-actions" | "shortcut" | "appearance" | "updates" | "diagnostics" | "about"
  | "status-ok" | "status-warning" | "status-error" | "status-unknown";

export function CommandCenterIcon({ id, size = 32 }: { id: CommandCenterIconId; size?: number }) {
  const p = { width: size, height: size, viewBox: "0 0 64 64", fill: "none", "aria-hidden": true as const, style: { flexShrink: 0 } };
  const s = { stroke: "currentColor", strokeWidth: 3.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (id) {
    case "quick-access": return <svg {...p}><path {...s} d="M9 30 32 11l23 19M15 27v26h34V27M26 53V38h12v15"/></svg>;
    case "performance": return <svg {...p}><path {...s} d="M11 44a23 23 0 1 1 42 0M18 38l5-2M24 26l4 4M32 21v6M40 26l-4 4M46 38l-5-2M32 42l12-13"/><circle cx="32" cy="42" r="4" fill="currentColor"/></svg>;
    case "egpu": return <svg {...p}><rect {...s} x="8" y="14" width="48" height="36" rx="7"/><circle {...s} cx="38" cy="32" r="11"/><circle cx="38" cy="32" r="3" fill="currentColor"/><path {...s} d="M38 21c4 2 5 5 4 8M49 32c-2 4-5 5-8 4M38 43c-4-2-5-5-4-8M27 32c2-4 5-5 8-4M15 24h6M15 32h6M15 40h6"/></svg>;
    case "controllers": return <svg {...p}><path {...s} d="M18 24h28c5 0 8 3 9 8l3 13c1 5-5 8-8 4l-8-9H22l-8 9c-3 4-9 1-8-4l3-13c1-5 4-8 9-8Z"/><path {...s} d="M20 30v10M15 35h10"/><circle cx="44" cy="33" r="2.8" fill="currentColor"/><circle cx="50" cy="39" r="2.8" fill="currentColor"/></svg>;
    case "settings": return <svg {...p}><circle {...s} cx="32" cy="32" r="9"/><path {...s} d="M32 8v8M32 48v8M8 32h8M48 32h8M15 15l6 6M43 43l6 6M49 15l-6 6M21 43l-6 6"/><circle {...s} cx="32" cy="32" r="18"/></svg>;
    case "fps": return <svg {...p}><rect {...s} x="15" y="20" width="39" height="30" rx="4"/><path {...s} d="M10 15h39M7 10h37"/><text x="34.5" y="39" textAnchor="middle" fill="currentColor" fontSize="13" fontWeight="800">FPS</text></svg>;
    case "manual-tdp": return <svg {...p}><rect {...s} x="18" y="18" width="28" height="28" rx="5"/><rect {...s} x="25" y="25" width="14" height="14" rx="2"/><path {...s} d="M23 10v8M32 10v8M41 10v8M23 46v8M32 46v8M41 46v8M10 23h8M10 32h8M10 41h8M46 23h8M46 32h8M46 41h8"/></svg>;
    case "auto-tdp": return <svg {...p}><path {...s} d="M49 24A20 20 0 0 0 16 18l-5 6M15 40a20 20 0 0 0 33 6l5-6M11 15v9h9M53 49v-9h-9"/><path d="M26 40 32 23l6 17M28 35h8" {...s}/></svg>;
    case "display": return <svg {...p}><rect {...s} x="8" y="11" width="48" height="34" rx="5"/><path {...s} d="M32 45v9M21 55h22"/></svg>;
    case "safe-disconnect": return <svg {...p}><path {...s} d="M24 8v17M40 8v17M20 22h24v10c0 8-5 14-12 14S20 40 20 32V22ZM32 46v10"/></svg>;
    case "profile": return <svg {...p}><path {...s} d="M10 18h44M10 32h44M10 46h44"/><circle cx="23" cy="18" r="5" fill="currentColor"/><circle cx="42" cy="32" r="5" fill="currentColor"/><circle cx="30" cy="46" r="5" fill="currentColor"/></svg>;
    case "refresh-rate": return <svg {...p}><path {...s} d="M47 20a20 20 0 0 0-31 5M17 15v11h11M17 44a20 20 0 0 0 31-5M47 49V38H36"/></svg>;
    case "dock-mode": return <svg {...p}><rect {...s} x="10" y="17" width="44" height="29" rx="5"/><path {...s} d="M20 46v7M44 46v7M16 54h32M24 26h16M32 26v11"/></svg>;
    case "connection-link": return <svg {...p}><path {...s} d="M25 39 17 47a9 9 0 0 1-13-13l11-11a9 9 0 0 1 13 0M39 25l8-8a9 9 0 0 1 13 13L49 41a9 9 0 0 1-13 0M22 42l20-20"/></svg>;
    case "battery": return <svg {...p}><rect {...s} x="9" y="20" width="42" height="24" rx="4"/><path {...s} d="M51 27h4v10h-4M16 27h20v10H16"/></svg>;
    case "controller-priority": return <svg {...p}><path {...s} d="M12 20h40M20 12l-8 8 8 8M44 44H12M36 36l8 8-8 8"/><circle cx="34" cy="20" r="4" fill="currentColor"/><circle cx="28" cy="44" r="4" fill="currentColor"/></svg>;
    case "tv-dock": return <svg {...p}><rect {...s} x="8" y="11" width="48" height="34" rx="5"/><path {...s} d="M32 45v8M22 54h20M20 30h9l5-6 10 15"/></svg>;
    case "controller-settings": return <svg {...p}><path {...s} d="M16 27h32c5 0 8 3 9 8l2 9c1 5-5 8-8 4l-7-8H20l-7 8c-3 4-9 1-8-4l2-9c1-5 4-8 9-8Z"/><circle {...s} cx="32" cy="34" r="5"/><path {...s} d="M32 22v5M32 41v5M20 34h7M37 34h7"/></svg>;
    case "quick-actions": return <svg {...p}><rect {...s} x="10" y="10" width="18" height="18" rx="4"/><rect {...s} x="36" y="10" width="18" height="18" rx="4"/><rect {...s} x="10" y="36" width="18" height="18" rx="4"/><rect {...s} x="36" y="36" width="18" height="18" rx="4"/></svg>;
    case "shortcut": return <svg {...p}><rect {...s} x="8" y="14" width="48" height="36" rx="7"/><path {...s} d="M18 26h12M24 20v12M39 25h.01M46 32h.01M39 39h.01"/></svg>;
    case "appearance": return <svg {...p}><path {...s} d="M32 8a24 24 0 1 0 0 48h3a5 5 0 0 0 0-10h-3a14 14 0 0 1 0-28c9 0 17 6 20 14"/><circle cx="20" cy="28" r="3" fill="currentColor"/><circle cx="27" cy="19" r="3" fill="currentColor"/><circle cx="17" cy="39" r="3" fill="currentColor"/></svg>;
    case "updates": return <svg {...p}><path {...s} d="M15 24a20 20 0 0 1 34-6l5 6M49 18v8h-8M49 40a20 20 0 0 1-34 6l-5-6M15 46v-8h8"/><path {...s} d="M32 20v24M24 36l8 8 8-8"/></svg>;
    case "diagnostics": return <svg {...p}><path {...s} d="M10 46h44M14 40l9-12 8 7 10-16 9 10"/><circle cx="23" cy="28" r="3" fill="currentColor"/><circle cx="31" cy="35" r="3" fill="currentColor"/><circle cx="41" cy="19" r="3" fill="currentColor"/></svg>;
    case "about": return <svg {...p}><circle {...s} cx="32" cy="32" r="24"/><path {...s} d="M32 28v17M32 20h.01"/></svg>;
    case "status-ok": return <svg {...p}><circle {...s} cx="32" cy="32" r="24"/><path {...s} d="m20 32 8 8 17-18"/></svg>;
    case "status-warning": return <svg {...p}><path {...s} d="M32 8 58 54H6L32 8Z"/><path {...s} d="M32 24v14M32 46h.01"/></svg>;
    case "status-error": return <svg {...p}><circle {...s} cx="32" cy="32" r="24"/><path {...s} d="m23 23 18 18M41 23 23 41"/></svg>;
    case "status-unknown": return <svg {...p}><circle {...s} cx="32" cy="32" r="24"/><path {...s} d="M24 25c1-6 5-9 10-9 6 0 10 4 10 9 0 8-10 8-10 16M34 49h.01"/></svg>;
  }
}
