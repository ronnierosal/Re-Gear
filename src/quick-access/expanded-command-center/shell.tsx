import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode, ElementType } from "react";
import { CommandCenterIcon, type CommandCenterIconId } from "../command-center-icons";
import { columnsForWidth, gridCells, moveInGrid, nextTab, restoreTarget, sampleTiles, tabLabels, tabs } from "./model";
import type { Tab, Tile } from "./model";
import { expandedStyles } from "./styles";
import { brandIcon } from "../../brand-assets";

const iconIds: Record<string, CommandCenterIconId> = {
  quick: "quick-access", performance: "performance", egpu: "egpu", controllers: "controllers", settings: "settings",
  fps: "fps", manual: "manual-tdp", auto: "auto-tdp", display: "display", disconnect: "safe-disconnect",
  controller: "controllers", builtin: "controllers", render: "manual-tdp", game: "status-unknown",
  priority: "controllers", appearance: "settings", diagnostics: "status-unknown", about: "status-unknown",
};
function Icon({ id }: { id: string }) { return <CommandCenterIcon id={iconIds[id] ?? "status-unknown"} size={34}/>; }

/** Shared synthetic presentation for browser preview and native Decky shell. */
export function ExpandedCommandCenter({ onClose, initialTab = "quick", longReasons = false, settings, native = false, primitives, previewColumns, tiles, renderDetail }: {
  onClose(): void; initialTab?: Tab; longReasons?: boolean; settings?: ReactNode; native?: boolean;
  primitives?: { Button: ElementType; Focusable: ElementType };
  /** Synthetic comparison only; native callers never pass this. */
  previewColumns?: 3 | 4;
  /** Real observations for the tabs that have them. A tab left out keeps its
   *  synthetic tiles, so this can be filled in one tab at a time without the
   *  rest of the prototype claiming to be live. */
  tiles?: Partial<Record<Tab, readonly Tile[]>>;
  /** The application owns existing controls, availability and dispatch guards.
   * Null means status-only. Never invoked for sample or removed readings. */
  renderDetail?: (tab: Tab, tile: Tile) => ReactNode;
}) {
  const Button = primitives?.Button ?? "button";
  const Container = primitives?.Focusable ?? "div";
  const [tab, setTab] = useState<Tab>(initialTab);
  const [nestedId, setNested] = useState<string | null>(null);
  const [columns, setColumns] = useState<number>(previewColumns ?? 4);
  const panel = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const memory = useRef<Partial<Record<Tab, string>>>({});
  const launcher = useRef<string | undefined>(undefined);
  const pendingFocus = useRef<string | undefined>(undefined);
  const opener = useRef<HTMLElement | null>(null);
  const detailHadFocus = useRef(false);
  const supplied = tiles?.[tab];
  // A tab with real readings must stop describing itself as sample data.
  const synthetic = supplied === undefined;
  const items = supplied ?? sampleTiles[tab];
  // Retain the destination, never a copy of a reading that can become stale.
  const nested = nestedId === null ? null : items.find(item => item.id === nestedId) ?? {
    id: nestedId, title: "Status unavailable", value: "Unknown",
    detail: "This reading is no longer available. Return to the menu for current status.",
  };
  const detailTile = !synthetic && nestedId !== null ? supplied.find(item => item.id === nestedId) : undefined;
  const detailContent = detailTile ? renderDetail?.(tab, detailTile) : null;
  const hasDetail = detailContent != null && detailContent !== false;
  const gridColumns = columns;
  const focus = (id?: string) => {
    const target = Array.from(panel.current?.querySelectorAll<HTMLElement>("[data-ec-control]") ?? []).find(el => el.dataset.ecControl === id);
    const child = target?.querySelector<HTMLElement>('button:not(:disabled),select:not(:disabled),input:not(:disabled),textarea:not(:disabled),[tabindex="0"]');
    // Native Focusable may itself have tabindex; an embedded editor should
    // receive focus before its wrapper.
    const interactive = id === "nested-content" ? child : target?.matches("button,select,input,textarea,[tabindex]") ? target : child;
    if (!interactive) {
      const fallback = id === "nested-content" ? panel.current?.querySelector<HTMLElement>('[data-ec-control="nested-back"]') : null;
      (fallback ?? panel.current?.querySelector<HTMLElement>(`[data-ec-tab="${tab}"]`))?.focus();
      return;
    }
    interactive?.focus({ preventScroll: true });
    if (interactive) { if (tab === "settings" && !nested) reveal(interactive); else interactive.scrollIntoView({ block: "nearest" }); }
  };
  const controlIds = () => Array.from(panel.current?.querySelectorAll<HTMLElement>("[data-ec-control]") ?? []).map(el => el.dataset.ecControl!);
  useLayoutEffect(() => {
    const doc = panel.current?.ownerDocument;
    if (!hasDetail && nestedId !== null && detailHadFocus.current && doc &&
        (doc.activeElement === doc.body || !doc.activeElement?.isConnected)) {
      detailHadFocus.current = false;
      focus("nested-back");
    }
  }, [hasDetail, nestedId, tab]);
  useLayoutEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => { if (opener.current?.isConnected) opener.current.focus(); };
  }, []);
  useLayoutEffect(() => {
    if (!content.current) return;
    const observer = new ResizeObserver(entries => setColumns(previewColumns ?? columnsForWidth(entries[0].contentRect.width)));
    observer.observe(content.current);
    return () => observer.disconnect();
  }, [previewColumns]);
  useLayoutEffect(() => {
    focus(nested ? (hasDetail ? "nested-content" : "nested-back") : restoreTarget(controlIds(), pendingFocus.current ?? memory.current[tab]));
    pendingFocus.current = undefined;
  }, [tab, nestedId]);

  function switchTab(direction: -1 | 1) { setNested(null); setTab(nextTab(tab, direction)); }
  function back() {
    if (nested) { pendingFocus.current = launcher.current; setNested(null); }
    else onClose();
  }
  const nativeHandlers = native ? {
    "flow-children": "vertical",
    noFocusRing: true,
    onCancelButton: (event: CustomEvent) => { event.preventDefault(); event.stopPropagation(); back(); },
    onButtonDown: (event: CustomEvent<{ button: number; is_repeat?: boolean }>) => {
      // Steam UI GamepadButton enum (5/6), not raw controller callback codes.
      if (event.detail.button !== 5 && event.detail.button !== 6) return;
      event.preventDefault(); event.stopPropagation();
      if (!event.detail.is_repeat) switchTab(event.detail.button === 5 ? -1 : 1);
    },
  } : {};
  function reveal(target: HTMLElement) {
    const section = target.closest<HTMLElement>("[data-settings-section]");
    if (!section || !content.current) return;
    const controls = section.querySelectorAll("[data-ec-control]");
    const box = content.current.getBoundingClientRect();
    const r = target.getBoundingClientRect();
    if (controls[0]?.contains(target) || r.top < box.top + 10 || r.bottom > box.bottom - 10) {
      const anchor = section.querySelector<HTMLElement>(".rg-expanded-anchor");
      if (!anchor) return;
      const offset = section.dataset.settingsSection === "shortcut" ? 0 : content.current.scrollTop + anchor.getBoundingClientRect().top - box.top - 10;
      content.current.scrollTop = Math.max(0, offset);
      if (target.getBoundingClientRect().bottom > box.bottom - 10) target.scrollIntoView({block: "nearest"});
    }
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    // Embedded pickers own editing/navigation keys. Escape and tab trapping
    // still belong to this shell; native controller events remain Decky's.
    const detailTarget = (event.target as HTMLElement).closest("[data-ec-detail-content]");
    if (detailTarget && (event.target as HTMLElement).matches("input,textarea,select") && !["Escape", "Tab"].includes(event.key)) return;
    if (native && detailTarget && event.key.startsWith("Arrow")) return;
    if (native && (event.target as HTMLElement).closest('[data-ec-control="binding-menu"]')) return;
    if ((event.target as HTMLElement).tagName === "SELECT" && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", " ", "Enter"].includes(event.key)) return;
    if (["q", "Q", "e", "E", "Escape"].includes(event.key)) {
      event.preventDefault(); event.stopPropagation();
      if (event.repeat) return;
      if (event.key === "Escape") back(); else switchTab(event.key.toLowerCase() === "q" ? -1 : 1);
      return;
    }
    if (event.key === "Tab") {
      const buttons = Array.from(panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled)") ?? []);
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if ((event.shiftKey && index <= 0) || (!event.shiftKey && index === buttons.length - 1)) {
        event.preventDefault(); buttons[event.shiftKey ? buttons.length - 1 : 0]?.focus();
      }
      return;
    }
    if (tab === "settings" && !nested && ["Home", "End", "PageDown", "PageUp"].includes(event.key)) {
      event.preventDefault(); event.stopPropagation();
      const controls = Array.from(content.current?.querySelectorAll<HTMLElement>("[data-ec-control]") ?? []);
      const target = event.target as HTMLElement;
      let index = controls.indexOf(target.closest<HTMLElement>("[data-ec-control]")!);
      if (event.key === "Home") index = 0;
      else if (event.key === "End") index = controls.length - 1;
      else if (event.key.startsWith("Page")) {
        const sections = Array.from(content.current?.querySelectorAll<HTMLElement>("[data-settings-section]") ?? []);
        const current = sections.indexOf(target.closest<HTMLElement>("[data-settings-section]")!);
        const section = sections[Math.max(0, Math.min(sections.length - 1, current + (event.key === "PageDown" ? 1 : -1)))];
        index = controls.indexOf(section.querySelector<HTMLElement>("[data-ec-control]")!);
      }
      if (index < 0) { content.current!.scrollTop = 0; panel.current?.querySelector<HTMLButtonElement>('[data-ec-tab="settings"]')?.focus(); }
      else focus(controls[Math.min(index, controls.length - 1)]?.dataset.ecControl);
      return;
    }
    if (!event.key.startsWith("Arrow")) return;
    const target = event.target as HTMLElement;
    const tabTarget = target.closest<HTMLElement>("[data-ec-tab]");
    const direction = event.key.slice(5).toLowerCase() as "left" | "right" | "up" | "down";
    if (tabTarget) {
      event.preventDefault();
      if (direction === "down") focus(restoreTarget(controlIds(), memory.current[tab]));
      if (direction === "left" || direction === "right") {
        const adjacent = nextTab(tabTarget.dataset.ecTab as Tab, direction === "left" ? -1 : 1);
        panel.current?.querySelector<HTMLButtonElement>(`[data-ec-tab="${adjacent}"]`)?.focus();
      }
    } else if (!nested && target.dataset.ecControl && items.some(item => item.id === target.dataset.ecControl)) {
      event.preventDefault(); event.stopPropagation();
      const cells = gridCells(items, gridColumns);
      const cell = cells.find(item => item.id === target.dataset.ecControl);
      if (direction === "up" && cell?.row === 0) {
        const settingsControls = controlIds().filter(id => id.startsWith("binding-"));
        if (settingsControls.length) focus(settingsControls.at(-1));
        else { content.current!.scrollTop = 0; panel.current?.querySelector<HTMLButtonElement>(`[data-ec-tab="${tab}"]`)?.focus(); }
      }
      else {
        const next = moveInGrid(cells, target.dataset.ecControl, direction);
        focus(next);
      }
    } else {
      event.preventDefault(); event.stopPropagation();
      const buttons = Array.from(panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled)") ?? []);
      const index = buttons.indexOf(target as HTMLButtonElement);
      const next = Math.max(0, Math.min(buttons.length - 1, index + (direction === "up" || direction === "left" ? -1 : 1)));
      buttons[next]?.focus(); buttons[next]?.scrollIntoView({ block: "nearest" });
    }
  }

  const renderTile = (item: Tile) => <Button type="button" key={item.id} data-ec-control={item.id} data-tone={item.tone ?? "quiet"} className="rg-expanded-tile"
              {...(native ? { preferredFocus: item.id === restoreTarget(items.map(tile => tile.id), memory.current[tab]), onGamepadFocus: () => { memory.current[tab] = item.id; const target = panel.current?.querySelector<HTMLElement>(`[data-ec-control="${item.id}"]`); if(target) { if(tab === "settings") reveal(target); else target.scrollIntoView({block:"nearest"}); } } } : {})}
              style={{ gridColumn: item.wide ? (gridColumns === 4 ? "span 2" : "1 / -1") : undefined }}
              aria-label={`${item.title}: ${item.value}. ${item.detail}.${synthetic ? " Sample data." : ""} View details.`}
              onFocus={(event: { target: EventTarget }) => { memory.current[tab] = item.id; (event.target as HTMLElement).scrollIntoView({ block: "nearest" }); }} onClick={() => { launcher.current = item.id; setNested(item.id); }}>
              <span className="rg-expanded-tile-body">
                <span className="rg-expanded-tile-heading">
                  <span className="rg-expanded-tile-icon"><Icon id={item.id}/></span>
                  <span className="rg-expanded-label">{item.title}</span>
                </span>
                <span className="rg-expanded-value">{item.id === "disconnect" && <CommandCenterIcon id="status-warning" size={16}/>} {item.value}</span>
                <span className="rg-expanded-detail">{item.detail}{longReasons && item.tone === "unavailable" ? " — Provider observations are unavailable in this synthetic preview. No capability or successful operation can be inferred from the displayed sample." : ""}</span>
                <span className="rg-expanded-chevron" aria-hidden="true">›</span>
              </span>
            </Button>;

  return <div className="rg-expanded-backdrop">
    <style>{expandedStyles}</style>
    <Container ref={panel} data-ec-panel className="rg-expanded" role="dialog" aria-modal="true" aria-label={synthetic ? "Re-Gear expanded Command Center prototype" : "Re-Gear Command Center"} onKeyDown={onKeyDown} {...nativeHandlers}
      onFocus={(event: { target: EventTarget }) => { detailHadFocus.current = Boolean((event.target as HTMLElement).closest("[data-ec-detail-content]")); const id = (event.target as HTMLElement).closest<HTMLElement>("[data-ec-control]")?.dataset.ecControl; if (id && !nested) memory.current[tab] = id; }}>
      <header className="rg-expanded-brand"><span className="rg-expanded-wordmark"><img src={brandIcon} alt=""/>Re-Gear</span><span className="rg-expanded-demo"><span className="rg-expanded-demo-label"><i/>{synthetic ? "Demo · Sample data" : "Application status"}</span><span>{synthetic ? "Hardware controls not connected" : renderDetail ? "Status and controls" : "Readings only · View details"}</span></span></header>
      <Container className="rg-expanded-tabs" role="tablist" aria-label="Command Center sections" {...(native ? { "flow-children": "horizontal", noFocusRing: true } : {})}>
        {tabs.map(id => <Button key={id} id={`ec-tab-${id}`} type="button" role="tab" aria-selected={tab === id} aria-controls="ec-tabpanel" data-ec-tab={id} className="rg-expanded-tab"
          onClick={() => { setNested(null); setTab(id); if (id === tab) focus(restoreTarget(controlIds(), memory.current[tab])); }}>
          <span className="rg-expanded-tab-body"><Icon id={id}/><span>{tabLabels[id]}</span></span>
        </Button>)}
      </Container>
      <div ref={content} className="rg-expanded-content" id="ec-tabpanel" role="tabpanel" onFocusCapture={event => { if(tab === "settings") reveal(event.target as HTMLElement); }} aria-labelledby={`ec-tab-${tab}`}>
        <h2>{nested ? nested.title : tabLabels[tab]}</h2>
        <p className="rg-expanded-context">{nested ? (hasDetail ? "Settings and actions" : synthetic ? "Configuration preview · no changes are applied" : "Current status · no changes are applied") : tab === "quick" ? "Essential controls while you play" : tab === "performance" ? "Configure performance for your play style" : synthetic ? "Status and configuration preview" : "Status and configuration"}</p>
        {nested ? <section className="rg-expanded-detail-page">
          {hasDetail ? <Container key={nested.id} data-ec-control="nested-content" data-ec-detail-content {...(native ? { "flow-children": "vertical", noFocusRing: true, preferredFocus: true } : {})}>{detailContent}</Container> : <>
          <h3>{nested.value}</h3>
          <p>{synthetic && nested.id === "auto" ? "Auto TDP is off and not configured. Target and limit selection must precede Start. This prototype cannot start, stop or tune the controller." : nested.detail}</p>
          {synthetic && nested.id === "auto" && <p><strong>State vocabulary:</strong> Off · Running · Stopping… · Unknown · Needs configuration</p>}
          <p>{synthetic ? "Sample data only. No hardware operation is available." : "Status details only. No operation is available from this view."}</p>
          </>}
          {nested.id === "disconnect" && <p><strong>No unplug clearance.</strong> {synthetic ? "Backend readiness and confirmation are not connected. " : "Readiness, confirmation and unplug clearance are separate. "}A display change, missing observation or successful command does not establish safety.</p>}
          <Button type="button" className="rg-expanded-back" data-ec-control="nested-back" {...(native ? { preferredFocus: !hasDetail } : {})} onClick={back}>Back to {tabLabels[tab]}</Button>
        </section> : <>
          {tab === "settings" && settings}
          <Container className={tab === "settings" ? "rg-expanded-grid rg-expanded-settings-list" : "rg-expanded-grid"} style={{ "--ec-columns": gridColumns } as CSSProperties} {...(native ? { "flow-children": "grid", preferredFocus: true, noFocusRing: true } : {})}>
            {items.map(item => tab === "settings" ? <section key={item.id} data-settings-section={item.id} className="rg-expanded-settings-section">
              <span className="rg-expanded-anchor" tabIndex={-1} aria-label={`${item.title} section`} />
              {renderTile(item)}</section> : renderTile(item))}
          </Container>
          {synthetic ? <aside className="rg-expanded-info" aria-label="Sample status summary">
            <CommandCenterIcon id="status-unknown" size={22}/>
            <span><strong>{tab === "quick" || tab === "egpu" ? "eGPU connected · External controller active" : tab === "performance" ? "Performance preferences" : tab === "controllers" ? "External controller · Player 1" : "Make Re-Gear yours"}</strong>
              <small>{tab === "quick" || tab === "egpu" ? "Sample connection only · No unplug clearance" : tab === "settings" ? "Preview preferences · No settings saved" : "Sample data · Controls are not connected"}</small></span>
            <span className="rg-expanded-badges">{tab === "quick" || tab === "egpu" ? <><span><CommandCenterIcon id="egpu" size={18}/>RX 7600M XT</span><span><CommandCenterIcon id="controllers" size={18}/>P1</span></> : <span>Preview</span>}</span>
          </aside> : <aside className="rg-expanded-info" aria-label="Application status summary">
            <CommandCenterIcon id="status-unknown" size={22}/>
            <span><strong>{tabLabels[tab]}</strong><small>Reported readings · Unknown means no observation available. No unplug clearance.</small></span>
          </aside>}
        </>}
      </div>
      <footer className="rg-expanded-footer" data-ec-footer>
        <span><kbd>LB</kbd><kbd>RB</kbd> Switch Tab</span>
        <span className="rg-expanded-footer-spacer" aria-hidden="true"/>
        <span><kbd className="rg-expanded-round">A</kbd> Select</span>
        <span><kbd className="rg-expanded-round">B</kbd> {nested ? "Back" : "Close"}</span>
      </footer>
    </Container>
  </div>;
}
