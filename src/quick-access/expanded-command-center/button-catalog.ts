import type {TileOrigin} from './layout-preferences';
import {controlDomains,domainLabels,controlForKey} from './control-registry';
import type {ControlDomain,ControlType} from './control-registry';
export const catalogCategories=controlDomains;
export type CatalogCategory=ControlDomain;
export type CatalogKind=ControlType;
export type CatalogEntry={origin:TileOrigin;canonicalId:string;preferredKey:string;aliases:readonly string[];category:CatalogCategory|null;kind:CatalogKind;label:string;icon:string;replaceable:boolean};
export type CatalogGroup={category:CatalogCategory;label:string;entries:CatalogEntry[]};
/** Registry identities are independent of live producer copy and availability. */
export function catalogMetadata(origin:TileOrigin):CatalogEntry {
 const definition=controlForKey(origin.key);
 if(!definition)return {origin,canonicalId:origin.key,preferredKey:origin.key,aliases:[],category:null,kind:'status',label:origin.tile.title,icon:origin.tile.id,replaceable:false};
 return {origin,canonicalId:definition.id,preferredKey:definition.sourceKeys[0],aliases:definition.sourceKeys.slice(1),category:definition.domain,kind:definition.type,label:definition.shortLabel,icon:definition.icon,replaceable:definition.quickEligible&&definition.replace};
}
/** The picker deduplicates; the original source catalog still resolves old saves. */
export function groupedButtonCatalog(catalog:readonly TileOrigin[]):CatalogGroup[]{
 const selected=new Map<string,CatalogEntry>();
 for(const origin of catalog){const entry=catalogMetadata(origin);if(!entry.replaceable)continue;const prior=selected.get(entry.canonicalId);if(!prior||origin.key===entry.preferredKey)selected.set(entry.canonicalId,entry);}
 return controlDomains.map(category=>({category,label:domainLabels[category],entries:[...selected.values()].filter(entry=>entry.category===category)})).filter(group=>group.entries.length>0);
}
/** Each category starts a new row; headings are never focus targets. */
export function pickerRows(groups:readonly (readonly string[])[],trailing:readonly string[]=['choice:remove','picker-close']):string[][]{
 const rows:string[][]=[];for(const ids of groups)for(let i=0;i<ids.length;i+=3)rows.push(ids.slice(i,i+3));
 for(const id of trailing)rows.push([id]);return rows;
}
export function movePickerFocus(rows:readonly (readonly string[])[],id:string,direction:'up'|'down'|'left'|'right'):string|undefined{
 const row=Math.max(0,rows.findIndex(ids=>ids.includes(id))),column=Math.max(0,rows[row]?.indexOf(id)??0);
 if(direction==='up'||direction==='down'){const next=Math.max(0,Math.min(rows.length-1,row+(direction==='up'?-1:1)));return rows[next]?.[Math.min(column,rows[next].length-1)];}
 const flat=rows.flat(),index=Math.max(0,flat.indexOf(id));return flat[Math.max(0,Math.min(flat.length-1,index+(direction==='left'?-1:1)))];
}
