import { callable } from "@decky/api";
import { DialogButton, showModal } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { EgpuConfirmModal } from "./egpu-confirm-modal";
import { dockControl, type DockAction } from "./whole-dock-control-model";

const readTrial = callable<[string], any>("get_egpu_disconnect_status");
const readSnapshot = callable<[], any>("get_snapshot");
const execute = callable<[boolean, string, string, DockAction, boolean, string, string], any>("execute_egpu_disconnect");
const pendingKey = "regear.whole-dock.pending-request";
const pendingRequest = () => { try { return window.localStorage.getItem(pendingKey); } catch { return "storage-unavailable"; } };
const read = async () => { const [status, payload] = await Promise.all([readTrial("whole_dock_trial"), readSnapshot()]); return { status, snapshot: payload?.snapshot }; };

/** Only confirmed clicks mutate. Reopening the menu recovers backend progress. */
export function WholeDockControl() {
  const [reading, setReading] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const pending = useRef(false);
  const uncertain = useRef(!!pendingRequest());
  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await read();
        if (!mounted.current) return;
        const request = pendingRequest();
        if (request && next.status?.schema_version === 1 && next.status.request_id === request
            && next.status.busy === false && next.status.safe_to_unplug === false) {
          window.localStorage.removeItem(pendingKey);
          uncertain.current = false;
        }
        setReading(next);
      } catch { if (mounted.current) setReading(null); }
      if (mounted.current) timer = setTimeout(refresh, 2000);
    };
    void refresh();
    return () => { mounted.current = false; clearTimeout(timer); };
  }, []);
  const view = dockControl(reading?.status, reading?.snapshot);
  const confirm = () => {
    const action = view.action;
    const attachment = reading?.status?.attachment_token ?? "";
    if (!action || pending.current || uncertain.current) return;
    pending.current = true; setBusy(true);
    let decided = false;
    const cancel = () => { if (decided) return; decided = true; pending.current = false; if (mounted.current) setBusy(false); };
    const run = async () => {
      if (decided) return;
      decided = true;
      try {
        const fresh = await read();
        if (!mounted.current) return;
        if (dockControl(fresh.status, fresh.snapshot).action !== action
            || (action === "whole_dock_disconnect" && fresh.status?.attachment_token !== attachment)) {
          setReading(fresh); setNotice("Status changed. Review the current reading."); return;
        }
        const request = crypto.randomUUID().replaceAll("-", "");
        window.localStorage.setItem(pendingKey, request);
        uncertain.current = true;
        setNotice("Request sent. Keep the cable connected; Gaming Mode may restart.");
        const result = await execute(true, "", "disconnect", action, true, attachment, request);
        if (mounted.current) { setReading({ ...fresh, status: result }); setNotice(""); }
        if (result?.request_id === request && result?.busy === false && result?.schema_version === 1) {
          window.localStorage.removeItem(pendingKey); uncertain.current = false;
        }
      } catch {
        if (mounted.current) setNotice("The reply was interrupted. Waiting for backend progress; no retry was sent.");
      } finally { pending.current = false; if (mounted.current) setBusy(false); }
    };
    showModal(<EgpuConfirmModal strTitle={action === "whole_dock_disconnect" ? "Disconnect the dock in software?" : "Reconnect the eGPU?"}
      strDescription={action === "whole_dock_disconnect" ? "The TV will turn off and Gaming Mode may restart. Keep the dock cable connected for this trial. This is not permission to unplug." : "Re-Gear will try to restore the connected dock and verify its devices. Keep the cable connected."}
      strOKButtonText={action === "whole_dock_disconnect" ? "Disconnect" : "Reconnect"} strCancelButtonText="Cancel"
      className="rg-whole-dock-confirm" bDestructiveWarning onOK={() => { void run(); }} onCancel={cancel} onEscKeypress={cancel}>
      <style>{`.rg-whole-dock-confirm{z-index:2147483647!important;position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
    </EgpuConfirmModal>, undefined, { fnOnClose: cancel, bNeverPopOut: true });
  };
  return <div>
    <p role="status">{notice || (uncertain.current ? "Waiting to verify the previous request. Keep the cable connected." : view.message)}</p>
    <DialogButton style={{width:"100%",minWidth:0,padding:"10px",border:"1px solid #39d8ff",borderRadius:8,background:"#112434",color:"#f4f7fb"}} disabled={!view.action || busy || uncertain.current} onClick={confirm}>{busy ? "Working…" : view.label}</DialogButton>
    <p>Trial: keep the cable connected. No physical unplug clearance.</p>
  </div>;
}
