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
type Subscription = { close(): void };
type Rpc = {
  acknowledge(token: string): Promise<unknown>;
  decline(token: string): Promise<unknown>;
  confirm(token: string, consent: boolean, action: UsbAuthorizationAction): Promise<unknown>;
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
    || payload.already_offered !== false
    || payload.intentional_disconnect !== false
    || payload.confirmation_open !== false
    || !Number.isInteger(payload.generation)
    || (payload.remembered_grant_offered !== true
      && payload.remembered_grant_offered !== false)) return null;
  const candidate = payload as UsbAuthorizationPayload;
  return usbAuthorizationView({status: candidate}).phase === "offer" ? candidate : null;
}

function sameAttachment(payload: Record<string, unknown>, status: UsbAuthorizationPayload): boolean {
  return payload.token === status.token
    && payload.vendor === status.vendor
    && payload.model === status.model
    && payload.generation === status.generation
    && payload.already_offered === true
    && payload.intentional_disconnect === false
    && payload.remembered_grant_offered === status.remembered_grant_offered;
}

function acceptedAcknowledgement(value: unknown, status: UsbAuthorizationPayload): boolean {
  const payload = record(value);
  return payload?.schema_version === 1
    && payload.accepted === true
    && payload.state === "unavailable"
    && typeof payload.code === "string"
    && payload.confirmation_open === true
    && sameAttachment(payload, status);
}

function confirmationResult(value: unknown, status: UsbAuthorizationPayload, action: UsbAuthorizationAction): UsbAuthorizationPayload | null {
  const payload = record(value);
  if (payload?.schema_version !== 1
    || !sameAttachment(payload, status)
    || typeof payload.requested !== "boolean"
    || (payload.verified !== true && payload.verified !== false && payload.verified !== null)
    || typeof payload.code !== "string"
    || typeof payload.confirmation_open !== "boolean") return null;
  if (payload.requested === true) {
    if (payload.code !== "device_authorization.requested" || payload.confirmation_open !== false) return null;
  } else if (payload.verified !== null) return null;
  // The current backend's generic `verified` bit proves authorization only.
  // Remembered trust needs separate enrollment proof before the UI may claim it.
  if (action === "enroll" && payload.verified === true && payload.enrolled !== true)
    return {...payload, verified: null} as UsbAuthorizationPayload;
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
  const root = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  const acting = useRef(false);
  const acknowledging = useRef(true);
  const dismissQueued = useRef(false);
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
      acknowledging.current = false;
      if (!acceptedAcknowledgement(answer, status)) { close(); return; }
      if (dismissQueued.current) { dismissQueued.current = false; decline(); return; }
      setAcknowledged(true);
    }, () => { acknowledging.current = false; close(); });
    return () => { alive.current = false; };
  }, [rpc, status, token]);

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
      const checked = confirmationResult(answer, status, action);
      if (!checked) { close(); return; }
      setResult(checked);
    }, close).finally(() => { acting.current = false; });
  };

  const decline = () => {
    if (acting.current) return;
    if (result || pending) { close(); return; }
    acting.current = true;
    void rpc.decline(token).finally(close);
  };
  const dismiss = () => {
    if (acknowledging.current) { dismissQueued.current = true; return; }
    decline();
  };
  const toggleDetails = () => {
    const details = root.current?.querySelector<HTMLDetailsElement>("details");
    if (details) details.open = !details.open;
  };

  return <ModalRoot className="rg-popup-host" closeModal={close}
    bDisableBackgroundDismiss bHideCloseIcon>
    <Focusable ref={root} flow-children="vertical" noFocusRing preferredFocus
      onOKButton={event => { stopEvent(event); choose("authorize"); }}
      onSecondaryButton={event => { stopEvent(event); choose("enroll"); }}
      onCancelButton={event => { stopEvent(event); dismiss(); }}
      onOptionsButton={event => { stopEvent(event); toggleDetails(); }}
      onOKActionDescription={view.allowOnce.visible && view.allowOnce.enabled ? "Allow once" : undefined}
      onSecondaryActionDescription={view.alwaysTrust.visible && view.alwaysTrust.enabled ? "Always trust" : undefined}
      onCancelActionDescription={view.notNow.visible ? view.notNow.label : undefined}
      onOptionsActionDescription="Details">
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
  show(status: UsbAuthorizationPayload, onClosed: () => void): Subscription;
}) {
  let stopped = false;
  let epoch = 0;
  let dialog: Subscription | null = null;
  return {observe(value: unknown) {
    if (stopped || dialog) return;
    const offer = authorizationOffer(value);
    if (!offer) return;
    const token = epoch;
    dialog = deps.show(offer, () => {
      if (token !== epoch) return;
      dialog = null;
    });
  }, stop() {
    if (stopped) return;
    stopped = true;
    epoch++;
    const active = dialog;
    dialog = null;
    active?.close();
  }};
}
