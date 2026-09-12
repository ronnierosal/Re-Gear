import { DialogButton } from "@decky/ui";
import { useRef, type ReactNode } from "react";
import { PopupFrame, PopupStateIcon, type PopupState } from "./popup-frame";
import { CommandCenterIcon } from "./quick-access/command-center-icons";
import handheldIcon from "./assets/mode-handheld.svg";
import tvIcon from "./assets/mode-tv.svg";
export type ConnectionProgressState = "ready" | "checking" | "pending" | "switching" | "blocked" | "error";
export type ConnectionProgressPhase = "connecting" | "switching" | "ready";
export type ConnectionProgressRow = {key:string;label:string;state:ConnectionProgressState;stateLabel?:string;icon?:ReactNode};
export type ConnectionProgressOverlayProps = {
  phase:ConnectionProgressPhase;deviceLabel:string;elapsedSeconds?:number;rows:ConnectionProgressRow[];
  detail?:string;delayNotice?:string;activationNotice?:string;keepConnectedMessage?:string;
  onHide():void;onSwitch?:()=>void;
  recoveryAction?:ReactNode;
};
const rowState=(state:ConnectionProgressState):PopupState => state === "ready" ? "ready" : state === "blocked" ? "attention" : state === "error" ? "failed" : state === "switching" || state === "checking" ? "connecting" : "waiting";
const coreLabels=["GPU and driver","Connection link","TV HDMI detected","Audio recovery ready","Display switching ready"];
const shortLabels=["GPU / driver","eGPU link","TV detected","Audio recovery","Display setup"];
export function ConnectionProgressOverlay(props:ConnectionProgressOverlayProps) {
  const details=useRef<HTMLDetailsElement>(null);
  const primary:PopupState=props.phase === "ready" ? "ready" : props.rows.some(row=>row.state === "error") ? "failed" : props.rows.some(row=>row.state === "blocked") ? "attention" : props.phase === "switching" ? "connecting" : "waiting";
  const elapsed=props.elapsedSeconds;
  const elapsedLabel=elapsed != null && Number.isFinite(elapsed) && elapsed >= 0
    ? `${Math.floor(elapsed/60)}:${String(Math.floor(elapsed%60)).padStart(2,"0")}` : undefined;
  const core=coreLabels.map((label,i)=>props.rows.find(row=>row.label===label) ?? {key:label,label,state:"pending" as const,stateLabel:"Unavailable"}).map((row,i)=>({...row,shortLabel:shortLabels[i]}));
  const gpuReady=core[0].state === "ready" && core[1].state === "ready";
  const genericDelay=props.delayNotice && /^(Taking longer than expected|Connection hasn.t completed)/.test(props.detail ?? "");
  const current=genericDelay ? "Waiting for the next connection update" : props.detail ?? "Waiting for a status update";
  const toggleDetails=()=>{if(details.current)details.current.open=!details.current.open;};
  const stateLabel=primary === "attention" ? "Action required" : primary === "failed" ? "Connection failed" : props.phase === "switching" ? "Switching display to TV" : props.phase === "ready" ? "TV switch complete" : "Waiting for connection";
  return <PopupFrame title="eGPU Connection" state={primary} stateLabel={stateLabel} compact headerMeta={elapsedLabel && <span aria-label={`${elapsedLabel} elapsed`}>{elapsedLabel}</span>} footer={<>
    <DialogButton onClick={props.onHide}><span className="rg-key">B</span> Hide</DialogButton>
    <span className="rg-popup-guidance">{props.keepConnectedMessage}</span>
    {props.onSwitch && <DialogButton onClick={props.onSwitch}>Switch to TV</DialogButton>}
    <DialogButton onClick={toggleDetails}><span className="rg-key">Y</span> Details</DialogButton>
    <div className="rg-popup-recovery">{props.recoveryAction}</div>
  </>}>
    <div className="rg-connection-flow" aria-label="Connection path; device presence and display activation are separate">
      <div className="rg-flow-node"><img src={handheldIcon} alt=""/><span>Handheld</span></div>
      <span className="rg-flow-line" data-ready={gpuReady}/>
      <div className="rg-flow-node"><CommandCenterIcon id="egpu" size={34}/><span>eGPU</span><small>{gpuReady ? "Link ready" : "Unconfirmed"}</small></div>
      <span className="rg-flow-line" data-active={props.phase === "switching"} data-ready={props.phase === "ready"}/>
      <div className="rg-flow-node"><img src={tvIcon} alt=""/><span>TV</span><small>{props.phase === "ready" ? "Switch complete" : core[2].state === "ready" ? "Detected; not active" : "Unconfirmed"}</small></div>
    </div>
    <div className="rg-progress-cards">
      <div className="rg-step-card"><span className="rg-card-caption">CURRENT STEP</span><div className="rg-current-copy" title={current}>{current}</div><small>{props.deviceLabel}</small>
        {props.delayNotice && <div className="rg-delay-inline" title={props.delayNotice}>Taking longer than expected · See details</div>}
      </div>
      <div className="rg-core-card"><span className="rg-card-caption">STATUS</span>{core.map(row=><div className="rg-core-row" key={row.key}><span>{row.shortLabel}</span><span className="rg-core-result"><PopupStateIcon state={rowState(row.state)}/><span>{row.stateLabel ?? (row.state === "ready" ? "Confirmed" : "Unconfirmed")}</span></span></div>)}</div>
    </div>
    <details ref={details} className="rg-connection-details"><summary>Connection details</summary><div className="rg-details-scroll" tabIndex={0} aria-label="Connection diagnostics">
      {!genericDelay && <p>{props.detail}</p>}{props.activationNotice && <p>{props.activationNotice}</p>}{props.delayNotice && <p className="rg-delay-inline">{props.delayNotice}</p>}
      {props.rows.map(row=><div key={row.key} className="rg-popup-row"><span>{row.label}</span><span className="rg-popup-row-status"><PopupStateIcon state={rowState(row.state)}/>{row.stateLabel ?? (row.state === "ready" ? "Confirmed" : "Unconfirmed")}</span></div>)}
    </div></details>
  </PopupFrame>;
}
