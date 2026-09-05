export type UiStatus = "ready" | "checking" | "waiting" | "pending" | "switching" | "blocked" | "error" | "unavailable";
export const statusAppearance: Record<UiStatus, {label:string; color:string; motion:boolean}> = {
  ready:{label:"Ready",color:"#87da91",motion:false},
  checking:{label:"Checking",color:"#ffd16b",motion:true},
  waiting:{label:"Waiting",color:"#ffd16b",motion:false},
  pending:{label:"Pending",color:"#95a6b7",motion:false},
  switching:{label:"Switching",color:"#66d9f7",motion:true},
  blocked:{label:"Blocked",color:"#ffd16b",motion:false},
  error:{label:"Error",color:"#ff9c93",motion:false},
  unavailable:{label:"Unavailable",color:"#95a6b7",motion:false},
};
