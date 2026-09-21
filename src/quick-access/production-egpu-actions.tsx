import { showModal } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { EgpuConfirmModal } from "../egpu-confirm-modal";
import { powerRequestPort } from "../power-request-port";
import { createPowerRequestCoordinator } from "../power-request-coordinator";
import { WholeDockControl } from "../whole-dock-control";

export type ProductionEgpuAction = "safe-disconnect" | "sleep-connected" | "shutdown";
export type ProductionEgpuActionRequest = Readonly<{ action: ProductionEgpuAction; nonce: number }>;

function ConnectedSleepRequest() {
  const [, setRevision] = useState(0);
  const coordinator = useRef<ReturnType<typeof createPowerRequestCoordinator> | null>(null);
  if (!coordinator.current) {
    coordinator.current = createPowerRequestCoordinator(powerRequestPort, {
      onChange: () => setRevision((value) => value + 1),
    });
  }
  const modal = useRef<ReturnType<typeof showModal> | null>(null);
  useEffect(() => {
    const owner = coordinator.current!;
    const choice = owner.captureSleep("");
    if (!choice) return () => owner.dispose();
    let decided = false;
    const cancel = () => {
      if (decided) return;
      decided = true;
      choice.cancel();
      modal.current?.Close();
      modal.current = null;
    };
    const confirm = () => {
      if (decided) return;
      decided = true;
      modal.current?.Close();
      modal.current = null;
      void choice.keepConnectedAndSleep();
    };
    modal.current = showModal(<EgpuConfirmModal
      strTitle="Sleep with eGPU connected?"
      strDescription="Re-Gear will request normal sleep and keep the eGPU connected. It will not run Safe Disconnect or remove the dock in software. Save your work before continuing."
      strOKButtonText="Sleep connected"
      strCancelButtonText="Cancel"
      className="rg-whole-dock-confirm"
      bDestructiveWarning
      onOK={confirm}
      onCancel={cancel}
      onEscKeypress={cancel}
    />, undefined, { fnOnClose: cancel, bNeverPopOut: true });
    return () => {
      modal.current?.Close();
      modal.current = null;
      owner.dispose();
    };
  }, []);
  const view = coordinator.current.read();
  const message = view.phase === "dispatching" || view.phase === "pending"
    ? "Sleep request pending. Keep the eGPU connected."
    : view.phase === "requested" || view.phase === "sleep_observed"
      ? "Sleep request accepted. Keep the eGPU connected."
      : view.phase === "refused"
        ? "Sleep was refused. The eGPU remains connected."
        : view.phase === "uncertain"
          ? "Sleep reply is uncertain. No retry was sent. Keep the eGPU connected."
          : "Confirm normal sleep with the eGPU connected.";
  return <p role="status" style={{ margin: "0 2px 10px", fontSize: 12, lineHeight: "16px", color: "#9eb2ca" }}>{message}</p>;
}

export function ProductionEgpuActionHost({ request, readCurrentSnapshot }: {
  request: ProductionEgpuActionRequest | null;
  readCurrentSnapshot(): unknown;
}) {
  if (!request) return null;
  if (request.action === "sleep-connected") return <ConnectedSleepRequest key={request.nonce} />;
  return <WholeDockControl
    key={request.nonce}
    intent={request.action === "shutdown" ? "shutdown" : "disconnect_only"}
    readCurrentSnapshot={readCurrentSnapshot}
    startRequest
  />;
}
