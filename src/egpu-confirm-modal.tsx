import type { ComponentProps } from "react";
import { ConfirmModal } from "@decky/ui";
import brandIcon from "./assets/regear-icon.svg";

/** Presentation only: native confirmation, cancellation and focus stay with Decky. */
export function EgpuConfirmModal({children, className, ...props}: ComponentProps<typeof ConfirmModal>) {
  return <ConfirmModal {...props} className={[className, "rg-egpu-confirm"].filter(Boolean).join(" ")}>
    <style>{`
      .rg-egpu-confirm { background:linear-gradient(180deg,#06101c,#071322)!important; border:1px solid #39d8ff99; border-radius:22px; color:#f4f7fb; max-width:calc(100vw - 24px); max-height:calc(100vh - 24px); overflow-y:auto; box-sizing:border-box; }
      .rg-egpu-confirm .rg-connection { font-size:13px; line-height:1.4; }
      .rg-egpu-confirm .rg-connection-list { background:#0a1727; border:1px solid #294665; border-radius:14px; padding:0 8px; }
      .rg-egpu-confirm .rg-connection-row { padding:5px 0; }
      .rg-egpu-confirm .rg-connection-ring { animation:none; border:2px solid #9fb1c8; }
      .rg-egpu-confirm .rg-connection-foot { color:#ffc43d; border:1px solid #ffc43d66; border-radius:8px; padding:8px; }
    `}</style>
    <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:12}}>
      <img src={brandIcon} alt="Re-Gear logo" width={40} height={40} style={{flexShrink:0}} />
      <div style={{fontSize:16,fontWeight:800}}>Re-Gear <span style={{fontSize:13,fontWeight:500,color:"#9fb1c8"}}> / eGPU</span></div>
    </div>
    <div style={{background:"linear-gradient(180deg,#0a1727,#0d1b2d)",border:"1px solid #294665",borderRadius:14,padding:10,lineHeight:1.4}}>
      {children}
    </div>
  </ConfirmModal>;
}
