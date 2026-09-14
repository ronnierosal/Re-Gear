import { loadLayout, saveLayout, projectLayout, replaceSlot, type LayoutPreferences, type LayoutStorage, type TileOrigin } from "./layout-preferences";
import { createCustomizeGestureRecognizer, type CustomizeGesture } from "./customization-input";
import { LayoutCustomizationBanner, reorderById, moveTargetIndex } from "./layout-customization";
import { CommandCenterFooterHints } from "./footer-hints";
import { QuickActionRailEditor } from "./quick-actions-customization";
import type { UtilityId } from "./utility-layout";
import { UtilityRail } from "./utility-rail";
import type { UtilityRailProps } from "./utility-rail";
import { CommandNotice } from "./detail-ui";
import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode, ElementType } from "react";
import { CommandCenterIcon, type CommandCenterIconId } from "../command-center-icons";
import { columnsForWidth, gridCells, moveInGrid, nextTab, restoreTarget, sampleTiles, tabLabels, tabs } from "./model";
import type { Tab, Tile } from "./model";
import { expandedStyles } from "./styles";
import { brandIcon } from "../../brand-assets";

const quickActionLabels:Partial<Record<UtilityId,string>>={mic:"Mic",wifi:"Wi-Fi",overlay:"Overlay",recording:"Record",audio:"Audio output"};
const iconIds: Record<string, CommandCenterIconId> = {
  quick: "quick-access", performance: "performance", egpu: "egpu", controllers: "controllers", settings: "settings",
  fps: "fps", manual: "manual-tdp", auto: "auto-tdp", display: "display", disconnect: "safe-disconnect",
  controller: "controllers", builtin: "controllers", render: "manual-tdp", game: "status-unknown",
  priority: "controllers", appearance: "settings", diagnostics: "status-unknown", about: "status-unknown",
};
function Icon({ id }: { id: string }) { return <CommandCenterIcon id={iconIds[id] ?? "status-unknown"} size={34}/>; }

