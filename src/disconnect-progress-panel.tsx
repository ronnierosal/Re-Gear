import { useEffect, useState } from "react";
import { ConfirmModal, showModal } from "@decky/ui";
import { getSnapshot, type SnapshotPayload } from "./backend";
import { disconnectProgress } from "./disconnect-progress";
import { connectionPanelCss } from "./connection-panel-style";
import { ReadinessRow } from "./readiness-row";
function DisconnectPanel({close}: {close(): void}) {
  const [payload, setPayload] = useState<SnapshotPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    const poll = async () => {
      try { const next = await getSnapshot(); if (!stopped) { setPayload(next); setFailed(false); } }
      catch { if (!stopped) setFailed(true); }
      finally { if (!stopped) timer = setTimeout(() => void poll(), 2000); }
    };
    void poll();
    return () => { stopped = true; clearInterval(tick); if (timer !== undefined) clearTimeout(timer); };
  }, []);
  const status = disconnectProgress(payload, failed, now);
  return <ConfirmModal className="rg-connection-modal" strTitle="Disconnect status"
    strOKButtonText="Hide" bAlertDialog={true} bDisableBackgroundDismiss={true} bHideCloseIcon={true} onOK={close} onCancel={close}>
    <style>{connectionPanelCss}</style>
    <div className="rg-connection">
      <p className="rg-connection-subtitle">Keep the G1 cable connected</p>
      <div className="rg-connection-list">{status.rows.map(row => <ReadinessRow key={row.label}
        label={row.label} state={row.state === "ready" ? "ready" : row.state === "blocked" ? "blocked" : row.state === "unavailable" ? "unavailable" : "waiting"}/>)}</div>
      <p role="status" className="rg-connection-detail">{status.detail}</p>
      <p className="rg-connection-foot">Status only. This does not release devices. Shut down fully before unplugging.</p>
    </div>
  </ConfirmModal>;
}
export function showDisconnectProgress(onClose: () => void) {
  let modal: ReturnType<typeof showModal>;
  const close = () => { modal.Close(); onClose(); };
  modal = showModal(<DisconnectPanel close={close}/>, window, {strTitle:"Re-Gear", bNeverPopOut:true});
  return modal;
}
