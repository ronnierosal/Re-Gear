import type { ReactNode } from "react";
import { DialogButton } from "@decky/ui";
import { PopupFrame, PopupStateIcon, type PopupState } from "./popup-frame";
export type ConnectionProgressState = "ready" | "checking" | "pending" | "switching" | "blocked" | "error";
export type ConnectionProgressPhase = "connecting" | "switching" | "ready";
export type ConnectionProgressRow = {key:string;label:string;state:ConnectionProgressState;stateLabel?:string;icon?:ReactNode};
export type ConnectionProgressOverlayProps = {
  phase:ConnectionProgressPhase;deviceLabel:string;elapsedSeconds?:number;rows:ConnectionProgressRow[];
  detail?:string;delayNotice?:string;activationNotice?:string;keepConnectedMessage?:string;
  onHide():void;onSwitch?:()=>void;
};
const rowState=(state:ConnectionProgressState):PopupState => state === "ready" ? "ready" : state === "blocked" ? "attention" : state === "error" ? "failed" : state === "switching" || state === "checking" ? "connecting" : "waiting";
export function ConnectionProgressOverlay(props:ConnectionProgressOverlayProps) {
  const primary:PopupState=props.phase === "ready" ? "ready" : props.rows.some(row=>row.state === "error") ? "failed" : props.rows.some(row=>row.state === "blocked") ? "attention" : props.phase === "switching" ? "connecting" : "waiting";
  // The reported reason stays primary; suppress only the monitor's generic
  // duration copy when the explicit duration notice already conveys it.
  const genericDelay=props.delayNotice && /^(Taking longer than expected|Connection hasn.t completed)/.test(props.detail ?? "");
  const elapsed=props.elapsedSeconds;
  const elapsedLabel=elapsed != null && Number.isFinite(elapsed) && elapsed >= 0
    ? `${Math.floor(elapsed/60)}:${String(Math.floor(elapsed%60)).padStart(2,"0")} elapsed` : undefined;
  const currentStep=props.rows.find(row=>row.state === "error" || row.state === "blocked")
    ?? props.rows.find(row=>row.state === "switching" || row.state === "checking" || row.state === "pending");
  return <PopupFrame title="eGPU connection" state={primary} footer={<>
    {props.keepConnectedMessage && <div className="rg-popup-guidance">{props.keepConnectedMessage}</div>}
    <div className="rg-popup-actions">
    <DialogButton onClick={props.onHide}>Hide</DialogButton>
    {props.onSwitch && <DialogButton onClick={props.onSwitch}>Switch to TV</DialogButton>}
    </div>
  </>}>
    <div className="rg-popup-muted">{props.deviceLabel}{elapsedLabel ? ` · ${elapsedLabel}` : ""}</div>
    {currentStep && <p className="rg-popup-current-step">{currentStep.label}: {currentStep.stateLabel ?? (currentStep.state === "switching" ? "Waiting for activation" : "Waiting")}</p>}
    {!genericDelay && props.detail && <p>{props.detail}</p>}
    {props.delayNotice ? <div className="rg-popup-notice">{props.delayNotice}</div> : props.activationNotice && <p className="rg-popup-muted">{props.activationNotice}</p>}
    <details><summary>Connection details</summary>{props.rows.map(row=><div key={row.key} className="rg-popup-row">
      <span>{row.label}</span><span className="rg-popup-row-status"><PopupStateIcon state={rowState(row.state)}/>{row.stateLabel ?? (row.state === "ready" ? "Confirmed" : row.state === "blocked" ? "Needs attention" : row.state === "error" ? "Failed" : "Waiting")}</span>
    </div>)}</details>
  </PopupFrame>;
}
