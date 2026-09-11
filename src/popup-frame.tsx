import type { ReactNode } from "react";
import { StatusIcon } from "./readiness-row";
import brandIcon from "./assets/regear-icon.svg";

export type PopupState = "connecting" | "waiting" | "ready" | "attention" | "failed";
const stateLabels: Record<PopupState,string> = {connecting:"Connecting",waiting:"Waiting",ready:"Ready",attention:"Action required",failed:"Failed"};
export const popupStyles = `
.rg-popup-host{padding:0!important;background:transparent!important;border:0!important;box-shadow:none!important;max-height:82vh!important;max-width:94vw!important;min-height:0!important;overflow:hidden!important}
.rg-popup{box-sizing:border-box;width:min(440px,94vw);max-height:82vh;display:flex;flex-direction:column;overflow:hidden;border:1px solid #467a9b;border-radius:14px;background:linear-gradient(145deg,#112434,#05111b);color:#f4f7fb;font:13px/1.4 Arial,sans-serif;animation:rg-popup-enter .16s ease-out}
.rg-popup *{box-sizing:border-box}.rg-popup-header,.rg-popup-footer{flex:0 0 auto;padding:10px 12px;min-height:0}
.rg-popup-header{border-bottom:1px solid #294665}.rg-popup-brand{display:flex;align-items:center;gap:8px;color:#a8cbe5;font-size:12px}.rg-popup-brand img{width:28px;height:28px}.rg-popup h2{margin:6px 0 0;font-size:18px;line-height:1.25;overflow-wrap:normal}
.rg-popup-body{flex:1 1 auto;min-height:0;overflow-y:auto;padding:10px 12px;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:#467a9b #05111b}
.rg-popup-footer{display:flex;flex-wrap:wrap;gap:8px;border-top:1px solid #294665}.rg-popup-actions{display:flex;gap:8px;width:100%}.rg-popup-guidance{width:100%;color:#a8cbe5;font-size:12px}.rg-popup-footer button{flex:1;min-width:0;min-height:34px;margin:0;padding:6px 10px;font:inherit;color:#f4f7fb;background:#102d42;border:1px solid #467a9b;border-radius:8px}
.rg-popup button:focus-visible,.rg-popup button.gpfocus,.rg-popup summary:focus-visible{outline:2px solid #39d8ff;outline-offset:-2px}
.rg-popup-primary{display:flex;align-items:center;gap:8px;font-size:16px;font-weight:700;margin-bottom:6px;transition:color .16s ease}.rg-popup-primary[data-state=ready]{color:#87da91}.rg-popup-primary[data-state=attention]{color:#ffc247}.rg-popup-primary[data-state=failed]{color:#ff9c93}
.rg-popup-state-icon{display:inline-flex;flex-shrink:0;color:inherit}.rg-popup-state-icon[data-motion=true]{animation:rg-popup-pulse 1.4s ease-in-out infinite}
.rg-popup-row{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:8px 0;border-bottom:1px solid #294665}.rg-popup-row-status{display:flex;gap:5px;align-items:center;color:#a8cbe5;font-size:12px;max-width:52%;text-align:right}
.rg-popup-muted{color:#a8cbe5}.rg-popup-notice{padding:8px;border:1px solid #bc913c;border-radius:8px;color:#ffc247;margin-top:8px}.rg-popup details{margin-top:10px}.rg-popup summary{cursor:pointer;padding:5px 0}
@keyframes rg-popup-enter{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}@keyframes rg-popup-pulse{50%{opacity:.45}}
@media(prefers-reduced-motion:reduce){.rg-popup,.rg-popup-state-icon{animation:none!important;transition:none!important}}
`;

export function PopupStateIcon({state,motion=false}: {state:PopupState;motion?:boolean}) {
  const mapped=state === "ready" ? "ready" : state === "attention" ? "blocked" : state === "failed" ? "error" : "waiting";
  return <span className="rg-popup-state-icon" data-motion={motion && (state === "connecting" || state === "waiting")} aria-hidden="true"><StatusIcon state={mapped} color={state === "connecting" || state === "waiting" ? "#39d8ff" : undefined}/></span>;
}
/** Fixed chrome, one scrolling region. The native host owns modal lifecycle. */
export function PopupFrame({title,state,children,footer}: {title:ReactNode;state?:PopupState;children:ReactNode;footer:ReactNode}) {
  return <section className="rg-popup">
    <style>{popupStyles}</style>
    <header className="rg-popup-header"><div className="rg-popup-brand"><img src={brandIcon} alt="Re-Gear logo"/><span>Re-Gear</span></div><h2>{title}</h2>
      {state && <div className="rg-popup-primary" data-state={state} role="status"><PopupStateIcon state={state} motion/>{stateLabels[state]}</div>}
    </header>
    <div className="rg-popup-body">
      {children}
    </div>
    <footer className="rg-popup-footer">{footer}</footer>
  </section>;
}
