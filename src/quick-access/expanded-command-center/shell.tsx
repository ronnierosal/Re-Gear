import { productionEgpuTiles } from "../../build-profile";
import type { BuildProfile } from "../../build-profile";
import {projectRegistryWidgets,replaceControlSlot,controlRegistry,controlForKey,domainLabels} from './control-registry';
import type {ControlDomain} from './control-registry';
import {groupedButtonCatalog,pickerRows,movePickerFocus} from "./button-catalog";
import { normalizeLayout,loadLayout, saveLayout, projectLayout, replaceSlot, type LayoutPreferences, type LayoutStorage, type TileOrigin } from "./layout-preferences";
import { createCustomizeGestureRecognizer, type CustomizeGesture } from "./customization-input";
import { LayoutCustomizationBanner, reorderById, moveTargetIndex } from "./layout-customization";
import { CommandCenterFooterHints } from "./footer-hints";
import type { UtilityId } from "./utility-layout";
import { UtilityIcon, UtilityRail } from "./utility-rail";
import type { UtilityRailProps } from "./utility-rail";
import { CommandNotice } from "./detail-ui";
import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode, ElementType } from "react";
import { CommandCenterIcon, type CommandCenterIconId } from "../command-center-icons";
import { columnsForWidth, gridCells, moveInGrid, nextTab, restoreTarget, sampleTiles, tabLabels, tabs } from "./model";
import type { Tab, Tile } from "./model";
import { expandedStyles } from "./styles";
import { tileOverlayStyles } from "./regear-tile";
import { FpsTile, ReGearTile } from "./regear-tile";
import { V3TileArtwork, v3TileArtworkId } from "./v3-tile-artwork";
import { TileArtworkSprite } from "./tile-artwork";
import { brandIcon } from "../../brand-assets";
import { RichTileArtwork, RichTileSprite, richTileArtworkId, richTileArtworkStyles } from "./rich-tile-artwork";

// Several source-level fixtures execute this module after stripping imports.
// Keep that harness path inert while production always uses the imported layer.
const RichArtwork = typeof RichTileArtwork === "undefined" ? () => null : RichTileArtwork;
const RichArtworkSprite = typeof RichTileSprite === "undefined" ? () => null : RichTileSprite;
const artworkIdFor = typeof richTileArtworkId === "undefined" ? () => undefined : richTileArtworkId;
const artworkStyles = typeof richTileArtworkStyles === "undefined" ? "" : richTileArtworkStyles;
const V3Artwork = typeof V3TileArtwork === "undefined" ? () => null : V3TileArtwork;
const v3ArtworkIdFor = typeof v3TileArtworkId === "undefined" ? () => undefined : v3TileArtworkId;
const SharedTile = typeof ReGearTile === "undefined" ? ({ Button = "button", buttonProps, children }: { Button?: ElementType; buttonProps?: Record<string, unknown>; children?: ReactNode }) => <Button {...buttonProps}>{children}</Button> : ReGearTile;
const SharedFpsTile = typeof FpsTile === "undefined" ? ({ Button = "button", buttonProps, label }: { Button?: ElementType; buttonProps?: Record<string, unknown>; label: string }) => <Button {...buttonProps}><span>{label}</span></Button> : FpsTile;

const quickActionLabels=Object.fromEntries(controlRegistry.filter(def=>def.rightEligible).map(def=>[def.id,def.shortLabel])) as Partial<Record<UtilityId,string>>;
const iconIds: Record<string, CommandCenterIconId> = {
  quick: "quick-access", performance: "performance", egpu: "egpu", controllers: "controllers", settings: "settings",
  fps: "fps", manual: "manual-tdp", auto: "auto-tdp", display: "display", disconnect: "safe-disconnect",
  controller: "controllers", builtin: "controllers", render: "manual-tdp", game: "status-unknown",
  priority: "controllers", appearance: "settings", diagnostics: "status-unknown", about: "status-unknown",
};
function Icon({ id }: { id: string }) { if(controlForKey(`utility:${id}`))return <UtilityIcon id={id as UtilityId}/>;return <CommandCenterIcon id={iconIds[id] ?? "status-unknown"} size={34}/>; }

