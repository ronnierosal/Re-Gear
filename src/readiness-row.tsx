import {statusAppearance, type UiStatus} from "./ui-status";
export function StatusIcon({state}: {state:UiStatus}) {
  const appearance=statusAppearance[state];
  return <span className="rg-connection-icon" aria-hidden="true" style={{color:appearance.color}}>
    {state === "ready" ? <svg className="rg-connection-check" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="10"/><path d="m7 12 3 3 7-7"/></svg>
      : state === "blocked" || state === "error" ? <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M12 3 22 21H2Z M12 9v5 M12 17v1"/></svg>
      : appearance.motion ? <span className="rg-connection-ring"/> : <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="9"/></svg>}
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
