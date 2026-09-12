import { CommandCenterIcon } from "./quick-access/command-center-icons";
import {statusAppearance, type UiStatus} from "./ui-status";
export function StatusIcon({state,color}: {state:UiStatus;color?:string}) {
  const appearance=statusAppearance[state];
  const id=state === "ready" ? "status-ok" : state === "error" ? "status-error" : state === "blocked" ? "status-warning" : "status-unknown";
  return <span className="rg-connection-icon" aria-hidden="true" style={{color:color ?? appearance.color}}>
    <CommandCenterIcon id={id} size={22}/>
  </span>;
}
export function ReadinessRow({label,state,compact=false}: {label:string;state:UiStatus;compact?:boolean}) {
  return <div className="rg-connection-row" style={compact ? {padding:"8px 0",gap:8,fontSize:13} : undefined}>
    <span className="rg-connection-label">{label}</span>
    <span className="rg-connection-state" style={{color:statusAppearance[state].color,fontSize:compact?12:14}}>
      <StatusIcon state={state}/>{statusAppearance[state].label}
    </span>
  </div>;
}
