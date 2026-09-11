import type { ComponentProps } from "react";
import { ConfirmModal } from "@decky/ui";
import brandIcon from "./assets/regear-icon.svg";

/** Decky retains confirmation, default focus, A/B routing and close semantics. */
export function EgpuConfirmModal({children, className, strTitle, strDescription, ...props}: ComponentProps<typeof ConfirmModal>) {
  return <ConfirmModal {...props} className={[className,"rg-egpu-confirm"].filter(Boolean).join(" ")}
    strTitle={<div className="rg-confirm-header"><div className="rg-confirm-brand"><img src={brandIcon} alt="Re-Gear logo"/>Re-Gear</div><div>{strTitle}</div></div>}>
    <style>{`
      .rg-egpu-confirm{background:linear-gradient(145deg,#112434,#05111b)!important;border:1px solid #467a9b;border-radius:14px;color:#f4f7fb;max-width:94vw;max-height:82vh;box-sizing:border-box}
      .rg-confirm-header{font-size:18px;line-height:1.25}.rg-confirm-brand{display:flex;align-items:center;gap:8px;font-size:12px;color:#a8cbe5;margin-bottom:6px}.rg-confirm-brand img{width:28px;height:28px}
      .rg-confirm-body{max-height:46vh;overflow-y:auto;overscroll-behavior:contain;font-size:13px;line-height:1.4;scrollbar-width:thin}
      .rg-egpu-confirm button:focus-visible,.rg-egpu-confirm button.gpfocus{outline:2px solid #39d8ff;outline-offset:-2px}
    `}</style>
    <div className="rg-confirm-body">{strDescription && <p>{strDescription}</p>}{children}</div>
  </ConfirmModal>;
}
