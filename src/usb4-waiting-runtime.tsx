import { DialogButton, Focusable, ModalRoot, showModal } from "@decky/ui";
import { useSyncExternalStore } from "react";
import { PopupFrame } from "./popup-frame";
import { ReadableBlock } from "./quick-access/readable-block";
import { createUsb4WaitingMemory, usb4WaitingObservation, validUsb4WaitingReceipt,
  USB4_WAITING_TEXT, USB4_WAITING_UNAVAILABLE, type Usb4WaitingReceipt } from "./usb4-waiting-model";

export type Usb4WaitingStatusReading = Readonly<{
  state: "unauthorized" | "unknown" | "ambiguous";
  guidance: string;
  automaticNoticeSuppressed: boolean;
}>;
export type Usb4WaitingStatusSource = {
  read(): Usb4WaitingStatusReading | null;
  subscribe(listener: () => void): () => void;
};

/** Mounted by index beside the existing eGPU status, never a new action. */
export function Usb4WaitingStatus({ source }: { source: Usb4WaitingStatusSource }) {
  const status = useSyncExternalStore(source.subscribe, source.read, source.read);
  if (!status) return null;
  return <ReadableBlock label="USB4 authorization status"><p role="status"
    style={{ margin: "8px 0", fontSize: 14, lineHeight: 1.45 }}>{status.guidance}</p></ReadableBlock>;
}

export function Usb4WaitingPopup({ onDismiss }: { onDismiss(): void }) {
  return <ModalRoot className="rg-popup-host" closeModal={onDismiss} bHideCloseIcon>
    <Focusable flow-children="vertical" noFocusRing
      onCancelButton={event => { event.preventDefault(); event.stopPropagation(); onDismiss(); }}
      onCancelActionDescription="Hide">
      <PopupFrame title="USB4 device" state="attention" stateLabel="Waiting for system authorization"
        footer={<DialogButton onClick={onDismiss}><span className="rg-key">B</span> Hide</DialogButton>}>
        <ReadableBlock label="USB4 authorization guidance"><p style={{ margin: 0, fontSize: 14, lineHeight: 1.45 }}>
          {USB4_WAITING_TEXT}
        </p></ReadableBlock>
      </PopupFrame>
    </Focusable>
  </ModalRoot>;
}

export function showUsb4WaitingNotice(onClosed: () => void): { close(): void } {
  let modal: ReturnType<typeof showModal>;
  let closed = false, closing = false;
  const close = () => {
    if (closed || closing) return;
    closing = true;
    try { modal?.Close(); closed = true; onClosed(); }
    finally { closing = false; }
  };
  modal = showModal(<Usb4WaitingPopup onDismiss={close} />, window,
    { strTitle: "Re-Gear", bNeverPopOut: true });
  return { close };
}

/** Presentation only. Index owns request order, admission latch and expiry timer. */
export function createUsb4WaitingRuntime(deps: {
  show(onClosed: () => void): { close(): void };
  now?(): number;
}) {
  const memory = createUsb4WaitingMemory();
  const now = deps.now ?? Date.now;
  let stopped = false, supportedLifetime = false;
  let generation = -1, startedAt = -Infinity;
  let revision = 0;
  let status: Usb4WaitingStatusReading | null = null;
  const listeners = new Set<() => void>();
  const publish = (next: Usb4WaitingStatusReading | null) => {
    if (status?.state === next?.state && status?.guidance === next?.guidance
      && status?.automaticNoticeSuppressed === next?.automaticNoticeSuppressed) return;
    status = next ? Object.freeze(next) : null;
    for (const listener of [...listeners]) {
      try { listener(); } catch { /* One presentation listener cannot block withdrawal. */ }
    }
  };
  const source: Usb4WaitingStatusSource = {
    read: () => status,
    subscribe(listener) { if (stopped) return () => {}; listeners.add(listener); return () => listeners.delete(listener); },
  };
  let active: { key: string; close: (() => void) | null } | null = null;
  const closeActive = () => {
    const current = active;
    if (!current?.close) { active = null; return; }
    // Failed native closure is not treated as a closed surface or replaced.
    try { current.close(); }
    catch (error) { publish(null); throw error; }
    if (active === current) active = null;
  };
  const withdraw = () => { revision++; publish(null); closeActive(); };
  const observe = (receipt: Usb4WaitingReceipt) => {
    if (stopped) return;
    // Ignore expired/malformed old completions without withdrawing a newer surface.
    try {
      const oldGeneration = Object.getOwnPropertyDescriptor(receipt, "generation")?.value;
      const oldStarted = Object.getOwnPropertyDescriptor(receipt, "requestStartedAtMs")?.value;
      if (Number.isInteger(oldGeneration) && oldGeneration < generation) return;
      if (oldGeneration === generation && typeof oldStarted === "number" && oldStarted < startedAt
        && !validUsb4WaitingReceipt(receipt, now())) return;
    } catch { withdraw(); return; }
    if (!validUsb4WaitingReceipt(receipt, now())) { withdraw(); return; }
    if (receipt.generation < generation) return;
    if (receipt.supportedLifetime) supportedLifetime = true;
    if (supportedLifetime) { withdraw(); return; }
    if (receipt.generation === generation && receipt.requestStartedAtMs < startedAt) return;
    const turn = ++revision;
    if (receipt.generation > generation) closeActive();
    generation = receipt.generation;
    startedAt = receipt.requestStartedAtMs;
    const reading = usb4WaitingObservation(receipt.payload);
    if (!reading || reading.state === "none" || reading.state === "authorized") { withdraw(); return; }
    if (reading.state !== "unauthorized" || reading.noticeKey === null) {
      closeActive();
      publish({ state: reading.state, guidance: USB4_WAITING_UNAVAILABLE, automaticNoticeSuppressed: true });
      return;
    }
    if (active?.key === reading.noticeKey) return;
    closeActive();
    const claimed = memory.claim(reading.noticeKey);
    publish({ state: "unauthorized", guidance: USB4_WAITING_TEXT, automaticNoticeSuppressed: !claimed });
    if (!claimed || stopped || turn !== revision) return;
    const current = { key: reading.noticeKey, close: null as (() => void) | null };
    active = current;
    try {
      const modal = deps.show(() => { if (active === current) active = null; });
      current.close = () => modal.close();
      // Dismissal/disposal can run synchronously while the host is opening.
      if (stopped || active !== current) modal.close();
    } catch (error) {
      if (active === current) active = null;
      throw error;
    }
  };
  return { source, observe, withdraw, stop() { stopped = true; try { withdraw(); } finally { listeners.clear(); } } };
}
