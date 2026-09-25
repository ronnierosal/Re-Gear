/**
 * Presentation model for the first-time USB4/Thunderbolt authorization popup.
 *
 * Pure: no I/O, timers or device access. It reads the payload shape of the
 * device-authorization facade (draft PR #317) and decides only what the
 * player is shown. The player's confirmation is the authorization, so every
 * approve action carries an explicit choice; nothing here grants anything.
 *
 * Truth boundaries:
 * - `requested` is submission, never success.
 * - `verified` is a readback of this attachment's authorization state only.
 *   It is not proof that the GPU enumerated, the TV switched or the
 *   connection completed.
 * - "Always trust" is shown only when the backend reports that remembered
 *   trust is offered; the backend refuses it otherwise.
 */

export type UsbAuthorizationAction = "authorize" | "enroll";
export type UsbAuthorizationPayload = {
  schema_version?: number;
  state?: string;
  code?: string;
  token?: string;
  vendor?: string;
  model?: string;
  generation?: number;
  requested?: boolean;
  verified?: boolean | null;
  confirmation_open?: boolean;
  already_offered?: boolean;
  /** Whether this build offers remembered trust ("Always trust"). */
  remembered_grant_offered?: boolean;
};

export type UsbAuthorizationPhase =
  | "hidden"      // nothing to offer, or unreadable
  | "offer"       // waiting for the player's choice
  | "submitting"  // a choice was sent; no answer yet
  | "checking"    // accepted by the executor; readback not yet proven
  | "approved"    // readback proved this attachment is authorized
  | "not_approved"// readback proved it is not
  | "refused"     // the request was refused before anything ran
  | "gone";       // the device or its token went away

export type UsbAuthorizationView = {
  phase: UsbAuthorizationPhase;
  tone: "warning" | "waiting" | "ready" | "attention";
  headline: string;
  deviceLabel: string;
  body: string;
  choice?: UsbAuthorizationAction;
  allowOnce: {visible: boolean; enabled: boolean};
  alwaysTrust: {visible: boolean; enabled: boolean};
  notNow: {visible: boolean; label: string};
  /** Details-only facts; never shown as a claim of connection success. */
  details: string[];
};

const MAX_TEXT = 64;
const clean = (value: unknown): string => {
  if (typeof value !== "string") return "";
  const text = value.replace(/[\u0000-\u001f\u007f]/g, "").trim();
  return text.length > MAX_TEXT ? text.slice(0, MAX_TEXT - 1) + "…" : text;
};

export function usbDeviceLabel(payload: UsbAuthorizationPayload | null | undefined): string {
  const vendor = clean(payload?.vendor), model = clean(payload?.model);
  if (vendor && model) return model.toLowerCase().startsWith(vendor.toLowerCase()) ? model : `${vendor} ${model}`;
  return model || vendor || "";
}

const REFUSAL_COPY: Record<string, string> = {
  "device_authorization.remembered_grant_not_offered": "Always trust isn't available in this version. You can still allow it for this connection.",
  "device_authorization.identity_unresolved": "Re-Gear can't tell which device this is, so it won't approve it.",
  "device_authorization.intentional_disconnect": "This device was disconnected on purpose, so Re-Gear won't reconnect it.",
};

export type UsbAuthorizationInput = {
  /** Latest status payload from the backend, or null when unreadable. */
  status: UsbAuthorizationPayload | null;
  /** The action the player chose and that has been sent, if any. */
  pending?: UsbAuthorizationAction | null;
  /** The answer to that confirmation, once received. */
  result?: UsbAuthorizationPayload | null;
};

const details = (label: string) => [
  `Device: ${label || "Unnamed device"}`,
  "Approving gives this device direct access to system memory over PCIe, which the eGPU needs.",
  "Only approve hardware you own or trust.",
];

/** Decide what the popup shows. Unknown or partial evidence never becomes an offer. */
export function usbAuthorizationView({status, pending = null, result = null}: UsbAuthorizationInput): UsbAuthorizationView {
  const label = usbDeviceLabel(result ?? status);
  const remembered = status?.remembered_grant_offered === true;
  const offered = status?.state === "offered" && typeof status.token === "string" && status.token.length > 0 && label.length > 0;
  const base = {deviceLabel: label || "Unnamed device", details: details(label),
    allowOnce: {visible: false, enabled: false}, alwaysTrust: {visible: false, enabled: false},
    notNow: {visible: true, label: "Close"}};

  if (result) {
    const code = clean(result.code);
    if (result.requested !== true) {
      const refusedRemembered = code === "device_authorization.remembered_grant_not_offered";
      const canRetry = refusedRemembered && offered && result.token === status?.token;
      return {...base, phase: "refused", tone: "attention", choice: pending ?? undefined,
        headline: "Not approved",
        body: REFUSAL_COPY[code] ?? "The request wasn't accepted. The device stays blocked.",
        allowOnce: {visible: canRetry, enabled: canRetry},
        notNow: {visible: true, label: canRetry ? "Not now" : "Close"}};
    }
    const scope = pending === "enroll" ? "Trusted — Re-Gear will remember this device" : "Approved for this connection";
    if (result.verified === true) {
      return {...base, phase: "approved", tone: "ready", choice: pending ?? undefined, headline: scope,
        body: "The device is authorized. The eGPU connection continues from here."};
    }
    if (result.verified === false) {
      return {...base, phase: "not_approved", tone: "attention", choice: pending ?? undefined,
        headline: "Approval didn't take effect",
        body: "The device still reports as not authorized. Unplug it and plug it back in to try again."};
    }
    return {...base, phase: "checking", tone: "waiting", choice: pending ?? undefined,
      headline: "Approval sent — checking", body: "Waiting for the device to report that it is authorized.",
      notNow: {visible: true, label: "Hide"}};
  }

  if (pending) {
    return {...base, phase: "submitting", tone: "waiting", choice: pending,
      headline: "Sending approval…", body: "Keep the eGPU connected.", notNow: {visible: false, label: "Hide"}};
  }

  if (!status || !offered) {
    const gone = status?.state === "unavailable" && !!status.already_offered;
    return {...base, phase: gone ? "gone" : "hidden", tone: "attention",
      headline: gone ? "Device no longer waiting" : "", body: gone ? "The device was unplugged or already handled." : ""};
  }

  return {...base, phase: "offer", tone: "warning",
    headline: "Allow this eGPU?",
    body: remembered
      ? "New Thunderbolt/USB4 hardware needs your approval before it can connect. Allow it once, or trust it so it connects automatically next time."
      : "New Thunderbolt/USB4 hardware needs your approval before it can connect. You'll be asked again the next time you plug it in.",
    allowOnce: {visible: true, enabled: true},
    alwaysTrust: {visible: remembered, enabled: remembered},
    notNow: {visible: true, label: "Not now"}};
}

/** The exact confirmation a button sends. Consent is always literal `true`. */
export function usbAuthorizationRequest(token: string, action: UsbAuthorizationAction) {
  return {token, consent: true as const, action};
}