/** Shared synthetic presentation for browser preview and native Decky shell. */
export function ExpandedCommandCenter({ onClose, initialTab = "quick", longReasons = false, settings, native = false, primitives, previewColumns, tiles, renderDetail, disconnectControl, utilityReadings, onUtilityRequest, directions, onDisconnect, unavailableActions = {}, layoutStorage, editButtons }: {
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
  /** Native-only verified control, independent of other synthetic tab readings. */
  disconnectControl?: ReactNode;
  utilityReadings?: UtilityRailProps["readings"];
  onUtilityRequest?: UtilityRailProps["onRequest"];
  directions?: UtilityRailProps["directions"];
  onDisconnect?:()=>void;
  unavailableActions?:Record<string,string>;
  layoutStorage?:LayoutStorage;
  editButtons?:{x:number;y:number};
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
  const lastGrid = useRef<string | undefined>(undefined);
  const pendingFocus = useRef<string | undefined>(undefined);
  const opener = useRef<HTMLElement | null>(null);
  const detailHadFocus = useRef(false);
  const initialLayout=useRef<LayoutPreferences|null>(null);
  if(layoutStorage&&!initialLayout.current)initialLayout.current=loadLayout(layoutStorage);
  const [savedLayout,setSavedLayout]=useState<LayoutPreferences|null>(initialLayout.current);
  const [draft,setDraft]=useState<LayoutPreferences|null>(null);
  const [editMode,setEditMode]=useState<"normal"|"customize"|"move"|"quick-actions">("normal");
  const [selected,setSelected]=useState<string|undefined>(undefined);
  const [rightSlot,setRightSlot]=useState(0);
  const [layoutError,setLayoutError]=useState("");
  const [utilityEditing,setUtilityEditing]=useState<UtilityId|null>(null);
  const tabRef=useRef(tab);tabRef.current=tab;
  const gestureAction=useRef<(gesture:CustomizeGesture)=>void>(()=>{});
  const gesture=useRef<ReturnType<typeof createCustomizeGestureRecognizer>|null>(null);
  if(layoutStorage&&editButtons&&!gesture.current)gesture.current=createCustomizeGestureRecognizer({tab:()=>tabRef.current,onGesture:value=>gestureAction.current(value)});
  const projection=savedLayout?projectLayout(tiles??sampleTiles,draft??savedLayout):null;
  const supplied = tiles?.[tab];
  // A tab with real readings must stop describing itself as sample data.
  const synthetic = supplied === undefined;
  const items = projection?.view[tab] ?? supplied ?? sampleTiles[tab];
  const originFor=(tile:Tile):TileOrigin=>projection?.resolve(tab,tile.id)??{key:`${tab}:${tile.id}`,tab,tile};
  // Retain the destination, never a copy of a reading that can become stale.
  const nested = nestedId === null ? null : items.find(item => item.id === nestedId) ?? {
    id: nestedId, title: "Status unavailable", value: "Unknown",
    detail: "This reading is no longer available. Return to the menu for current status.",
  };
  const detailTile = !synthetic && nestedId !== null ? items.find(item => item.id === nestedId) : undefined;
  const dockControl = native && nestedId === "disconnect" && disconnectControl != null;
  const detailOrigin=detailTile?originFor(detailTile):null;
  const detailContent = dockControl ? disconnectControl : detailOrigin ? renderDetail?.(detailOrigin.tab, detailOrigin.tile) : null;
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
  const controlIds = () => Array.from(panel.current?.querySelectorAll<HTMLElement>("[data-ec-control]") ?? []).map(el => el.dataset.ecControl!).filter(id=>!id.startsWith("utility-"));
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
    return () => { gesture.current?.cancel(); if (opener.current?.isConnected) opener.current.focus(); };
  }, []);
  useLayoutEffect(() => {
    if (!content.current) return;
    const observer = new ResizeObserver(entries => setColumns(previewColumns ?? columnsForWidth(entries[0].contentRect.width)));
    observer.observe(content.current);
    return () => observer.disconnect();
  }, [previewColumns]);
  useLayoutEffect(() => {
    focus(editMode==="customize" ? `choice:${projection?.catalog[0]?.key}` : editMode==="quick-actions" ? `right-slot:${rightSlot}` : editMode==="move" ? selected : nested ? (hasDetail ? "nested-content" : "nested-back") : restoreTarget(controlIds(), pendingFocus.current ?? memory.current[tab]));
    pendingFocus.current = undefined;
  }, [tab, nestedId, editMode, draft]);

  function cancelEdit(){gesture.current?.cancel();setUtilityEditing(null);setDraft(null);setEditMode("normal");setLayoutError("");}
  function commitLayout(next:LayoutPreferences,focusId=selected){
    if(!layoutStorage)return false;
    try{saveLayout(layoutStorage,next);setSavedLayout(next);pendingFocus.current=focusId;cancelEdit();return true;}
    catch{setLayoutError("Could not save this layout. Your saved layout is unchanged.");return false;}
  }
  function beginEdit(value:CustomizeGesture){
    if(!savedLayout||nested||utilityEditing||editMode!=="normal")return;
    const target=items.find(item=>item.id===memory.current[tab])??items[0];
    if(!target)return;
    setSelected(target.id);setLayoutError("");
    setDraft({...savedLayout,quick:[...savedLayout.quick],order:{...savedLayout.order},right:[...savedLayout.right]});
    setEditMode(value.kind==="move"?"move":"customize");
  }
  gestureAction.current=beginEdit;
  function moveSelected(direction:"up"|"down"|"left"|"right"){
    if(editMode!=="move"||!draft||!selected)return false;
    const reordered=reorderById(items,selected,moveTargetIndex(items,selected,direction,gridColumns));
    setDraft(tab==="quick"?{...draft,quick:reordered.map(item=>originFor(item).key)}:{...draft,order:{...draft.order,[tab]:reordered.map(item=>item.id)}});
    return true;
  }
  function chooseTile(origin:TileOrigin){
    if(!savedLayout||Boolean(unavailableActions[origin.tile.id]))return;
    const slot=items.findIndex(item=>item.id===selected);
    commitLayout({...savedLayout,quick:replaceSlot(items.map(item=>originFor(item).key),slot,origin.key)},origin.tab==="quick"?origin.tile.id:`custom:${origin.key}`);
  }
  function chooseRight(id:UtilityId){
    if(!savedLayout||!utilityReadings?.[id]?.available)return;
    const next={...savedLayout,right:replaceSlot(savedLayout.right,rightSlot,id) as UtilityId[]};
    if(!layoutStorage)return;
    try{saveLayout(layoutStorage,next);setSavedLayout(next);setLayoutError("");}catch{setLayoutError("Could not save this layout. Your saved layout is unchanged.");}
  }
  function switchTab(direction: -1 | 1) { cancelEdit();setNested(null); setTab(nextTab(tab, direction)); }
  function enterRail(id:string) {
    if(tab!=="quick"||nested||gridCells(items,gridColumns).find(cell=>cell.id===id)?.column!==0) return false;
    lastGrid.current=id;focus("utility-brightness");return true;
  }
  function back() {
    if(editMode!=="normal"){cancelEdit();return;}
    if (nested) { pendingFocus.current = launcher.current; setNested(null); }
    else onClose();
  }
  const nativeHandlers = native ? {
    "flow-children": "horizontal",
    noFocusRing: true,
    onCancelButton: (event: CustomEvent) => { event.preventDefault(); event.stopPropagation(); back(); },
    onButtonDown: (event: CustomEvent<{ button: number; is_repeat?: boolean }>) => {
      if(editButtons&&savedLayout&&!nested&&!utilityEditing){
        if(event.detail.button===editButtons.y){event.preventDefault();event.stopPropagation();if(editMode==="normal")gesture.current?.down();return;}
        if(event.detail.button===editButtons.x&&tab==="quick"){event.preventDefault();event.stopPropagation();if(!event.detail.is_repeat&&editMode==="normal"){gesture.current?.cancel();setRightSlot(0);setEditMode("quick-actions");}return;}
      }
      // Steam UI GamepadButton enum (5/6), not raw controller callback codes.
      if (event.detail.button !== 5 && event.detail.button !== 6) return;
      event.preventDefault(); event.stopPropagation();
      if (!event.detail.is_repeat) switchTab(event.detail.button === 5 ? -1 : 1);
    },
    onButtonUp:(event:CustomEvent<{button:number}>)=>{if(editButtons&&event.detail.button===editButtons.y&&gesture.current?.isPressed()){event.preventDefault();event.stopPropagation();gesture.current.up();}},
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
    if(savedLayout&&!nested&&!utilityEditing){
      if(event.key.toLowerCase()==="y"){event.preventDefault();event.stopPropagation();if(editMode==="normal")gesture.current?.down();return;}
      if(event.key.toLowerCase()==="x"&&tab==="quick"&&editMode==="normal"){event.preventDefault();event.stopPropagation();setRightSlot(0);setEditMode("quick-actions");return;}
    }
    if(editMode==="move"&&event.key.startsWith("Arrow")){event.preventDefault();event.stopPropagation();moveSelected(event.key.slice(5).toLowerCase() as "up"|"down"|"left"|"right");return;}
    if ((event.target as HTMLElement).matches('input[type="range"]') && (event.target as HTMLElement).closest('[data-utility-side]') && !["Escape", "Tab"].includes(event.key)) return;
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
      if(direction==="left"&&enterRail(target.dataset.ecControl)) return;
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
              disabled={editMode==="normal"&&Boolean(unavailableActions[originFor(item).tile.id])}
              data-move-selected={editMode==="move"&&selected===item.id || undefined}
              onGamepadDirection={native&&directions ? (event:CustomEvent<{button:number}>)=>{const direction=Object.keys(directions).find(key=>directions[key as keyof typeof directions]===event.detail.button) as "up"|"down"|"left"|"right"|undefined;if(direction&&moveSelected(direction)){event.preventDefault();event.stopPropagation();return true;}if(event.detail.button===directions.left&&enterRail(item.id)){event.preventDefault();event.stopPropagation();return true;}return false;} : undefined}
              {...(native ? { preferredFocus: item.id === restoreTarget(items.map(tile => tile.id), memory.current[tab]), onGamepadFocus: () => { memory.current[tab] = item.id; const target = panel.current?.querySelector<HTMLElement>(`[data-ec-control="${item.id}"]`); if(target) { if(tab === "settings") reveal(target); else target.scrollIntoView({block:"nearest"}); } } } : {})}
              aria-label={`${editMode==="move" ? "Move button. A to place. " : ""}${item.title}: ${item.value}. ${item.detail}.${synthetic ? " Sample data." : ""} ${unavailableActions[originFor(item).tile.id] ? unavailableActions[originFor(item).tile.id] : originFor(item).tile.id === "disconnect" && onDisconnect ? "Start guarded disconnect." : "View details."}`}
              onFocus={(event: { target: EventTarget }) => { memory.current[tab] = item.id; (event.target as HTMLElement).scrollIntoView({ block: "nearest" }); }} onClick={() => { if(editMode==="move"){if(draft)commitLayout(draft);return;}const original=originFor(item);if(unavailableActions[original.tile.id])return; if(original.tile.id==="disconnect"&&onDisconnect){onDisconnect();return;} launcher.current = item.id; setNested(item.id); }}>
              <span className="rg-expanded-tile-body">
                <span className="rg-expanded-tile-heading">
                  <span className="rg-expanded-tile-icon"><Icon id={originFor(item).tile.id}/></span>
                  <span className="rg-expanded-label">{item.title}</span>
                </span>
                <span className="rg-expanded-value">{originFor(item).tile.id === "disconnect" && <CommandCenterIcon id="status-warning" size={16}/>} {item.value}</span>
                <span className="rg-expanded-detail">{item.detail}{longReasons && item.tone === "unavailable" ? " — Provider observations are unavailable in this synthetic preview. No capability or successful operation can be inferred from the displayed sample." : ""}</span>
                {!unavailableActions[originFor(item).tile.id] && !(originFor(item).tile.id === "disconnect" && onDisconnect) && <span className="rg-expanded-chevron" aria-hidden="true">›</span>}
              </span>
            </Button>;

  return <div className="rg-expanded-backdrop">
    <style>{expandedStyles}</style>
    <Container ref={panel} data-ec-panel className="rg-expanded-frame" role="dialog" aria-modal="true" aria-label={synthetic ? "Re-Gear expanded Command Center prototype" : "Re-Gear Command Center"} onKeyDown={onKeyDown} {...nativeHandlers}
      onFocus={(event: { target: EventTarget }) => { detailHadFocus.current = Boolean((event.target as HTMLElement).closest("[data-ec-detail-content]")); const id = (event.target as HTMLElement).closest<HTMLElement>("[data-ec-control]")?.dataset.ecControl; if (id && !nested) memory.current[tab] = id; }} onKeyUp={(event:KeyboardEvent<HTMLDivElement>)=>{if(event.key.toLowerCase()==="y"&&gesture.current?.isPressed()){event.preventDefault();event.stopPropagation();gesture.current.up();}}}>
      {tab === "quick" && !nested && editMode==="normal" && <UtilityRail side="left" Button={Button} Focusable={Container} readings={utilityReadings} onRequest={onUtilityRequest} directions={directions} onReturnToGrid={()=>focus(lastGrid.current??items[0]?.id)} onEditingChange={setUtilityEditing}/>}
      <Container className="rg-expanded" {...(native ? {"flow-children":"vertical",noFocusRing:true} : {})}>
      <header className="rg-expanded-brand"><span className="rg-expanded-wordmark"><img src={brandIcon} alt=""/>Re-Gear</span><span className="rg-expanded-demo"><span className="rg-expanded-demo-label"><i/>{synthetic ? "Demo · Sample data" : "Application status"}</span><span>{synthetic ? "Hardware controls not connected" : renderDetail ? "Status and controls" : "Readings only · View details"}</span></span></header>
      <Container className="rg-expanded-tabs" role="tablist" aria-label="Command Center sections" {...(native ? { "flow-children": "horizontal", noFocusRing: true } : {})}>
        {tabs.map(id => <Button key={id} id={`ec-tab-${id}`} type="button" role="tab" aria-selected={tab === id} aria-controls="ec-tabpanel" data-ec-tab={id} className="rg-expanded-tab"
          onClick={() => { cancelEdit();setNested(null); setTab(id); if (id === tab) focus(restoreTarget(controlIds(), memory.current[tab])); }}>
          <span className="rg-expanded-tab-body"><Icon id={id}/><span>{tabLabels[id]}</span></span>
        </Button>)}
      </Container>
      <div ref={content} className="rg-expanded-content" id="ec-tabpanel" role="tabpanel" onFocusCapture={event => { if(tab === "settings") reveal(event.target as HTMLElement); }} aria-labelledby={`ec-tab-${tab}`}>
        {layoutError&&<p role="alert">{layoutError}</p>}
        {editMode==="move"&&<LayoutCustomizationBanner tab={tab} mode="move" selectedTitle={items.find(item=>item.id===selected)?.title}/>}
        {editMode==="customize"&&<LayoutCustomizationBanner tab="quick" mode="swap"/>}
        {nested && <><h2>{nested.title}</h2>
        <p className="rg-expanded-context">{hasDetail ? "Settings and actions" : synthetic ? "Configuration preview · no changes are applied" : "Current status · no changes are applied"}</p></>}
        {editMode==="customize" ? <Container className="rg-expanded-grid" style={{"--ec-columns":gridColumns} as CSSProperties} flow-children="grid" noFocusRing>
          {projection?.catalog.map(origin=><Button key={origin.key} type="button" className="rg-expanded-tile" data-ec-control={`choice:${origin.key}`} disabled={Boolean(unavailableActions[origin.tile.id])} aria-label={`${origin.tile.title}, ${tabLabels[origin.tab]}. ${unavailableActions[origin.tile.id]??origin.tile.detail}`} onClick={()=>chooseTile(origin)}><span className="rg-expanded-tile-body"><span className="rg-expanded-label">{origin.tile.title}</span><span className="rg-expanded-value">{origin.tile.value}</span><small>{tabLabels[origin.tab]}</small></span></Button>)}
        </Container> : editMode==="quick-actions" ? <QuickActionRailEditor slots={(savedLayout?.right??[]).map((id,slot)=>({slot,id,label:quickActionLabels[id]??id,control:<Button type="button" data-ec-control={`right-slot:${slot}`} onClick={()=>setRightSlot(slot)} aria-pressed={rightSlot===slot}>Select</Button>}))} choices={(["mic","wifi","overlay","recording","audio"] as UtilityId[]).map(id=>({id,label:quickActionLabels[id]??id,available:Boolean(utilityReadings?.[id]?.available),selected:savedLayout?.right.includes(id)??false,control:<Button type="button" data-ec-control={`right-choice:${id}`} disabled={!utilityReadings?.[id]?.available} onClick={()=>chooseRight(id)}>Choose</Button>}))}/> : nested ? <section className="rg-expanded-detail-page">
          {hasDetail ? <Container key={nested.id} data-ec-control="nested-content" data-ec-detail-content {...(native ? { "flow-children": "vertical", noFocusRing: true, preferredFocus: true } : {})}>
            {dockControl && <CommandNotice tone="warning" title="Keep the cable connected">Disconnect trial. Follow the guarded flow before any physical action.</CommandNotice>}
            {detailContent}</Container> : <>
          <h3>{nested.value}</h3>
          <p>{synthetic && nested.id === "auto" ? "Auto TDP is off and not configured. Target and limit selection must precede Start. This prototype cannot start, stop or tune the controller." : nested.detail}</p>
          {synthetic && nested.id === "auto" && <p><strong>State vocabulary:</strong> Off · Running · Stopping… · Unknown · Needs configuration</p>}
          <p>{synthetic ? "Sample data only. No hardware operation is available." : "Status details only. No operation is available from this view."}</p>
          </>}
          {nested.id === "disconnect" && !dockControl && <p><strong>No unplug clearance.</strong> {synthetic ? "Backend readiness and confirmation are not connected. " : "Readiness, confirmation and unplug clearance are separate. "}A display change, missing observation or successful command does not establish safety.</p>}
          <Button type="button" className="rg-expanded-back" data-ec-control="nested-back" {...(native ? { preferredFocus: !hasDetail } : {})} onClick={back}>Back to {tabLabels[tab]}</Button>
        </section> : <>
          {tab === "settings" && settings}
          <Container data-layout-customizing={editMode==="move" || undefined} className={tab === "settings" ? "rg-expanded-grid rg-expanded-settings-list" : "rg-expanded-grid"} style={{ "--ec-columns": gridColumns } as CSSProperties} {...(native ? { "flow-children": "grid", preferredFocus: true, noFocusRing: true } : {})}>
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
        {utilityEditing ? <><span>D-pad Adjust</span><span><kbd className="rg-expanded-round">B</kbd> Done</span><span>Right: Menu</span></> : savedLayout ? <CommandCenterFooterHints tab={tab} nested={Boolean(nested)} mode={editMode}/> : <>
        <span><kbd>LB</kbd><kbd>RB</kbd> Switch Tab</span>
        <span className="rg-expanded-footer-spacer" aria-hidden="true"/>
        <span><kbd className="rg-expanded-round">A</kbd> Select</span>
        <span><kbd className="rg-expanded-round">B</kbd> {nested ? "Back" : "Close"}</span></>}
      </footer>
      </Container>
      {tab === "quick" && !nested && editMode==="normal" && <UtilityRail side="right" layout={savedLayout?.right.map(id=>({id,side:"right" as const}))} Button={Button} Focusable={Container} readings={utilityReadings} onRequest={onUtilityRequest}/>}
    </Container>
  </div>;
}
