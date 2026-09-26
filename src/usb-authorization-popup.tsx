import { DialogButton } from "@decky/ui";
import { useRef } from "react";
import { PopupFrame, type PopupState } from "./popup-frame";
import { CommandCenterIcon } from "./quick-access/command-center-icons";
import type { UsbAuthorizationView } from "./usb-authorization-model";

export type UsbAuthorizationPopupProps = {
  view: UsbAuthorizationView;
  /** "Allow once": authorize this attachment only. */
  onAllowOnce?(): void;
  /** "Always trust": remembered trust; only rendered when the view offers it. */
  onAlwaysTrust?(): void;
  /** Not now / Close / Hide: never authorizes anything. */
  onDismiss(): void;
};

const frameState: Record<UsbAuthorizationView["tone"], PopupState> = {
  warning: "attention", waiting: "connecting", ready: "ready", attention: "attention",
};

export const usbAuthorizationCss = `
.rg-usb-auth{display:flex;flex-direction:column;gap:8px}
.rg-usb-device{display:flex;align-items:center;gap:10px;padding:8px 10px;background:#112333;border:1px solid #1e3548;border-radius:8px}
.rg-usb-device-icon{display:grid;place-items:center;width:36px;height:36px;border-radius:8px;background:#0a2232;border:1px solid #315c75;color:#c9ecff;flex:0 0 auto}
.rg-usb-device-name{font-size:14px;font-weight:600;color:#edf3f8;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rg-usb-device-kind{font-size:11px;color:#93adc1}
.rg-usb-body{font-size:13px;line-height:1.35;color:#c9dfef;margin:0}
.rg-usb-choices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.rg-usb-choice{font-size:11px;line-height:1.3;color:#93adc1;padding:6px 8px;border:1px solid #1e3548;border-radius:8px}
.rg-usb-choice strong{display:block;font-size:12px;color:#edf3f8}
.rg-usb-warning{font-size:11px;color:#ffc247}
.rg-usb-auth[data-phase=approved] .rg-usb-device{border-color:#2f5e3c}
.rg-usb-auth details summary{font-size:12px}.rg-usb-auth details p{font-size:12px;margin:4px 0;color:#c9dfef}
@media(min-height:650px){.rg-usb-body{font-size:15px}.rg-usb-device-name{font-size:16px}.rg-usb-choice{font-size:12px}.rg-usb-choice strong{font-size:13px}}
`;

export function UsbAuthorizationPopup({view, onAllowOnce, onAlwaysTrust, onDismiss}: UsbAuthorizationPopupProps) {
  const details = useRef<HTMLDetailsElement>(null);
  const toggleDetails = () => { if (details.current) details.current.open = !details.current.open; };
  const offer = view.phase === "offer";
  return <PopupFrame title="eGPU Authorization" state={frameState[view.tone]} stateLabel={view.headline} compact footer={<>
    {view.notNow.visible && <DialogButton onClick={onDismiss}><span className="rg-key">B</span> {view.notNow.label}</DialogButton>}
    <DialogButton onClick={toggleDetails}><span className="rg-key">Y</span> Details</DialogButton>
    {view.alwaysTrust.visible && onAlwaysTrust && <DialogButton onClick={onAlwaysTrust} disabled={!view.alwaysTrust.enabled}><span className="rg-key">X</span> Always trust</DialogButton>}
    {view.allowOnce.visible && onAllowOnce && <DialogButton onClick={onAllowOnce} disabled={!view.allowOnce.enabled}><span className="rg-key">A</span> Allow once</DialogButton>}
  </>}>
    <style>{usbAuthorizationCss}</style>
    <div className="rg-usb-auth" data-phase={view.phase}>
      <div className="rg-usb-device">
        <span className="rg-usb-device-icon" aria-hidden="true"><CommandCenterIcon id="egpu" size={24}/></span>
        <div style={{minWidth:0}}>
          <div className="rg-usb-device-name" title={view.deviceLabel}>{view.deviceLabel}</div>
          <div className="rg-usb-device-kind">Thunderbolt / USB4 device</div>
        </div>
      </div>
      <p className="rg-usb-body">{view.body}</p>
      {offer && <div className="rg-usb-choices">
        <div className="rg-usb-choice"><strong>Allow once</strong>Works until you unplug it. You'll be asked again next time.</div>
        {view.alwaysTrust.visible
          ? <div className="rg-usb-choice"><strong>Always trust</strong>Re-Gear remembers this device and connects it automatically.</div>
          : <div className="rg-usb-choice"><strong>Not now</strong>The device stays blocked. Nothing is trusted.</div>}
      </div>}
      {offer && <div className="rg-usb-warning">Only approve hardware you own or trust.</div>}
      <details ref={details}><summary>Details</summary>{view.details.map(line => <p key={line}>{line}</p>)}</details>
    </div>
  </PopupFrame>;
}
