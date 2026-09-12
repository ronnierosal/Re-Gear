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
.rg-state-copy{animation:rg-state-change .16s ease-out}@keyframes rg-state-change{from{opacity:.55}to{opacity:1}}
.rg-popup.rg-compact{width:62vw;max-width:94vw;min-height:45vh;max-height:82vh;font:clamp(12px,1.05vw,16px)/1.3 Arial,sans-serif;border-color:#294665;border-radius:12px;background:linear-gradient(145deg,#101e2c,#08131e)}
.rg-compact .rg-popup-header{display:flex;flex-wrap:wrap;align-items:center;gap:3px;padding:3px 12px}.rg-compact .rg-popup-brand img{width:24px;height:24px}.rg-compact .rg-popup-brand span{display:none}.rg-compact h2{margin:0;font-size:clamp(16px,1.45vw,22px)}.rg-popup-meta{margin-left:auto;color:#a8cbe5;font-size:13px;font-variant-numeric:tabular-nums}
.rg-compact .rg-popup-primary{width:100%;justify-content:center;margin:0;font-size:14px;min-height:20px}.rg-compact .rg-popup-body{overflow:visible;padding:2px 12px;flex:1}.rg-connection-flow{display:flex;align-items:center;justify-content:center;gap:10px;padding:0 18px 3px}.rg-flow-node{display:flex;align-items:center;flex-direction:column;min-width:80px;color:#c9dfef;position:relative;font-size:12px}.rg-flow-node img{width:26px;height:24px;object-fit:contain}.rg-flow-node>svg{width:26px;height:24px}.rg-flow-node small{font-size:11px;color:#93adc1}.rg-flow-line{height:2px;flex:1;background:#304b60;max-width:120px;transition:background .16s}.rg-flow-line[data-ready=true]{background:#87da91}.rg-flow-line[data-active=true]{background:#39d8ff;animation:rg-popup-pulse 1.4s ease-in-out infinite}
.rg-progress-cards{display:grid;grid-template-columns:1.05fr 1fr;gap:8px}.rg-step-card,.rg-core-card{background:#112333;border:1px solid #1e3548;border-radius:8px;padding:4px 8px;min-width:0}.rg-card-caption{font-size:10px;letter-spacing:1px;color:#93adc1}.rg-current-copy{font-size:13px;font-weight:600;margin:5px 0;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.rg-step-card small{font-size:11px;color:#93adc1}.rg-core-row{display:flex;justify-content:space-between;gap:5px;font-size:12px;line-height:1.25}.rg-core-result{display:flex;align-items:center;gap:4px;color:#a8cbe5}.rg-core-result svg{width:13px;height:13px}.rg-core-result span:last-child{max-width:95px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rg-delay-inline{font-size:11px;color:#ffc247;margin-top:4px}
.rg-compact details{margin-top:3px}.rg-compact summary{font-size:12px;padding:3px 0}.rg-details-scroll{max-height:22vh;overflow-y:auto;overscroll-behavior:contain;padding-right:6px}.rg-details-scroll:focus-visible{outline:2px solid #39d8ff;outline-offset:-2px}.rg-compact .rg-popup-footer{flex-wrap:nowrap;align-items:center;padding:3px 10px;gap:8px}.rg-compact .rg-popup-footer button{flex:0 0 auto;background:transparent;border-color:transparent;padding:3px 4px;min-height:28px;font-size:12px}.rg-compact .rg-popup-guidance{width:auto;flex:1;text-align:center;font-size:11px}.rg-key{display:inline-flex;border:1px solid #c9dfef;border-radius:50%;width:18px;height:18px;align-items:center;justify-content:center;margin-right:4px}
@media(min-height:650px){.rg-compact .rg-popup-header{padding:12px 16px}.rg-compact .rg-popup-body{padding:10px 16px}.rg-connection-flow{padding:5px 20px 12px}.rg-flow-node img{width:44px;height:40px}.rg-flow-node{font-size:14px}.rg-current-copy{font-size:16px}.rg-core-row{font-size:13px}.rg-step-card,.rg-core-card{padding:10px 12px}.rg-compact .rg-popup-footer{padding:8px 14px}.rg-compact summary{font-size:13px}}
@media(max-width:650px){.rg-state-copy{animation:rg-state-change .16s ease-out}@keyframes rg-state-change{from{opacity:.55}to{opacity:1}}
.rg-popup.rg-compact{width:92vw}.rg-flow-node{min-width:65px}.rg-core-result span:last-child{max-width:70px}}
@media(prefers-reduced-motion:reduce){.rg-flow-line{animation:none!important;transition:none!important}.rg-popup-primary{transition:none!important}.rg-state-copy{animation:none!important}}
`;

export function PopupStateIcon({state,motion=false}: {state:PopupState;motion?:boolean}) {
  const mapped=state === "ready" ? "ready" : state === "attention" ? "blocked" : state === "failed" ? "error" : "waiting";
  return <span className="rg-popup-state-icon" data-motion={motion && (state === "connecting" || state === "waiting")} aria-hidden="true"><StatusIcon state={mapped} color={state === "connecting" || state === "waiting" ? "#39d8ff" : undefined}/></span>;
}
/** Fixed chrome, one scrolling region. The native host owns modal lifecycle. */
export function PopupFrame({title,state,children,footer,compact=false,headerMeta,stateLabel}: {title:ReactNode;state?:PopupState;children:ReactNode;footer:ReactNode;compact?:boolean;headerMeta?:ReactNode;stateLabel?:string}) {
  return <section className={`rg-popup${compact ? " rg-compact" : ""}`}>
    <style>{popupStyles}</style>
    <header className="rg-popup-header"><div className="rg-popup-brand"><img src={brandIcon} alt="Re-Gear logo"/><span>Re-Gear</span></div><h2>{title}</h2><div className="rg-popup-meta">{headerMeta}</div>
      {state && <div className="rg-popup-primary" data-state={state} role="status"><PopupStateIcon state={state} motion/><span key={stateLabel ?? state} className="rg-state-copy">{stateLabel ?? stateLabels[state]}</span></div>}
    </header>
    <div className="rg-popup-body">
      {children}
    </div>
    <footer className="rg-popup-footer">{footer}</footer>
  </section>;
}
