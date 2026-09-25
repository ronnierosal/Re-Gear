import { Focusable, ModalRoot, showModal } from "@decky/ui";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  usbAuthorizationRequest,
  usbAuthorizationView,
  type UsbAuthorizationAction,
  type UsbAuthorizationPayload,
} from "./usb-authorization-model";
import { UsbAuthorizationPopup } from "./usb-authorization-popup";

const TOKEN = /^[0-9a-f]{32}$/;
export const USB_AUTHORIZATION_POLL_MS = 1000;

type Subscription = { close(): void };
type Rpc = {
  acknowledge(token: string): Promise<unknown>;
  decline(token: string): Promise<unknown>;
  confirm(token: string, consent: boolean, action: UsbAuthorizationAction): Promise<unknown>;
};
type TimerHost = {
  setTimeout(callback: () => void, delay: number): ReturnType<typeof setTimeout>;
  clearTimeout(timer: ReturnType<typeof setTimeout>): void;
};

const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;

/** Only a complete live backend offer can create a prompt. Unknown state and
 * the software-down intentional-disconnect projection remain silent. */
export function authorizationOffer(value: unknown): UsbAuthorizationPayload | null {
  const payload = record(value);
  if (!payload
    || payload.schema_version !== 1
    || payload.state !== "offered"
    || payload.code !== "device_authorization.available"
    || typeof payload.token !== "string"
    || !TOKEN.test(payload.token)
    || typeof payload.vendor !== "string"
    || typeof payload.model !== "string"
    || payload.model.trim().length === 0
    || payload.already_offered !== false
    || payload.intentional_disconnect !== false
    || payload.confirmation_open !== false
    || !Number.isInteger(payload.generation)
    || (payload.remembered_grant_offered !== true
      && payload.remembered_grant_offered !== false)) return null;
  const candidate = payload as UsbAuthorizationPayload;
  return usbAuthorizationView({status: candidate}).phase === "offer" ? candidate : null;
}

function acceptedAcknowledgement(value: unknown, token: string): boolean {
  const payload = record(value);
  return payload?.schema_version === 1
    && payload.accepted === true
    && payload.token === token
    && payload.confirmation_open === true;
}

function confirmationResult(value: unknown, token: string): UsbAuthorizationPayload | null {
  const payload = record(value);
  if (payload?.schema_version !== 1
    || payload.token !== token
    || typeof payload.requested !== "boolean"
    || (payload.verified !== true && payload.verified !== false && payload.verified !== null)
    || typeof payload.code !== "string") return null;
  return payload as UsbAuthorizationPayload;
}

function stopEvent(event: {preventDefault?(): void; stopPropagation?(): void}) {
  event.preventDefault?.();
  event.stopPropagation?.();
}

export function UsbAuthorizationDialog({status, rpc, onClose}: {
  status: UsbAuthorizationPayload;
  rpc: Rpc;
  onClose(): void;
}) {
  const token = status.token!;
  const [acknowledged, setAcknowledged] = useState(false);
  const [pending, setPending] = useState<UsbAuthorizationAction | null>(null);
  const [result, setResult] = useState<UsbAuthorizationPayload | null>(null);
  const alive = useRef(true);
  const acting = useRef(false);
  const closed = useRef(false);
  const close = () => {
    if (closed.current) return;
    closed.current = true;
    onClose();
  };

  useEffect(() => {
    alive.current = true;
    void rpc.acknowledge(token).then(answer => {
      if (!alive.current) return;
      if (!acceptedAcknowledgement(answer, token)) { close(); return; }
      setAcknowledged(true);
    }, close);
    return () => { alive.current = false; };
  }, [rpc, token]);

  const rawView = usbAuthorizationView({status, pending, result});
  const view = useMemo(() => ({
    ...rawView,
    allowOnce: {...rawView.allowOnce, enabled: acknowledged && rawView.allowOnce.enabled},
    alwaysTrust: {...rawView.alwaysTrust, enabled: acknowledged && rawView.alwaysTrust.enabled},
  }), [rawView, acknowledged]);

  const choose = (action: UsbAuthorizationAction) => {
    const retryAllowOnce = action === "authorize"
      && result?.requested === false
      && result.code === "device_authorization.remembered_grant_not_offered"
      && result.token === token;
    if (!acknowledged || acting.current || ((pending || result) && !retryAllowOnce)) return;
    if (action === "enroll" && status.remembered_grant_offered !== true) return;
    acting.current = true;
    setResult(null);
    setPending(action);
    const request = usbAuthorizationRequest(token, action);
    void rpc.confirm(request.token, request.consent, request.action).then(answer => {
      if (!alive.current) return;
      const checked = confirmationResult(answer, token);
      if (!checked) { close(); return; }
      setResult(checked);
    }, close).finally(() => { acting.current = false; });
  };

  const dismiss = () => {
    if (acting.current) return;
    if (result || pending) { close(); return; }
    acting.current = true;
    void rpc.decline(token).finally(close);
  };

  return <ModalRoot className="rg-popup-host" closeModal={close}
    bDisableBackgroundDismiss bHideCloseIcon>
    <Focusable flow-children="vertical" noFocusRing preferredFocus
      onOKButton={event => { stopEvent(event); choose("authorize"); }}
      onSecondaryButton={event => { stopEvent(event); choose("enroll"); }}
      onCancelButton={event => { stopEvent(event); dismiss(); }}
      onOKActionDescription="Allow once"
      onSecondaryActionDescription={status.remembered_grant_offered === true ? "Always trust" : undefined}
      onCancelActionDescription="Not now">
      <UsbAuthorizationPopup view={view}
        onAllowOnce={() => choose("authorize")}
        onAlwaysTrust={status.remembered_grant_offered === true ? () => choose("enroll") : undefined}
        onDismiss={dismiss}/>
    </Focusable>
  </ModalRoot>;
}

export function showUsbAuthorizationDialog(status: UsbAuthorizationPayload, rpc: Rpc, onClosed: () => void): Subscription {
  let modal: ReturnType<typeof showModal>;
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    modal.Close();
    onClosed();
  };
  modal = showModal(<UsbAuthorizationDialog status={status} rpc={rpc} onClose={close}/>, window,
    {strTitle: "Re-Gear", bNeverPopOut: true});
  return {close};
}

export function startUsbAuthorizationMonitor(deps: {
  read(): Promise<unknown>;
  show(status: UsbAuthorizationPayload, onClosed: () => void): Subscription;
  timers?: TimerHost;
}) {
  const timers = deps.timers ?? window;
  let stopped = false;
  let reading = false;
  let epoch = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let dialog: Subscription | null = null;

  const schedule = () => {
    if (!stopped && timer === undefined) timer = timers.setTimeout(() => {
      timer = undefined;
      void poll();
    }, USB_AUTHORIZATION_POLL_MS);
  };
  const poll = async () => {
    if (stopped || reading || dialog) { schedule(); return; }
    reading = true;
    const token = epoch;
    try {
      const offer = authorizationOffer(await deps.read());
      if (stopped || token !== epoch || !offer || dialog) return;
      dialog = deps.show(offer, () => {
        if (token !== epoch) return;
        dialog = null;
        schedule();
      });
    } catch { /* A failed read makes no claim and opens nothing. */ }
    finally { reading = false; schedule(); }
  };
  void poll();
  return {stop() {
    if (stopped) return;
    stopped = true;
    epoch++;
    if (timer !== undefined) timers.clearTimeout(timer);
    timer = undefined;
    const active = dialog;
    dialog = null;
    active?.close();
  }};
}
