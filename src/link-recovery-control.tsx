import { DialogButton, showModal } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { executeLinkRecovery, getLinkRecoveryStatus } from "./backend";
import { EgpuConfirmModal } from "./egpu-confirm-modal";
import { recoveryOffered, recoveryResult } from "./link-recovery-model";
import { regearTheme as theme } from "./regear-theme";

/** Adds an explicit recovery request; mounting, polling and cancellation never mutate. */
export function LinkRecoveryControl({ eligible }: { eligible: boolean }) {
  const [offered, setOffered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const current = useRef(eligible);
  const mounted = useRef(true);
  const pending = useRef(false);
  current.current = eligible;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setOffered(false);
    if (!eligible) return;
    const refresh = async () => {
      try {
        const status = await getLinkRecoveryStatus();
        if (disposed) return;
        setOffered(recoveryOffered(status));
        timer = setTimeout(refresh, 2000);
      } catch {
        // An older installed backend may not have this RPC. Do not retry it forever.
        if (!disposed) setOffered(false);
      }
    };
    void refresh();
    return () => { disposed = true; clearTimeout(timer); };
  }, [eligible]);

  const confirm = () => {
    if (!current.current || !offered || pending.current) return;
    pending.current = true;
    setBusy(true);
    let decided = false;
    const cancel = () => {
      if (decided) return;
      decided = true;
      pending.current = false;
      if (mounted.current) setBusy(false);
    };
    const execute = async () => {
      if (decided) return;
      decided = true;
      try {
        // Confirmation can outlive the card or its fresh readiness evidence.
        if (!mounted.current || !current.current) return;
        const status = await getLinkRecoveryStatus();
        if (!mounted.current || !current.current) return;
        if (!recoveryOffered(status)) {
          setOffered(false);
          setMessage("Connection status changed. Check the latest readings.");
          return;
        }
        setOffered(false);
        setMessage("Restart requested. Gaming Mode will briefly close; keep the eGPU connected.");
        const result = await executeLinkRecovery(true, "session_restart");
        if (mounted.current) setMessage(recoveryResult(result));
      } catch {
        // Restarting Steam can interrupt this RPC reply. Never infer failure or retry.
        if (mounted.current) setMessage("Gaming Mode may have restarted. Check the connection status.");
      } finally {
        pending.current = false;
        if (mounted.current) setBusy(false);
      }
    };
    showModal(<EgpuConfirmModal
      className="rg-recovery-confirm"
      strTitle="Restart Gaming Mode to retry the eGPU?"
      strDescription="Gaming Mode will briefly close and reopen. Keep the eGPU connected. This may restore detection; it does not guarantee a TV connection."
      strOKButtonText="Restart Gaming Mode"
      strCancelButtonText="Keep waiting"
      bDestructiveWarning
      onOK={() => { void execute(); }}
      onCancel={cancel}
      onEscKeypress={cancel}
    ><style>{`.rg-recovery-confirm{position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style></EgpuConfirmModal>, undefined, { fnOnClose: cancel, bNeverPopOut: true });
  };

  if (!eligible) return null;
  if (!offered && !message) return null;
  return <div style={{ marginTop: 8 }}>
    {offered && <DialogButton onClick={confirm} disabled={busy}
      style={{ width: "100%", minWidth: 0, height: "auto", padding: "9px 8px",
        border: `1px solid ${theme.border}`, borderRadius: 9, background: "transparent",
        color: theme.accentSoft, fontSize: 13, lineHeight: 1.4 }}>
      Retry eGPU detection
    </DialogButton>}
    {message && <div role="status" style={{ color: theme.muted, fontSize: 13, lineHeight: 1.4, marginTop: 6 }}>{message}</div>}
  </div>;
}
