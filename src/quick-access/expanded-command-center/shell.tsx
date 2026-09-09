import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import { ApprovedIcon } from "../approved-icons";
import { columnsForWidth, gridCells, moveInGrid, nextTab, restoreTarget, sampleTiles, tabLabels, tabs } from "./model";
import type { Tab, Tile } from "./model";
import { expandedStyles } from "./styles";

function Icon({ id }: { id: string }) {
  if (id === "controllers" || id === "controller" || id === "builtin") return <ApprovedIcon id="module-controller" size={30} />;
  if (id === "egpu") return <ApprovedIcon id="module-egpu" size={30} />;
  if (id === "display") return <ApprovedIcon id="mode-tv-docked" size={30} />;
  if (["performance", "auto"].includes(id)) return <ApprovedIcon id="module-auto-tdp" size={30} />;
  // Minimal line icons follow the approved currentColor icon geometry/style.
  return <svg width="30" height="30" viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    {id === "quick" ? <path d="m4 15 12-11 12 11M8 12v16h6v-9h4v9h6V12" />
      : id === "manual" ? <><rect x="8" y="8" width="16" height="16" rx="2"/><rect x="12" y="12" width="8" height="8"/><path d="M12 3v5m8-5v5M12 24v5m8-5v5M3 12h5m-5 8h5m16-8h5m-5 8h5"/></>
      : id === "fps" ? <><path d="M3 22V4h22M7 26V8h22"/><rect x="11" y="12" width="18" height="16" rx="1"/><path d="M14 23v-6h4m-4 3h3m4 3v-6h5"/></>
      : id === "disconnect" ? <path d="M11 3v8m10-8v8M8 11h16v5a8 8 0 0 1-16 0Zm8 13v6" />
        : <><circle cx="16" cy="16" r="8"/><circle cx="16" cy="16" r="3"/><path d="M16 2v6m0 16v6M2 16h6m16 0h6M6 6l5 5m10 10 5 5M26 6l-5 5M11 21l-5 5"/></>}
  </svg>;
}

