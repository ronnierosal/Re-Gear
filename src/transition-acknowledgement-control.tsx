import { DialogButton } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import {
  acknowledgeSupervisedTvSwitch,
  getSupervisedTvSwitchStatus,
  getTransitionJournalStatus,
  type SupervisedTvSwitchStatusPayload,
  type TransitionJournalStatusPayload,
} from "./backend";
import { regearTheme as theme } from "./regear-theme";

const acknowledgementId = /^[A-Za-z0-9_-]{8,64}$/;

export function displayAcknowledgementId(
  journal: TransitionJournalStatusPayload | null,
  status: SupervisedTvSwitchStatusPayload | null,
): string {
  const id = journal?.acknowledgement_id ?? "";
  return journal?.schema_version === 1
    && journal.code === "transition.blocked"
    && journal.owner === "presentation"
    && journal.acknowledgement_required === true
    && journal.action_required === true
    && journal.durable === true
    && acknowledgementId.test(id)
    && status?.schema_version === 1
    && status.code === "transition.blocked"
    && status.acknowledgement_required === true
    && status.action_required === true
    && status.durable === true
    && status.acknowledgement_id === id
      ? id : "";
}

/** Makes the existing owner-specific acknowledgement reachable from the
 * connection popup. Reads and mounting never acknowledge. A press re-reads
 * both journal views and can clear only the exact result shown to the player. */
export function TransitionAcknowledgementControl() {
  const [offered, setOffered] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const mounted = useRef(true);
  const acknowledgementInFlight = useRef(false);
  const acknowledgedId = useRef("");
  const offeredRef = useRef("");
  offeredRef.current = offered;

  useEffect(() => {
    mounted.current = true;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      try {
        const [journal, status] = await Promise.all([
          getTransitionJournalStatus(), getSupervisedTvSwitchStatus(),
        ]);
        if (!disposed) {
          const current = displayAcknowledgementId(journal, status);
          setOffered(current === acknowledgedId.current ? "" : current);
        }
      } catch { if (!disposed) setOffered(""); }
      if (!disposed) timer = setTimeout(refresh, 2000);
    };
    void refresh();
    return () => { disposed = true; mounted.current = false; clearTimeout(timer); };
  }, []);

  const acknowledge = async () => {
    const shown = offeredRef.current;
    if (!shown || acknowledgementInFlight.current) return;
    acknowledgementInFlight.current = true;
    setBusy(true);setMessage("");
    try {
      const [journal, status] = await Promise.all([
        getTransitionJournalStatus(), getSupervisedTvSwitchStatus(),
      ]);
      const current = displayAcknowledgementId(journal, status);
      if (!mounted.current) return;
      if (!current || current !== shown) {
        setOffered(current);
        setMessage("Display result changed. Review the current status.");
        return;
      }
      const result = await acknowledgeSupervisedTvSwitch(current);
      if (!mounted.current) return;
      if (result?.schema_version === 1 && result.acknowledged === true) {
        acknowledgedId.current = current;
        setOffered("");
        setMessage("Prior display result acknowledged. Re-Gear is checking the connection again.");
      } else setMessage("The exact display result could not be acknowledged.");
    } catch { if (mounted.current) setMessage("Display-result acknowledgement is unavailable."); }
    finally {
      acknowledgementInFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  if (!offered && !message) return null;
  return <div style={{ marginTop: 8 }}>
    {offered && <DialogButton onClick={() => void acknowledge()} disabled={busy}
      style={{ width:"100%", minWidth:0, height:"auto", padding:"9px 8px",
        border:`1px solid ${theme.border}`, borderRadius:9, background:"transparent",
        color:theme.accentSoft, fontSize:13, lineHeight:1.4 }}>
      {busy ? "Acknowledging…" : "Acknowledge prior display result"}
    </DialogButton>}
    {message && <div role="status" style={{ color:theme.muted, fontSize:13, lineHeight:1.4, marginTop:6 }}>{message}</div>}
  </div>;
}
