import type { Tab, Tile } from './model';
import { tabs } from './model';
type TileView=Partial<Record<Tab,readonly Tile[]>>;
import { defaultUtilityLayout, quickActionIds, optionalQuickActionIds } from './utility-layout';
import type { UtilityId } from './utility-layout';
export const LAYOUT_KEY='regear.command-center-layout.v1';
export type LayoutPreferences={quick:string[];order:Partial<Record<Tab,string[]>>;right:UtilityId[]};
export type LayoutStorage=Pick<Storage,'getItem'|'setItem'>;
export type TileOrigin={key:string;tab:Tab;tile:Tile};
const strings=(value:unknown):string[]=>Array.isArray(value)?[...new Set(value.filter((x):x is string=>typeof x==='string'&&x.length<160))].slice(0,64):[];
const rightDefaults=defaultUtilityLayout.filter(x=>x.side==='right').map(x=>x.id);
const allowedRight=new Set<UtilityId>([...quickActionIds,...optionalQuickActionIds]);
export function normalizeLayout(value:unknown):LayoutPreferences {
 const raw=value&&typeof value==='object'?value as Record<string,unknown>:{};
 const order:LayoutPreferences['order']={};
 for(const tab of tabs)order[tab]=strings((raw.order as Record<string,unknown>|undefined)?.[tab]);
 const right=[...strings(raw.right).filter((id):id is UtilityId=>allowedRight.has(id as UtilityId))];
 for(const id of rightDefaults)if(!right.includes(id))right.push(id);
 return {quick:strings(raw.quick),order,right:right.slice(0,4)};
}
export function loadLayout(storage:LayoutStorage):LayoutPreferences {
 try{return normalizeLayout(JSON.parse(storage.getItem(LAYOUT_KEY)??'null'));}catch{return normalizeLayout(null);}
}
export function saveLayout(storage:LayoutStorage,prefs:LayoutPreferences):void {
 storage.setItem(LAYOUT_KEY,JSON.stringify(normalizeLayout(prefs)));
}
export function tileCatalog(source:TileView):TileOrigin[] {
 return tabs.flatMap(tab=>(source[tab]??[]).map(tile=>({key:`${tab}:${tile.id}`,tab,tile})));
}
export function projectLayout(source:TileView,prefs:LayoutPreferences) {
 const catalog=tileCatalog(source),byKey=new Map(catalog.map(origin=>[origin.key,origin]));
 const view:TileView={},origins=new Map<string,TileOrigin>();
 for(const tab of tabs){
  const originals=source[tab]??[];
  const base=originals.map(tile=>`${tab}:${tile.id}`);
  const requested=tab==='quick'?prefs.quick:(prefs.order[tab]??[]).map(id=>`${tab}:${id}`);
  const keys=[...new Set([...requested.filter(key=>byKey.has(key)&&(tab==='quick'||key.startsWith(`${tab}:`))),...base])];
  const selected=tab==='quick'?keys.slice(0,base.length):keys;
  view[tab]=selected.map(key=>{
   const origin=byKey.get(key)!;
   const id=origin.tab===tab?origin.tile.id:`custom:${key}`;
   origins.set(`${tab}:${id}`,origin);
   return {...origin.tile,id};
  });
 }
 return {view,catalog,resolve:(tab:Tab,id:string)=>origins.get(`${tab}:${id}`)};
}
export function replaceSlot(current:readonly string[],slot:number,key:string):string[]{
 const next=[...current];if(slot<0||slot>=next.length)return next;
 const old=next.indexOf(key);if(old>=0)next[old]=next[slot];next[slot]=key;return next;
}
