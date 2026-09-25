import { DialogButton } from "@decky/ui";
import { useRef, type ReactNode } from "react";
import { PopupFrame, PopupStateIcon, type PopupState } from "./popup-frame";
import { CommandCenterIcon } from "./quick-access/command-center-icons";
import handheldIcon from "./assets/mode-handheld.svg";
import tvIcon from "./assets/mode-tv.svg";
import type { MilestoneModel } from "./connection-progress-model";
export type ConnectionProgressState = "ready" | "checking" | "pending" | "switching" | "blocked" | "error";
export type ConnectionProgressPhase = "connecting" | "switching" | "ready";
export type ConnectionProgressRow = {key:string;label:string;state:ConnectionProgressState;stateLabel?:string;icon?:ReactNode};
export type ConnectionProgressOverlayProps = {
  phase:ConnectionProgressPhase;deviceLabel:string;elapsedSeconds?:number;rows:ConnectionProgressRow[];
  detail?:string;delayNotice?:string;activationNotice?:string;keepConnectedMessage?:string;
  onHide():void;onSwitch?:()=>void;
  recoveryAction?:ReactNode;
  milestones?:MilestoneModel;
};
const rowState=(state:ConnectionProgressState):PopupState => state === "ready" ? "ready" : state === "blocked" ? "attention" : state === "error" ? "failed" : state === "switching" || state === "checking" ? "connecting" : "waiting";
const coreLabels=["GPU and driver","Connection link","TV HDMI detected","Audio recovery ready","Display switching ready"];
const unknownMilestones:MilestoneModel={activeStep:-1,observedDone:0,steps:["Detect eGPU","Load GPU driver","Verify connection","Find TV","Prepare and switch display"].map(label=>({label,state:"pending"})),headline:"Waiting for connection",currentDetail:"Waiting for a status update",complete:false,stale:false,attention:false};
const milestoneCopy:Record<string,string>={done:"Done",active:"In progress",pending:"Waiting",attention:"Needs attention",stale:"Last observed"};
export function ConnectionProgressOverlay(props:ConnectionProgressOverlayProps) {
  const details=useRef<HTMLDetailsElement>(null);
  const primary:PopupState=props.phase === "ready" ? "ready" : props.rows.some(row=>row.state === "error") ? "failed" : props.rows.some(row=>row.state === "blocked") ? "attention" : props.phase === "switching" ? "connecting" : "waiting";
  const elapsed=props.elapsedSeconds;
  const elapsedLabel=elapsed != null && Number.isFinite(elapsed) && elapsed >= 0
    ? `${Math.floor(elapsed/60)}:${String(Math.floor(elapsed%60)).padStart(2,"0")}` : undefined;
  const core=coreLabels.map(label=>props.rows.find(row=>row.label===label) ?? {key:label,label,state:"pending" as const});
  const m=props.milestones ?? unknownMilestones;
  // Completion stays the view model's fresh docked + docked_egpu phase.
  const done=props.phase === "ready" && !m.stale;
  const gpuReady=!m.stale && (done || m.activeStep > 2 || core[0].state === "ready" && core[1].state === "ready");
  const tvFound=!m.stale && (done || m.activeStep > 3 || core[2].state === "ready");
  const genericDelay=props.delayNotice && /^(Taking longer than expected|Connection hasn.t completed)/.test(props.detail ?? "");
  const toggleDetails=()=>{if(details.current)details.current.open=!details.current.open;};
  const state:PopupState=m.attention && primary !== "failed" ? "attention" : primary;
  const stateLabel=state === "failed" ? "Connection failed" : m.headline;
  return <PopupFrame title="eGPU Connection" state={state} stateLabel={stateLabel} compact headerMeta={elapsedLabel && <span aria-label={`${elapsedLabel} elapsed`}>{elapsedLabel}</span>} footer={<>
    <DialogButton onClick={props.onHide}><span className="rg-key">B</span> Hide</DialogButton>
    <span className="rg-popup-guidance">{props.keepConnectedMessage}</span>
    {props.onSwitch && <DialogButton onClick={props.onSwitch}>Switch to TV</DialogButton>}
    <DialogButton onClick={toggleDetails}><span className="rg-key">Y</span> Details</DialogButton>
    <div className="rg-popup-recovery">{props.recoveryAction}</div>
  </>}>
    <div className="rg-milestones" data-stale={m.stale} data-complete={m.complete}>
      <div className="rg-milestone-bar" role="progressbar" aria-label="Connection milestones" aria-valuemin={0} aria-valuemax={m.steps.length} aria-valuenow={m.observedDone} aria-valuetext={m.currentDetail}>
        {m.steps.map(step=><span key={step.label} className="rg-milestone-segment" data-state={step.state}/>)}
      </div>
      <div className="rg-milestone-current" title={m.currentDetail}>{m.currentDetail}</div>
      <div className="rg-connection-flow" aria-label="Connection path; device presence and display activation are separate">
        <div className="rg-flow-node"><img src={handheldIcon} alt=""/><span>Handheld</span></div>
        <span className="rg-flow-line" data-ready={gpuReady} data-active={!m.stale && !m.attention && !gpuReady && m.activeStep >= 0}/>
        <div className="rg-flow-node"><CommandCenterIcon id="egpu" size={34}/><span title={props.deviceLabel}>{props.deviceLabel}</span></div>
        <span className="rg-flow-line" data-ready={done} data-active={!m.stale && !m.attention && !done && tvFound}/>
        <div className="rg-flow-node"><img src={tvIcon} alt=""/><span>TV</span><small>{done ? "Switch complete" : tvFound ? "Detected; not active" : "Unconfirmed"}</small></div>
      </div>
      <ol className="rg-milestone-list">
        {m.steps.map(step=><li key={step.label} className="rg-milestone" data-state={step.state}><span className="rg-milestone-dot" aria-hidden="true"/><span className="rg-milestone-label">{step.label}</span><span className="rg-milestone-status">{milestoneCopy[step.state]}</span></li>)}
      </ol>
      <div className="rg-milestone-live" data-live={!m.stale}><span className="rg-live-dot" aria-hidden="true"/>{m.stale ? "Status not updating · last observation shown" : "Live status"}</div>
      {m.slowNotice && <div className="rg-milestone-slow" role="status">{m.slowNotice}</div>}
    </div>
    <details ref={details} className="rg-connection-details"><summary>Connection details</summary><div className="rg-details-scroll" tabIndex={0} aria-label="Connection diagnostics">
      {!genericDelay && <p>{props.detail}</p>}{props.activationNotice && <p>{props.activationNotice}</p>}{props.delayNotice && <p className="rg-delay-inline">{props.delayNotice}</p>}
      {props.rows.map(row=><div key={row.key} className="rg-popup-row"><span>{row.label}</span><span className="rg-popup-row-status"><PopupStateIcon state={rowState(row.state)}/>{row.stateLabel ?? (row.state === "ready" ? "Confirmed" : "Unconfirmed")}</span></div>)}
    </div></details>
  </PopupFrame>;
}
