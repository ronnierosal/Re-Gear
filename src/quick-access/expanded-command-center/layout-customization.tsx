import type { ReactNode } from "react";
import type { Tab, Tile } from "./model";
import { CommandCenterIcon } from "../command-center-icons";

export type LayoutCustomizationMode = "idle" | "swap" | "move";

export function reorderById<T extends { id: string }>(items: readonly T[], id: string, toIndex: number): T[] {
  const from = items.findIndex(item => item.id === id);
  if (from < 0 || items.length === 0) return [...items];
  const target = Math.max(0, Math.min(items.length - 1, toIndex));
  if (from === target) return [...items];
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(target, 0, moved);
  return next;
}

export function moveTargetIndex(items: readonly { id: string }[], id: string, direction: "left" | "right" | "up" | "down", columns: number): number {
  const index = items.findIndex(item => item.id === id);
  if (index < 0) return -1;
  const cols = Math.max(1, columns);
  const row = Math.floor(index / cols);
  const col = index % cols;
  if (direction === "left") return col > 0 ? index - 1 : index;
  if (direction === "right") return col < cols - 1 && index + 1 < items.length ? index + 1 : index;
  if (direction === "up") return row > 0 ? Math.max(0, index - cols) : index;
  const down = index + cols;
  return down < items.length ? down : index;
}

const customizeStyles = `
@keyframes regearTileJiggle{0%,100%{transform:rotate(-.7deg) translateY(0)}50%{transform:rotate(.7deg) translateY(-1px)}}
[data-layout-customizing=true] .rg-expanded-tile{animation:regearTileJiggle .24s ease-in-out infinite alternate;transform-origin:50% 55%;will-change:transform}
[data-layout-customizing=true] .rg-expanded-tile:nth-child(even){animation-delay:-.12s;animation-direction:alternate-reverse}
[data-layout-customizing=true] .rg-expanded-tile[data-move-selected=true]{animation-duration:.18s;outline:2px solid #39d8ff!important;outline-offset:-2px;box-shadow:0 0 0 1px #39d8ff33,0 0 18px #39d8ff35!important;background:linear-gradient(145deg,#17445b,#09283c)!important}
[data-layout-customizing=true] .rg-expanded-tile[data-move-selected=true]:after{content:'MOVE';position:absolute;right:7px;top:6px;padding:2px 5px;border-radius:999px;background:#39d8ff;color:#042333;font-size:7.5px;font-weight:900;letter-spacing:.35px;z-index:2}
@media(prefers-reduced-motion:reduce){[data-layout-customizing=true] .rg-expanded-tile{animation:none!important}}
`;

export function LayoutCustomizationBanner({ tab, mode, selectedTitle }: { tab: Tab; mode: Exclude<LayoutCustomizationMode,"idle">; selectedTitle?: string }) {
  const moving = mode === "move";
  return <>
    <style>{customizeStyles}</style>
    <div data-layout-customization-banner style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, padding: "7px 9px", border: "1px solid #3d7994", borderRadius: 9, background: "#0b2b3c", color: "#dff7ff", minWidth: 0 }}>
      <span style={{ display: "grid", placeItems: "center", width: 25, height: 25, borderRadius: 7, background: "#0b2232", border: "1px solid #3d7994", color: "#53dfff", flex: "0 0 auto" }}><CommandCenterIcon id={moving ? "quick-actions" : "settings"} size={16}/></span>
      <span style={{ minWidth: 0, flex: 1 }}>
        <strong style={{ display: "block", fontSize: 10.5 }}>{moving ? `Move ${selectedTitle ?? "button"}` : "Customize Quick Access"}</strong>
        <small style={{ display: "block", marginTop: 1, color: "#91b7d1", fontSize: 8.8, lineHeight: 1.25 }}>
          {moving ? "D-pad moves the selected button. A confirms. B cancels. The available buttons do not change on this tab." : "Choose which supported buttons appear in Quick Access. Hold Y on the menu to rearrange buttons."}
        </small>
      </span>
      <span style={{ fontSize: 8.5, color: "#8fb3cc", whiteSpace: "nowrap" }}>{tab === "quick" ? "Quick Access" : "Reorder only"}</span>
    </div>
  </>;
}

export function CustomizationFooterHints({ mode, children }: { mode: LayoutCustomizationMode; children?: ReactNode }) {
  if (mode === "idle") return <>{children}</>;
  return <>
    {mode === "swap" ? <><span><kbd className="rg-expanded-round">A</kbd> Choose</span><span><kbd className="rg-expanded-round">B</kbd> Done</span></> : <><span>D-pad Move</span><span><kbd className="rg-expanded-round">A</kbd> Place</span><span><kbd className="rg-expanded-round">B</kbd> Cancel</span></>}
    {children}
  </>;
}

export function markMoveTile(tile: Tile, selectedId?: string) {
  return tile.id === selectedId ? { "data-move-selected": "true" } : {};
}