/** Developer-only browser prototype. Intentionally not imported by the plugin. */
export function ExpandedCommandCenter({ onClose, initialTab = "quick", longReasons = false }: {
  onClose(): void; initialTab?: Tab; longReasons?: boolean;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [nested, setNested] = useState<Tile | null>(null);
  const [columns, setColumns] = useState(4);
  const panel = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const memory = useRef<Partial<Record<Tab, string>>>({});
  const launcher = useRef<string | undefined>(undefined);
  const pendingFocus = useRef<string | undefined>(undefined);
  const opener = useRef<HTMLElement | null>(null);
  const items = sampleTiles[tab];
  const gridColumns = tab === "performance" ? Math.min(columns, 2) : columns;
  const focus = (id?: string) => {
    const target = Array.from(panel.current?.querySelectorAll<HTMLElement>("[data-ec-control]") ?? []).find(el => el.dataset.ecControl === id);
    target?.focus();
    target?.scrollIntoView({ block: "nearest" });
  };
  useLayoutEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => { if (opener.current?.isConnected) opener.current.focus(); };
  }, []);
  useLayoutEffect(() => {
    if (!content.current) return;
    const observer = new ResizeObserver(entries => setColumns(columnsForWidth(entries[0].contentRect.width)));
    observer.observe(content.current);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    focus(nested ? "nested-back" : restoreTarget(items.map(item => item.id), pendingFocus.current ?? memory.current[tab]));
    pendingFocus.current = undefined;
  }, [tab, nested]);

  function switchTab(direction: -1 | 1) { setNested(null); setTab(nextTab(tab, direction)); }
  function back() {
    if (nested) { pendingFocus.current = launcher.current; setNested(null); }
    else onClose();
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (["q", "Q", "e", "E", "Escape"].includes(event.key)) {
      event.preventDefault(); event.stopPropagation();
      if (event.repeat) return;
      if (event.key === "Escape") back(); else switchTab(event.key.toLowerCase() === "q" ? -1 : 1);
      return;
    }
    if (event.key === "Tab") {
      const buttons = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if ((event.shiftKey && index <= 0) || (!event.shiftKey && index === buttons.length - 1)) {
        event.preventDefault(); buttons[event.shiftKey ? buttons.length - 1 : 0]?.focus();
      }
      return;
    }
    if (!event.key.startsWith("Arrow")) return;
    const target = event.target as HTMLElement;
    const tabTarget = target.closest<HTMLElement>("[data-ec-tab]");
    const direction = event.key.slice(5).toLowerCase() as "left" | "right" | "up" | "down";
    if (tabTarget) {
      event.preventDefault();
      if (direction === "down") focus(restoreTarget(items.map(item => item.id), memory.current[tab]));
      if (direction === "left" || direction === "right") {
        const adjacent = nextTab(tabTarget.dataset.ecTab as Tab, direction === "left" ? -1 : 1);
        panel.current?.querySelector<HTMLButtonElement>(`[data-ec-tab="${adjacent}"]`)?.focus();
      }
    } else if (!nested && target.dataset.ecControl && items.some(item => item.id === target.dataset.ecControl)) {
      event.preventDefault(); event.stopPropagation();
      const cells = gridCells(items, gridColumns);
      const cell = cells.find(item => item.id === target.dataset.ecControl);
      if (direction === "up" && cell?.row === 0) panel.current?.querySelector<HTMLButtonElement>(`[data-ec-tab="${tab}"]`)?.focus();
      else focus(moveInGrid(cells, target.dataset.ecControl, direction));
    }
  }

  return <div className="rg-expanded-backdrop">
    <style>{expandedStyles}</style>
    <div ref={panel} data-ec-panel className="rg-expanded" role="dialog" aria-modal="true" aria-label="Re-Gear expanded Command Center prototype" onKeyDown={onKeyDown}>
      <header className="rg-expanded-brand"><span>Re-Gear</span><span className="rg-expanded-demo">Prototype · Sample data<br/>No device connected</span></header>
      <nav className="rg-expanded-tabs" role="tablist" aria-label="Command Center sections">
        {tabs.map(id => <button key={id} id={`ec-tab-${id}`} type="button" role="tab" aria-selected={tab === id} aria-controls="ec-tabpanel" data-ec-tab={id} className="rg-expanded-tab"
          onClick={() => { setNested(null); setTab(id); if (id === tab) focus(restoreTarget(items.map(item => item.id), memory.current[tab])); }}>
          <Icon id={id}/><span>{tabLabels[id]}</span>
        </button>)}
      </nav>
      <div ref={content} className="rg-expanded-content" id="ec-tabpanel" role="tabpanel" aria-labelledby={`ec-tab-${tab}`}>
        <h2>{nested ? nested.title : tabLabels[tab]}</h2>
        <p className="rg-expanded-context">{nested ? "Configuration preview · no changes are applied" : tab === "quick" ? "Essential controls while you play" : tab === "performance" ? "Configure performance for your play style" : "Status and configuration preview"}</p>
        {nested ? <section className="rg-expanded-detail-page">
          <h3>{nested.value}</h3>
          <p>{nested.id === "auto" ? "Auto TDP is off and not configured. Target and limit selection must precede Start. This prototype cannot start, stop or tune the controller." : nested.detail}</p>
          {nested.id === "auto" && <p><strong>State vocabulary:</strong> Off · Running · Stopping… · Unknown · Needs configuration</p>}
          {nested.id === "disconnect" && <p><strong>No unplug clearance.</strong> Backend readiness and confirmation are not connected. A display change, missing observation or successful command does not establish safety.</p>}
          <p>Sample data only. No hardware operation is available.</p>
          <button type="button" className="rg-expanded-back" data-ec-control="nested-back" onClick={back}>Back to {tabLabels[tab]}</button>
        </section> : <>
          {tab === "performance" && <p className="rg-expanded-context">Manual limit: 18 W · Auto TDP: Off / not configured · FPS provider: unavailable. All values are samples.</p>}
          <div className="rg-expanded-grid" style={{ "--ec-columns": gridColumns } as CSSProperties}>
            {items.map(item => <button type="button" key={item.id} data-ec-control={item.id} data-tone={item.tone ?? "quiet"} className="rg-expanded-tile"
              style={{ gridColumn: item.wide && columns >= 3 ? "span 2" : undefined }}
              aria-label={`${item.title}: ${item.value}. ${item.detail}. Sample data. View details.`}
              onFocus={() => { memory.current[tab] = item.id; }} onClick={() => { launcher.current = item.id; setNested(item); }}>
              <Icon id={item.id}/><span className="rg-expanded-label">{item.title}</span>
              <span className="rg-expanded-value">{item.tone === "warning" ? "⚠ " : ""}{item.value}</span>
              <span className="rg-expanded-detail">{item.detail}{longReasons && item.tone === "unavailable" ? " — Provider observations are unavailable in this synthetic preview. No capability or successful operation can be inferred from the displayed sample." : ""}</span>
            </button>)}
          </div>
          <div className="rg-expanded-summary">Sample scenario · eGPU connected · external controller active<br/>Connection status does not establish rendering or disconnect readiness.</div>
        </>}
      </div>
      <footer className="rg-expanded-footer" data-ec-footer>
        <button type="button" aria-label="Previous tab (LB equivalent, Q)" onClick={() => switchTab(-1)}>LB</button>
        <button type="button" aria-label="Next tab (RB equivalent, E)" onClick={() => switchTab(1)}>RB</button>
        <span>Switch tab · Q / E</span><span>Arrows Navigate · Enter Select</span>
        <button type="button" onClick={back}>B {nested ? "Back" : "Close"} · Esc</button>
      </footer>
    </div>
  </div>;
}
