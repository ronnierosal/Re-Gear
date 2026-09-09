import { DialogButton, Focusable } from "@decky/ui";
import type { ReactNode } from "react";
import type { ModuleEntry, ModuleId, Route, StatusId } from "./module-registry";

/** Command Center navigation shell: rendering only, no policy, no requests.
 *
 * Which destinations exist, whether they are usable and what a blocked one says
 * all come from `module-registry`, so this file cannot disagree with the
 * taxonomy. It renders one route at a time and owns no state.
 *
 * A destination is never hidden because it is unavailable. It renders its
 * reason instead, which is the answer a player actually needs, and it stays
 * focusable so a controller can reach it.
 *
 * Nothing here implies a backend operation is supported. Content for each
 * module arrives in its own slice; this shell only establishes the routes.
 */

const C = {
  cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca",
  border: "#294665", amber: "#ffc247", dim: "#5d7a99",
};

const SURFACE = "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))";

function Chevron() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    style={{ flexShrink: 0 }}><path d="M9 6l6 6-6 6" /></svg>;
}

/** One tappable row: icon slot, title, one-line summary or reason, chevron. */
function NavRow({ title, detail, blocked, onClick, focusKey }: {
  title: string; detail: string; blocked: boolean;
  onClick(): void; focusKey: string;
}) {
  return <DialogButton
    data-regear-focus={focusKey}
    onClick={onClick}
    // Blocked rows stay focusable: opening one is how its reason is read.
    style={{
      width: "100%", minHeight: 44, margin: "0 0 6px", padding: "8px 10px",
      display: "flex", alignItems: "center", gap: 8, textAlign: "left",
      background: SURFACE, border: `1px solid ${C.border}`, borderRadius: 12,
      color: blocked ? C.dim : C.text,
    }}>
    <span style={{ flex: "1 1 auto", minWidth: 0 }}>
      <span style={{ display: "block", fontSize: 14, fontWeight: 700 }}>{title}</span>
      <span style={{ display: "block", fontSize: 12, lineHeight: "16px",
        color: blocked ? C.amber : C.muted, whiteSpace: "normal" }}>{detail}</span>
    </span>
    <Chevron />
  </DialogButton>;
}

export function ModulesList({ modules, onOpen }: {
  modules: ModuleEntry[]; onOpen(id: ModuleId): void;
}) {
  return <Focusable style={{ color: C.text }} flow-children="vertical">
    {modules.map((entry) => (
      <NavRow key={entry.id} focusKey={`module:${entry.id}`}
        title={entry.title}
        // A blocked module shows why, not a summary of controls it cannot reach.
        detail={entry.available ? entry.summary : entry.reason ?? ""}
        blocked={!entry.available}
        onClick={() => onOpen(entry.id)} />
    ))}
  </Focusable>;
}

/** Heading for a pushed level, with the reason when the destination is blocked. */
export function RouteHeader({ title, reason }: { title: string; reason: string | null }) {
  return <div style={{ margin: "0 2px 10px", color: C.text }}>
    <div style={{ fontSize: 15, fontWeight: 760, marginBottom: 2 }}>{title}</div>
    {reason && <div style={{ fontSize: 12, lineHeight: "16px", color: C.amber }}>{reason}</div>}
  </div>;
}

/** The Modules entry on Command Center. Labelled, not an icon-only target. */
export function ModulesButton({ onOpen }: { onOpen(): void }) {
  return <DialogButton
    data-regear-focus="modules"
    onClick={onOpen}
    style={{
      width: "auto", minHeight: 36, margin: 0, padding: "4px 12px",
      alignSelf: "flex-end", borderRadius: 10, fontSize: 13, fontWeight: 700,
      background: SURFACE, border: `1px solid ${C.border}`, color: C.cyan,
    }}>
    Modules
  </DialogButton>;
}

/** Read-only status entries, deliberately not routed to configuration. */
export function StatusLinks({ entries, onOpen }: {
  entries: Array<{ id: StatusId; title: string; detail: string }>;
  onOpen(id: StatusId): void;
}) {
  return <Focusable style={{ color: C.text }} flow-children="vertical">
    {entries.map((entry) => (
      <NavRow key={entry.id} focusKey={`status:${entry.id}`} title={entry.title}
        detail={entry.detail} blocked={false} onClick={() => onOpen(entry.id)} />
    ))}
  </Focusable>;
}

/** Placeholder body for a route whose content has not been migrated yet.
 *
 * Stated plainly rather than left blank: an empty pane reads as a broken
 * screen, and this shell must not imply a control exists where none does. */
export function PendingContent({ what }: { what: string }) {
  return <div style={{ margin: "0 2px", fontSize: 12, lineHeight: "16px", color: C.muted }}>
    {what} has not moved here yet. It is still reachable on the main panel.
  </div>;
}

export function ShellBody({ route, modules, children, onOpenModule, onOpenStatus, statusEntries }: {
  route: Route;
  modules: ModuleEntry[];
  /** Command Center body, supplied by the caller during migration. */
  children: ReactNode;
  statusEntries: Array<{ id: StatusId; title: string; detail: string }>;
  onOpenModule(id: ModuleId): void;
  onOpenStatus(id: StatusId): void;
}) {
  if (route.kind === "modules") {
    return <>
      <RouteHeader title="Modules" reason={null} />
      <ModulesList modules={modules} onOpen={onOpenModule} />
    </>;
  }
  if (route.kind === "module") {
    const entry = modules.find((candidate) => candidate.id === route.id);
    return <>
      <RouteHeader title={entry?.title ?? "Module"} reason={entry?.reason ?? null} />
      <PendingContent what={entry?.title ?? "This module"} />
    </>;
  }
  if (route.kind === "status") {
    const entry = statusEntries.find((candidate) => candidate.id === route.id);
    return <>
      <RouteHeader title={entry?.title ?? "Status"} reason={null} />
      <PendingContent what={entry?.title ?? "This status"} />
    </>;
  }
  return <>
    {children}
    <StatusLinks entries={statusEntries} onOpen={onOpenStatus} />
  </>;
}
