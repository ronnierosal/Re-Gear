import { createPowerChoiceBinding } from "./power-choice-binding";
import type { PowerChoice, PowerChoiceRequest, PowerChoiceView } from "./power-choice-binding";
import type { PowerIntent, PowerRequestPort, PowerView } from "../../power-request-coordinator";

export type EgpuPowerEvidence =
  | Readonly<{ available: true; request: PowerChoiceRequest }>
  | Readonly<{ available: false; reason: string }>;
export type EgpuPowerButtonChoice = Readonly<{
  intent: PowerIntent;
  action: "whole_dock_sleep" | "whole_dock_shutdown";
  connectionLabel: string;
  confirm: () => Promise<void>;
  cancel: () => void;
}>;
export type EgpuPowerButtonView = Readonly<{
  power: PowerView;
  choice: EgpuPowerButtonChoice | null;
}>;
export type EgpuPowerBeginResult =
  | Readonly<{ captured: true }>
  | Readonly<{ captured: false; reason: string }>;

/** Create once per plugin lifetime. A popup subscribes/reads on mount and only
 * unsubscribes on hide; dispose belongs exclusively to plugin unload.
 * Evidence is read at the explicit button press, not at construction or render.
 * Available means caller facts exist, never that teardown is ready: the backend
 * owns preflight, including the ordinary/already-down power route. An explicitly
 * observed empty token is valid; an absent token must never be defaulted to it.
 */
export function createEgpuPowerButtonSource(
  port: PowerRequestPort,
  readEvidence: (intent: PowerIntent) => EgpuPowerEvidence,
  options: { requestId?: () => string } = {},
) {
  const binding = createPowerChoiceBinding(port, options);
  const choices = new WeakMap<PowerChoice, EgpuPowerButtonChoice>();
  const views = new WeakMap<PowerChoiceView, EgpuPowerButtonView>();
  function present(snapshot: PowerChoiceView): EgpuPowerButtonView {
    const cached = views.get(snapshot);
    if (cached) return cached;
    let choice: EgpuPowerButtonChoice | null = null;
    // Only choosing advertises actions. The binding retains its private guard
    // after dispatch, while presentation continues to show the power outcome.
    if (snapshot.power.phase === "choosing" && snapshot.choice) {
      const ticket = snapshot.choice;
      choice = choices.get(ticket) ?? Object.freeze({
        intent: ticket.intent,
        action: ticket.intent === "sleep" ? "whole_dock_sleep" : "whole_dock_shutdown",
        connectionLabel: ticket.connectionLabel,
        // Retain the real ticket callback. Looking up the current choice here
        // would let an old confirmation operate a replacement request.
        confirm: ticket.intent === "sleep" ? ticket.disconnectAndSleep : ticket.confirm,
        cancel: ticket.cancel,
      });
      choices.set(ticket, choice);
    }
    // Keep the outcome even after the choice retires (refusal/sleep observed).
    const view = Object.freeze({ power: snapshot.power, choice });
    views.set(snapshot, view);
    return view;
  }
  function begin(intent: PowerIntent): EgpuPowerBeginResult {
    const evidence = readEvidence(intent);
    if (!evidence.available) return { captured: false, reason: evidence.reason };
    const captured = intent === "sleep"
      ? binding.beginSleep(evidence.request) : binding.beginShutdown(evidence.request);
    return captured ? { captured: true } : { captured: false, reason: "power.choice_unavailable" };
  }
  return Object.freeze({
    read: () => present(binding.read()),
    subscribe: (listener: (view: EgpuPowerButtonView) => void) =>
      binding.subscribe((snapshot) => listener(present(snapshot))),
    beginSleep: () => begin("sleep"),
    beginShutdown: () => begin("shutdown"),
    // Host owns bounded visible refresh. No polling or retry/dispatch here.
    refresh: () => binding.refresh(),
    dispose: () => binding.dispose(),
  });
}