/** Shared synthetic presentation for browser preview and native Decky shell. */
export function ExpandedCommandCenter({ onClose, initialTab = "quick", longReasons = false, settings, native = false, primitives, previewColumns, tiles, catalogReadings, renderDetail, disconnectControl, utilityReadings, onUtilityRequest, directions, onDisconnect, unavailableActions = {}, layoutStorage, editButtons, onFeedback, onAction, policy = "development" }: {
  policy?: BuildProfile;
  onClose(): void; initialTab?: Tab; longReasons?: boolean; settings?: ReactNode; native?: boolean;
  primitives?: { Button: ElementType; Focusable: ElementType };
  /** Synthetic comparison only; native callers never pass this. */
  previewColumns?: 3 | 4 | 5;
  /** Real observations for the tabs that have them. A tab left out keeps its
   *  synthetic tiles, so this can be filled in one tab at a time without the
   *  rest of the prototype claiming to be live. */
  tiles?: Partial<Record<Tab, readonly Tile[]>>;
  catalogReadings?:Partial<Record<Tab,readonly Tile[]>>;
  /** The application owns existing controls, availability and dispatch guards.
   * Null means status-only. Never invoked for sample or removed readings. */
  renderDetail?: (tab: Tab, tile: Tile) => ReactNode;
  /** Native-only verified control, independent of other synthetic tab readings. */
  disconnectControl?: ReactNode;
  utilityReadings?: UtilityRailProps["readings"];
  onUtilityRequest?: UtilityRailProps["onRequest"];
  directions?: UtilityRailProps["directions"];
  onDisconnect?:()=>void;
  onAction?:(tab:Tab,tile:Tile)=>boolean;
  unavailableActions?:Record<string,string>;
  layoutStorage?:LayoutStorage;
  editButtons?:{y:number};
  onFeedback?:(kind:"select"|"back")=>void;
}) {
  const production = policy === "production";
  const visibleTabs: readonly Tab[] = production ? ["egpu"] : tabs;
  if (production) {
    tiles = productionEgpuTiles(tiles);
    layoutStorage = undefined;
    editButtons = undefined;
    catalogReadings = undefined;
    onUtilityRequest = undefined;
    onAction = undefined;
  }
  const Button = primitives?.Button ?? "button";
  const Container = primitives?.Focusable ?? "div";
  const [tab, setTab] = useState<Tab>(production ? "egpu" : initialTab);
  const [nestedId, setNested] = useState<string | null>(null);
  const [tileSize,setTileSize]=useState({width:100,height:88});
  const [columns, setColumns] = useState<number>(previewColumns ?? 5);
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
  const [focusContext,setFocusContext]=useState<'main'|'left'|'right'>('main');
  const [pickerDomain,setPickerDomain]=useState<ControlDomain|'all'>('all');
  const [widgetFilter,setWidgetFilter]=useState(false);
  const picker=useRef<HTMLDivElement>(null);
  const pickerOpen=editMode==="customize"||editMode==="quick-actions";
  const [layoutError,setLayoutError]=useState("");
  const [utilityEditing,setUtilityEditing]=useState<UtilityId|null>(null);
  const tabRef=useRef(tab);tabRef.current=tab;
  const gestureAction=useRef<(gesture:CustomizeGesture)=>void>(()=>{});
  const gesture=useRef<ReturnType<typeof createCustomizeGestureRecognizer>|null>(null);
  if(layoutStorage&&editButtons&&!gesture.current)gesture.current=createCustomizeGestureRecognizer({tab:()=>tabRef.current,onGesture:value=>gestureAction.current(value)});
  const utilityBusy=useRef(new Set<UtilityId>());
  const [utilityErrors,setUtilityErrors]=useState<Partial<Record<UtilityId,string>>>({});
  const utilityErrorReadings=useRef(new Map<UtilityId,unknown>());
  const extraUtilities=controlRegistry.filter(def=>def.rightEligible&&def.quickEligible).map(def=>{const reading=utilityReadings?.[def.id as UtilityId];return {id:`utility-${def.id}`,title:def.shortLabel,value:reading?.value??'Unavailable',detail:utilityErrors[def.id as UtilityId]??reading?.reason??'',tone:reading?.available?'quiet' as const:'unavailable' as const};});
  const widgetTiles=production ? {} : projectRegistryWidgets(catalogReadings??{});
  const rawSource=tiles??sampleTiles;
  const composedSource=Object.fromEntries(visibleTabs.map(tab=>[tab,[...(rawSource[tab]??[]),...(widgetTiles[tab]??[]),...(tab==='settings'?extraUtilities:[])]])) as Partial<Record<Tab,readonly Tile[]>>;
  const projection=savedLayout?projectLayout(composedSource,draft??savedLayout):null;
  const allPickerGroups=groupedButtonCatalog(projection?.catalog??[]);
  const rightDefinitions=controlRegistry.filter(def=>def.rightEligible);
  const pickerDomains=editMode==='quick-actions'?[...new Set(rightDefinitions.map(def=>def.domain))]:allPickerGroups.filter(group=>!widgetFilter||group.entries.some(entry=>entry.kind==='widget')).map(group=>group.category);
  const hasWidgets=allPickerGroups.some(group=>group.entries.some(entry=>entry.kind==='widget'));
  const pickerGroups=allPickerGroups.filter(group=>pickerDomain==='all'||group.category===pickerDomain).map(group=>({...group,entries:group.entries.filter(entry=>!widgetFilter||entry.kind==='widget')})).filter(group=>group.entries.length);
  const rightChoices=rightDefinitions.filter(def=>pickerDomain==='all'||def.domain===pickerDomain);
  const filterIds=['filter:all',...pickerDomains.map(domain=>`filter:${domain}`),...(editMode==='customize'&&hasWidgets?['filter:widgets']:[])];
  const pickerFocusRows=pickerRows([filterIds,...(editMode==='quick-actions'?[rightChoices.map(def=>`right-choice:${def.id}`)]:pickerGroups.map(group=>group.entries.map(entry=>`choice:${entry.origin.key}`)))]);
  function movePicker(id:string,direction:'up'|'down'|'left'|'right'){
    const next=movePickerFocus(pickerFocusRows,id,direction);
    Array.from(picker.current?.querySelectorAll<HTMLElement>('[data-ec-control]')??[]).find(el=>el.dataset.ecControl===next)?.focus();
  }
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
  const resetDetail=detailOrigin?.key==='settings:reset-layout'&&savedLayout?<div><p>Restore the default Quick Access buttons, right rail and tab order?</p>{layoutError&&<p role="alert">{layoutError}</p>}<Button type="button" onClick={()=>{if(commitLayout(normalizeLayout(null),'reset-layout'))setNested(null);}}>Reset layout</Button></div>:null;
  const detailContent = dockControl ? disconnectControl : resetDetail ?? ( detailOrigin?.tab==="settings"&&detailOrigin.tile.id==="shortcut"?settings:detailOrigin ? renderDetail?.(detailOrigin.tab, detailOrigin.tile) : null);
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
  useLayoutEffect(()=>{for(const [id,failed] of utilityErrorReadings.current){const current=utilityReadings?.[id];if(current?.available&&!current.pending&&current!==failed){utilityErrorReadings.current.delete(id);setUtilityErrors(errors=>({...errors,[id]:undefined}));}}},[utilityReadings]);
  useLayoutEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => { gesture.current?.cancel(); if (opener.current?.isConnected) opener.current.focus(); };
  }, []);
  useLayoutEffect(() => {
    if (!content.current) return;
    const observer = new ResizeObserver(entries => {setColumns(previewColumns ?? columnsForWidth(entries[0].contentRect.width)); const tile=content.current?.querySelector('.rg-expanded-tile')?.getBoundingClientRect();if(tile)setTileSize({width:tile.width,height:tile.height});});
    observer.observe(content.current);
    return () => observer.disconnect();
  }, [previewColumns]);
  useLayoutEffect(() => {
    focus(editMode==="customize" ? `choice:${pickerGroups[0]?.entries[0]?.origin.key}` : editMode==="quick-actions" ? `right-choice:${savedLayout?.right[rightSlot]??"mic"}` : editMode==="move" ? selected : nested ? (hasDetail ? "nested-content" : "nested-back") : pendingFocus.current ?? restoreTarget(controlIds(), memory.current[tab]));
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
    if(value.kind==='swap'&&tab!=='quick')return;
    setPickerDomain('all');setWidgetFilter(false);
    const focused=memory.current[tab];
    if(focused==="utility-brightness"||focused==="utility-volume")return;
    const utilityId=focused?.startsWith("utility-")?focused.slice(8):undefined;
    if(utilityId){
      if(value.kind!=="swap"||tab!=="quick")return;
      const slot=focused?.startsWith("utility-slot-")?Number(focused.slice(13)):savedLayout.right.indexOf(utilityId as UtilityId);if(slot<0||slot>3)return;
      setSelected(focused);setRightSlot(slot);setLayoutError("");setEditMode("quick-actions");return;
    }
    const target=items.find(item=>item.id===focused)??items[0];
    if(!target)return;
    setSelected(target.id);setLayoutError("");
    setDraft({...savedLayout,quick:[...savedLayout.quick],order:{...savedLayout.order},right:[...savedLayout.right]});
    setEditMode(value.kind==="move"?"move":"customize");
  }
  gestureAction.current=beginEdit;
  function moveSelected(direction:"up"|"down"|"left"|"right"){
    if(editMode!=="move"||!draft||!selected)return false;
    const reordered=reorderById(items,selected,moveTargetIndex(items,selected,direction,gridColumns));
    setDraft(tab==="quick"?{...draft,quick:reordered.map(item=>item.empty?(item.layoutKey??item.id):originFor(item).key)}:{...draft,order:{...draft.order,[tab]:reordered.map(item=>item.id)}});
    return true;
  }
  function chooseTile(origin:TileOrigin){
    if(!savedLayout)return;
    const slot=items.findIndex(item=>item.id===selected);
    commitLayout({...savedLayout,quick:replaceControlSlot(items.map(item=>item.empty?(item.layoutKey??item.id):originFor(item).key),slot,origin.key)},origin.tab==="quick"?origin.tile.id:`custom:${origin.key}`);
  }
  function chooseRight(id:UtilityId|null){
    if(!savedLayout||editMode!=="quick-actions")return;
    const next={...savedLayout,right:replaceSlot(savedLayout.right,rightSlot,id)};
    commitLayout(next,`utility-slot-${rightSlot}`);
  }

  function switchTab(direction: -1 | 1) { if(production)return;cancelEdit();setNested(null); setTab(nextTab(tab, direction)); }
  function enterRail(id:string) {
    if(production||tab!=="quick"||nested||gridCells(items,gridColumns).find(cell=>cell.id===id)?.column!==0) return false;
    lastGrid.current=id;focus("utility-brightness");return true;
  }
  function back() {
    if(editMode!=="normal"){pendingFocus.current=selected;cancelEdit();return;}
    if (nested) { pendingFocus.current = launcher.current; setNested(null); }
    else onClose();
  }
  const nativeHandlers = native ? {
    "flow-children": "horizontal",
    noFocusRing: true,
    onGamepadBlur:()=>gesture.current?.cancel(),
    onCancelButton: (event: CustomEvent) => { event.preventDefault(); event.stopPropagation(); if(nested||editMode!=="normal")onFeedback?.("back"); back(); },
    onButtonDown: (event: CustomEvent<{ button: number; is_repeat?: boolean }>) => {
      if(editButtons&&savedLayout&&!nested&&!utilityEditing){
        if(event.detail.button===editButtons.y){event.preventDefault();event.stopPropagation();if(!event.detail.is_repeat&&editMode==="normal")gesture.current?.down();return;}
      }
      // Steam UI GamepadButton enum (5/6), not raw controller callback codes.
      if (event.detail.button !== 5 && event.detail.button !== 6) return;
      event.preventDefault(); event.stopPropagation();
      if (!event.detail.is_repeat&&!pickerOpen) switchTab(event.detail.button === 5 ? -1 : 1);
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
      if(event.key.toLowerCase()==="y"){event.preventDefault();event.stopPropagation();if(!event.repeat&&editMode==="normal")gesture.current?.down();return;}
    }
    if(pickerOpen){
      if(event.key==="Escape"){event.preventDefault();event.stopPropagation();back();return;}
      if(event.key==="Tab"||event.key.startsWith("Arrow")){
        event.preventDefault();event.stopPropagation();
        const choices=Array.from(picker.current?.querySelectorAll<HTMLElement>("button:not(:disabled),[tabindex='0']")??[]);
        const index=choices.indexOf(document.activeElement as HTMLElement);
        if(event.key==='Tab')choices[(Math.max(0,index)+(event.shiftKey?-1:1)+choices.length)%choices.length]?.focus();
        else movePicker((document.activeElement as HTMLElement)?.dataset.ecControl??'',event.key.slice(5).toLowerCase() as 'up'|'down'|'left'|'right');
      }
      if(["q","Q","e","E"].includes(event.key)){event.preventDefault();event.stopPropagation();}
      return;
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

  const hasTileDetails=(item:Tile)=>{const definition=controlForKey(originFor(item).key);return !definition||definition.type==='navigation'||definition.type==='status';};
  const renderTile = (item: Tile) => {
    const original=originFor(item);
    const definition=controlForKey(original.key);
    const disabled=editMode==="normal"&&Boolean(unavailableActions[original.tile.id]||(definition?.rightEligible&&(!utilityReadings?.[definition.id as UtilityId]?.available||utilityReadings?.[definition.id as UtilityId]?.pending)));
    const activate=()=>{if(pickerOpen)return;if(editMode==="move"){if(draft)commitLayout(draft);return;}if(item.empty)return;if(definition?.type==='widget')return;if(unavailableActions[original.tile.id])return;if(definition?.rightEligible){const id=definition.id as UtilityId;if(!onUtilityRequest||!utilityReadings?.[id]?.available||utilityReadings?.[id]?.pending||utilityBusy.current.has(id))return;utilityErrorReadings.current.delete(id);setUtilityErrors(value=>({...value,[id]:undefined}));utilityBusy.current.add(id);void Promise.resolve().then(()=>onUtilityRequest(id)).catch(()=>{utilityErrorReadings.current.set(id,utilityReadings?.[id]);setUtilityErrors(value=>({...value,[id]:'Could not apply'}));}).finally(()=>utilityBusy.current.delete(id));return;}if(definition?.directAction==="disconnect"&&onDisconnect){onDisconnect();return;}if(onAction?.(original.tab,original.tile))return;launcher.current=item.id;setNested(item.id);};
    const buttonProps={key:item.id,className:'rg-expanded-tile','data-ec-control':item.id,'data-tone':item.tone??'quiet','data-empty':item.empty||undefined,'aria-disabled':disabled,'data-move-selected':editMode==="move"&&selected===item.id||undefined,
      onGamepadDirection:native&&directions?(event:CustomEvent<{button:number}>)=>{const direction=Object.keys(directions).find(key=>directions[key as keyof typeof directions]===event.detail.button) as "up"|"down"|"left"|"right"|undefined;if(direction&&moveSelected(direction)){event.preventDefault();event.stopPropagation();return true;}if(event.detail.button===directions.left&&enterRail(item.id)){event.preventDefault();event.stopPropagation();return true;}return false;}:undefined,
      ...(native?{preferredFocus:item.id===restoreTarget(items.map(tile=>tile.id),memory.current[tab]),onGamepadFocus:()=>{memory.current[tab]=item.id;const target=panel.current?.querySelector<HTMLElement>(`[data-ec-control="${item.id}"]`);if(target){if(tab==="settings")reveal(target);else target.scrollIntoView({block:'nearest'});}}}:{}),
      'aria-label':`${editMode==="move"?'Move button. A to place. ':''}${item.title}: ${item.value}. ${item.detail}.${synthetic?' Sample data. ':''}${unavailableActions[original.tile.id]?unavailableActions[original.tile.id]:original.tile.id==='disconnect'&&onDisconnect?'Start guarded disconnect.':hasTileDetails(item)?'View details.':''}`,
      onFocus:(event:{target:EventTarget})=>{memory.current[tab]=item.id;(event.target as HTMLElement).scrollIntoView({block:'nearest'});},onClick:activate};
    // Empty Quick Access positions stay focusable so Y can add a control, but
    // their visible treatment is only the existing outlined card geometry.
    // Keep the instruction in the accessible name instead of repeating it in
    // every unused slot.
    if(item.empty) return <Button {...buttonProps} aria-label="Empty Quick Access slot. Press Y to add a button."/>;
    if(original.tile.id==='fps'){
      const current=/^\s*(\d+(?:\.\d+)?)\s*FPS\b/i.exec(item.value)?.[1];
      const target=/\btarget\s+(\d+(?:\.\d+)?)\b/i.exec(item.detail)?.[1];
      const known=item.tone!=='unavailable'&&current!==undefined;
      return <SharedFpsTile {...buttonProps} key={item.id} Button={Button} buttonProps={buttonProps} label="FPS Target" artwork={<V3Artwork controlId="fps"/>}
        current={known?Number(current):null} target={target===undefined?null:Number(target)} evidence={known?{availability:'available',freshness:'fresh'}:{availability:item.tone==='unavailable'?'unavailable':'unknown'}}/>;
    }
    if(original.tile.id==='disconnect'){
      const status=unavailableActions[original.tile.id]||(production && /unavailable/i.test(item.value))?'Unavailable':/unknown/i.test(item.value)?'Unknown':onDisconnect?'Ready':'Unknown';
      return <SharedTile {...buttonProps} key={item.id} Button={Button} buttonProps={buttonProps} label="Safe Disconnect" artworkId="safe-disconnect" artwork={<V3Artwork controlId="safe-disconnect"/>}>
        <span className="rg-expanded-value">{status}</span>
      </SharedTile>;
    }
    const v3ControlId=definition?.id??original.tile.id;
    const v3ArtworkId=v3ArtworkIdFor(v3ControlId);
    if(v3ArtworkId){
      return <SharedTile {...buttonProps} key={item.id} Button={Button} buttonProps={buttonProps} label={item.title} artworkId={v3ArtworkId} artwork={<V3Artwork controlId={v3ControlId}/> }>
        <span className="rg-expanded-value">{item.value}</span>
        <span className="rg-expanded-detail">{item.detail}{longReasons && item.tone === "unavailable" ? " — Provider observations are unavailable in this synthetic preview. No capability or successful operation can be inferred from the displayed sample." : ""}</span>
        {hasTileDetails(item) && !unavailableActions[original.tile.id] && <span className="rg-expanded-chevron" aria-hidden="true">›</span>}
      </SharedTile>;
    }
    return <Button type="button" key={item.id} data-ec-control={item.id} data-tone={item.tone ?? "quiet"} className="rg-expanded-tile" data-empty={item.empty||undefined}
              aria-disabled={editMode==="normal"&&Boolean(unavailableActions[originFor(item).tile.id]||(controlForKey(originFor(item).key)?.rightEligible&&(!utilityReadings?.[controlForKey(originFor(item).key)!.id as UtilityId]?.available||utilityReadings?.[controlForKey(originFor(item).key)!.id as UtilityId]?.pending)))}
              data-move-selected={editMode==="move"&&selected===item.id || undefined}
              onGamepadDirection={native&&directions ? (event:CustomEvent<{button:number}>)=>{const direction=Object.keys(directions).find(key=>directions[key as keyof typeof directions]===event.detail.button) as "up"|"down"|"left"|"right"|undefined;if(direction&&moveSelected(direction)){event.preventDefault();event.stopPropagation();return true;}if(event.detail.button===directions.left&&enterRail(item.id)){event.preventDefault();event.stopPropagation();return true;}return false;} : undefined}
              {...(native ? { preferredFocus: item.id === restoreTarget(items.map(tile => tile.id), memory.current[tab]), onGamepadFocus: () => { memory.current[tab] = item.id; const target = panel.current?.querySelector<HTMLElement>(`[data-ec-control="${item.id}"]`); if(target) { if(tab === "settings") reveal(target); else target.scrollIntoView({block:"nearest"}); } } } : {})}
              aria-label={`${editMode==="move" ? "Move button. A to place. " : ""}${item.title}: ${item.value}. ${item.detail}.${synthetic ? " Sample data." : ""} ${unavailableActions[originFor(item).tile.id] ? unavailableActions[originFor(item).tile.id] : originFor(item).tile.id === "disconnect" && onDisconnect ? "Start guarded disconnect." : hasTileDetails(item)?"View details.":""}`}
              onFocus={buttonProps.onFocus} onClick={activate}>
              <RichArtwork controlId={originFor(item).tile.id}/>
              <span className="rg-expanded-tile-body">
                <span className="rg-expanded-tile-heading">
                  {!artworkIdFor(originFor(item).tile.id) && <span className="rg-expanded-tile-icon"><Icon id={controlForKey(originFor(item).key)?.icon??originFor(item).tile.id}/></span>}
                  <span className="rg-expanded-label">{item.title}</span>
                </span>
                <span className="rg-expanded-value">{originFor(item).tile.id === "disconnect" && <CommandCenterIcon id="status-warning" size={16}/>} {item.value}</span>
                <span className="rg-expanded-detail">{item.detail}{longReasons && item.tone === "unavailable" ? " — Provider observations are unavailable in this synthetic preview. No capability or successful operation can be inferred from the displayed sample." : ""}</span>
                {!item.empty && hasTileDetails(item) && !unavailableActions[originFor(item).tile.id] && !(originFor(item).tile.id === "disconnect" && onDisconnect) && <span className="rg-expanded-chevron" aria-hidden="true">›</span>}
              </span>
            </Button>;
  };

  return <div className="rg-expanded-backdrop">
    <style>{expandedStyles + (typeof tileOverlayStyles === "string" ? tileOverlayStyles : "") + artworkStyles}</style>
    {typeof TileArtworkSprite === "function" ? <TileArtworkSprite/> : null}
    <RichArtworkSprite/>
    <Container ref={panel} data-ec-panel className="rg-expanded-frame" role="dialog" aria-modal="true" aria-label={synthetic ? "Re-Gear expanded Command Center prototype" : "Re-Gear Command Center"} onKeyDown={onKeyDown} {...nativeHandlers}
      onBlurCapture={()=>gesture.current?.cancel()}
      onFocusCapture={(event:{target:EventTarget})=>{if(pickerOpen&&!(event.target as HTMLElement).closest('[data-ec-picker]')){picker.current?.querySelector<HTMLElement>('button:not(:disabled)')?.focus();}}}
      onFocus={(event: { target: EventTarget }) => { detailHadFocus.current = Boolean((event.target as HTMLElement).closest("[data-ec-detail-content]")); const id = (event.target as HTMLElement).closest<HTMLElement>("[data-ec-control]")?.dataset.ecControl; if (id && !nested) {memory.current[tab] = id;setFocusContext(id==='utility-brightness'||id==='utility-volume'?'left':id.startsWith('utility-')?'right':'main');} }} onKeyUp={(event:KeyboardEvent<HTMLDivElement>)=>{if(event.key.toLowerCase()==="y"&&gesture.current?.isPressed()){event.preventDefault();event.stopPropagation();gesture.current.up();}}}>
      {!production && tab === "quick" && !nested && editMode!=="move" && <UtilityRail side="left" Button={Button} Focusable={Container} readings={utilityReadings} onRequest={pickerOpen?undefined:onUtilityRequest} directions={directions} onReturnToGrid={()=>focus(lastGrid.current??items[0]?.id)} onEditingChange={setUtilityEditing} onFeedback={onFeedback}/>}
      <Container className="rg-expanded" {...(pickerOpen?{inert:"", "aria-hidden":true}:{})} {...(native ? {"flow-children":"vertical",noFocusRing:true} : {})}>
      <header className="rg-expanded-brand"><span className="rg-expanded-wordmark"><img src={brandIcon} alt=""/>Re-Gear</span><span className="rg-expanded-demo"><span className="rg-expanded-demo-label"><i/>{synthetic ? "Demo · Sample data" : "Application status"}</span><span>{synthetic ? "Hardware controls not connected" : renderDetail ? "Status and controls" : "Readings only · View details"}</span></span></header>
      <Container className="rg-expanded-tabs" role="tablist" aria-label="Command Center sections" {...(native ? { "flow-children": "horizontal", noFocusRing: true } : {})}>
        {visibleTabs.map(id => <Button key={id} id={`ec-tab-${id}`} type="button" role="tab" aria-selected={tab === id} aria-controls="ec-tabpanel" data-ec-tab={id} className="rg-expanded-tab"
          onClick={() => { if(pickerOpen)return;cancelEdit();setNested(null); setTab(id); if (id === tab) focus(restoreTarget(controlIds(), memory.current[tab])); }}>
          <span className="rg-expanded-tab-body"><Icon id={id}/><span>{tabLabels[id]}</span></span>
        </Button>)}
      </Container>
      <div ref={content} className="rg-expanded-content" id="ec-tabpanel" role="tabpanel" onFocusCapture={event => { if(tab === "settings") reveal(event.target as HTMLElement); }} aria-labelledby={`ec-tab-${tab}`}>
        {layoutError&&<p role="alert">{layoutError}</p>}
        {editMode==="move"&&<LayoutCustomizationBanner tab={tab} mode="move" selectedTitle={items.find(item=>item.id===selected)?.title}/>}
        {nested && <><h2>{nested.title}</h2>
        <p className="rg-expanded-context">{hasDetail ? "Settings and actions" : synthetic ? "Configuration preview · no changes are applied" : "Current status · no changes are applied"}</p></>}
        {nested ? <section className="rg-expanded-detail-page">
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
        {utilityEditing ? <><span>D-pad Adjust</span><span><kbd className="rg-expanded-round">B</kbd> Done</span><span>Right: Menu</span></> : savedLayout ? <CommandCenterFooterHints tab={tab} nested={Boolean(nested)} mode={editMode} context={focusContext}/> : <>
        {!production && <span><kbd>LB</kbd><kbd>RB</kbd> Switch Tab</span>}
        <span className="rg-expanded-footer-spacer" aria-hidden="true"/>
        <span><kbd className="rg-expanded-round">A</kbd> Select</span>
        <span><kbd className="rg-expanded-round">B</kbd> {nested ? "Back" : "Close"}</span></>}
      </footer>
      </Container>
      {!production && tab === "quick" && !nested && editMode!=="move" && <UtilityRail side="right" layout={savedLayout?.right.map((id,slot)=>({id,slot,side:"right" as const}))} Button={Button} Focusable={Container} readings={utilityReadings} onRequest={pickerOpen?undefined:onUtilityRequest}/>}
      {pickerOpen&&<div className="rg-expanded-picker-backdrop">
        <Container ref={picker} data-ec-picker className="rg-expanded-picker" style={{"--ec-picker-width":`${tileSize.width}px`,"--ec-picker-height":`${tileSize.height}px`} as CSSProperties} role="dialog" aria-modal="true" aria-label="Change button" flow-children="vertical" noFocusRing
          onGamepadDirection={directions?(event:CustomEvent<{button:number}>)=>{
            const direction=Object.keys(directions).find(key=>directions[key as keyof typeof directions]===event.detail.button) as 'up'|'down'|'left'|'right'|undefined;
            if(direction){event.preventDefault();event.stopPropagation();movePicker((event.target as HTMLElement).closest<HTMLElement>('[data-ec-control]')?.dataset.ecControl??'',direction);return true;}return false;
          }:undefined}>
          <h3>Change {editMode==="quick-actions"?quickActionLabels[savedLayout?.right[rightSlot]??"mic"]:items.find(item=>item.id===selected)?.title}</h3>
          {layoutError&&<p role="alert">{layoutError}</p>}
          <Container className="rg-expanded-picker-filters" flow-children="grid" noFocusRing aria-label="Filter controls">
            <Button type="button" data-ec-control="filter:all" aria-pressed={pickerDomain==='all'&&!widgetFilter} onClick={()=>{setPickerDomain('all');setWidgetFilter(false);}}>All</Button>
            {pickerDomains.map(domain=><Button key={domain} type="button" data-ec-control={`filter:${domain}`} aria-pressed={pickerDomain===domain} onClick={()=>setPickerDomain(domain)}>{domainLabels[domain]}</Button>)}
            {editMode==='customize'&&hasWidgets&&<Button type="button" data-ec-control="filter:widgets" aria-pressed={widgetFilter} onClick={()=>{setWidgetFilter(!widgetFilter);setPickerDomain('all');}}>Widgets</Button>}
          </Container>
          {editMode==='customize'?pickerGroups.map(group=><section key={group.category} data-picker-category={group.category}>
            <Container className="rg-expanded-picker-grid" flow-children="grid" noFocusRing>
              {group.entries.map(({origin,label,icon})=><Button key={origin.key} type="button" data-ec-control={`choice:${origin.key}`} className="rg-expanded-picker-tile" onClick={()=>chooseTile(origin)} aria-label={`${label}, ${group.label}`}><span className="rg-expanded-tile-heading"><Icon id={icon}/><span>{label}</span></span><small>{group.label}</small></Button>)}
            </Container></section>):<section><Container className="rg-expanded-picker-grid" flow-children="grid" noFocusRing>
              {rightChoices.map(def=><Button key={def.id} type="button" data-ec-control={`right-choice:${def.id}`} className="rg-expanded-picker-tile" onClick={()=>chooseRight(def.id as UtilityId)} aria-label={`${def.label}${utilityReadings?.[def.id as UtilityId]?.available?'':', unavailable action'}`}><span>{def.shortLabel}</span><small>{domainLabels[def.domain]}</small>{!utilityReadings?.[def.id as UtilityId]?.available&&<small>Unavailable</small>}</Button>)}
            </Container></section>}
          <Container className="rg-expanded-picker-grid" flow-children="grid" noFocusRing>
            <Button type="button" className="rg-expanded-picker-tile" data-ec-control="choice:remove" onClick={()=>{
              if(editMode==='quick-actions'){chooseRight(null);return;}
              if(!savedLayout)return;const slot=items.findIndex(item=>item.id===selected);
              const key=`empty:${Date.now()}:${slot}`;const quick=items.map(item=>item.empty?(item.layoutKey??item.id):originFor(item).key);quick[slot]=key;
              commitLayout({...savedLayout,quick},key);
            }}>Remove button</Button>
          </Container>
          <Button type="button" data-ec-control="picker-close" onClick={back}>B · Cancel</Button>
        </Container>
      </div>}
    </Container>
  </div>;
}
