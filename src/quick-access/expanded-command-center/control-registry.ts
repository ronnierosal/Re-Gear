import type {Tab,Tile} from './model';

export const controlDomains=['general','performance','egpu','display','controller','power','battery','storage','network','system'] as const;
export type ControlDomain=typeof controlDomains[number];
export const controlTypes=['action','toggle','slider','status','widget','navigation'] as const;
export type ControlType=typeof controlTypes[number];
export const domainLabels:Record<ControlDomain,string>={general:'General',performance:'Performance',egpu:'eGPU',display:'Display',controller:'Controllers',power:'Power',battery:'Battery',storage:'Storage',network:'Network',system:'System'};
export type ControlDefinition={
 id:string;sourceKeys:readonly string[];label:string;shortLabel:string;icon:string;
 domain:ControlDomain;type:ControlType;nativeTab:Tab|null;nativeVisible:boolean;defaultQuick:boolean;defaultRightSlot:number|null;
 quickEligible:boolean;rightEligible:boolean;reorder:boolean;replace:boolean;
 capability:string|null;directAction:string|null;
 widgetSource?:{tab:Tab;id:string;tileId:string};
};
function entry(value:Omit<ControlDefinition,'reorder'|'replace'|'quickEligible'|'rightEligible'|'directAction'|'nativeVisible'|'defaultQuick'|'defaultRightSlot'> & Partial<Pick<ControlDefinition,'quickEligible'|'rightEligible'|'directAction'|'nativeVisible'|'defaultQuick'|'defaultRightSlot'>>):ControlDefinition{
 return {reorder:true,replace:true,quickEligible:true,rightEligible:false,directAction:null,nativeVisible:true,defaultQuick:false,defaultRightSlot:null,...value};
}
/** Explicit product identities. Domain, interaction and membership are independent;
 * never classify an unknown producer key by its spelling, label or original tab.
 * A capability is an adapter identifier, not evidence that it is available. */
export const controlRegistry:readonly ControlDefinition[]=[
 entry({id:'fps-target',sourceKeys:['performance:fps','quick:fps'],label:'FPS Target',shortLabel:'FPS Target',icon:'fps',domain:'performance',type:'navigation',nativeTab:'performance',capability:'performance-details',defaultQuick:true}),
 entry({id:'manual-tdp',sourceKeys:['performance:manual','quick:manual'],label:'Manual TDP',shortLabel:'Manual TDP',icon:'manual',domain:'performance',type:'navigation',nativeTab:'performance',capability:'performance-details',defaultQuick:true}),
 entry({id:'auto-tdp',sourceKeys:['performance:auto','quick:auto'],label:'Auto TDP',shortLabel:'Auto TDP',icon:'auto',domain:'performance',type:'navigation',nativeTab:'performance',capability:'performance-details',defaultQuick:true}),
 entry({id:'performance-profile',sourceKeys:['performance:profile'],label:'Performance Profile',shortLabel:'Profile',icon:'profile',domain:'performance',type:'navigation',nativeTab:'performance',capability:null}),
 entry({id:'performance-resolution',sourceKeys:['performance:display'],label:'Resolution',shortLabel:'Resolution',icon:'display',domain:'display',type:'navigation',nativeTab:'performance',capability:null}),
 entry({id:'refresh-rate',sourceKeys:['performance:refresh'],label:'Refresh Rate',shortLabel:'Refresh Rate',icon:'refresh',domain:'display',type:'navigation',nativeTab:'performance',capability:null}),
 entry({id:'display-target',sourceKeys:['quick:display'],label:'Display Target',shortLabel:'Display Target',icon:'display',domain:'display',type:'navigation',nativeTab:'egpu',capability:'display-details',nativeVisible:false,defaultQuick:true}),
 entry({id:'egpu-connection',sourceKeys:['quick:egpu'],label:'eGPU Connection',shortLabel:'eGPU Connection',icon:'egpu',domain:'egpu',type:'navigation',nativeTab:'egpu',capability:'egpu-details',nativeVisible:false,defaultQuick:true}),
 entry({id:'egpu-overview',sourceKeys:['egpu:egpu'],label:'eGPU Status',shortLabel:'eGPU Overview',icon:'egpu',domain:'egpu',type:'navigation',nativeTab:'egpu',capability:'egpu-details'}),
 entry({id:'handheld',sourceKeys:['egpu:switch-handheld'],label:'Switch to Handheld',shortLabel:'Handheld',icon:'display',domain:'egpu',type:'action',nativeTab:'egpu',capability:'handheld-switch',directAction:'switch-handheld'}),
 entry({id:'safe-disconnect',sourceKeys:['egpu:disconnect','quick:disconnect'],label:'Safe Disconnect',shortLabel:'Safe Disconnect',icon:'disconnect',domain:'egpu',type:'action',nativeTab:'egpu',capability:'guarded-disconnect',directAction:'disconnect',defaultQuick:true}),
 entry({id:'egpu-resolution',sourceKeys:['egpu:resolution'],label:'Resolution',shortLabel:'Resolution',icon:'display',domain:'display',type:'navigation',nativeTab:'egpu',capability:null}),
 entry({id:'disconnect-sleep',sourceKeys:['egpu:disconnect-sleep'],label:'Safe Disconnect + Sleep',shortLabel:'Disconnect + Sleep',icon:'disconnect-sleep',domain:'egpu',type:'action',nativeTab:'egpu',capability:null,directAction:'disconnect-sleep'}),
 entry({id:'portable-shutdown',sourceKeys:['egpu:portable-shutdown'],label:'Shutdown',shortLabel:'Shutdown',icon:'disconnect-shutdown',domain:'power',type:'action',nativeTab:'egpu',capability:'portable-shutdown',directAction:'portable-shutdown'}),
 entry({id:'disconnect-shutdown',sourceKeys:['egpu:disconnect-shutdown'],label:'Safe Disconnect + Shutdown',shortLabel:'Disconnect + Shutdown',icon:'disconnect-shutdown',domain:'egpu',type:'action',nativeTab:'egpu',capability:null,directAction:'disconnect-shutdown'}),
 entry({id:'egpu-device',sourceKeys:['egpu:device'],label:'External GPU',shortLabel:'External GPU',icon:'egpu',domain:'egpu',type:'status',nativeTab:null,capability:'egpu-observation',nativeVisible:false}),
 entry({id:'egpu-dock',sourceKeys:['egpu:dock'],label:'Dock Mode',shortLabel:'Dock Mode',icon:'egpu',domain:'egpu',type:'status',nativeTab:null,capability:'egpu-observation',nativeVisible:false}),
 entry({id:'egpu-display',sourceKeys:['egpu:display'],label:'Display Output',shortLabel:'Display Output',icon:'display',domain:'display',type:'status',nativeTab:null,capability:'egpu-observation',nativeVisible:false}),
 entry({id:'egpu-render',sourceKeys:['egpu:render'],label:'Render GPU',shortLabel:'Render GPU',icon:'egpu',domain:'egpu',type:'status',nativeTab:null,capability:'egpu-observation',nativeVisible:false}),
 entry({id:'egpu-link',sourceKeys:['egpu:link'],label:'Connection Link',shortLabel:'Connection Link',icon:'egpu',domain:'egpu',type:'status',nativeTab:null,capability:'egpu-observation',nativeVisible:false}),
 entry({id:'egpu-link-widget',sourceKeys:['egpu:widget-link'],label:'eGPU Connection Widget',shortLabel:'eGPU Connection',icon:'egpu',domain:'egpu',type:'widget',nativeTab:'egpu',nativeVisible:false,capability:'egpu-observation',widgetSource:{tab:'egpu',id:'link',tileId:'widget-link'}}),
 entry({id:'controller-summary',sourceKeys:['quick:controller'],label:'Controller Status',shortLabel:'Controller Status',icon:'controller',domain:'controller',type:'navigation',nativeTab:'controllers',capability:'controller-details',nativeVisible:false,defaultQuick:true}),
 entry({id:'controller-player1',sourceKeys:['controllers:controller'],label:'Player 1',shortLabel:'Player 1',icon:'controller',domain:'controller',type:'status',nativeTab:'controllers',capability:null}),
 entry({id:'controller-battery',sourceKeys:['controllers:battery'],label:'Controller Battery',shortLabel:'Battery',icon:'battery',domain:'controller',type:'status',nativeTab:'controllers',capability:null}),
 entry({id:'controller-builtin',sourceKeys:['controllers:builtin'],label:'Built-in Controller',shortLabel:'Built-in',icon:'controller',domain:'controller',type:'status',nativeTab:'controllers',capability:'controller-observation'}),
 entry({id:'controller-priority',sourceKeys:['controllers:priority'],label:'Controller Priority',shortLabel:'Priority',icon:'controller',domain:'controller',type:'navigation',nativeTab:'controllers',capability:null}),
 entry({id:'controller-tv',sourceKeys:['controllers:tv-controller'],label:'TV Dock Behavior',shortLabel:'TV Dock Behavior',icon:'controller',domain:'controller',type:'navigation',nativeTab:'controllers',capability:null}),
 entry({id:'controller-settings',sourceKeys:['controllers:controller-settings'],label:'Controller Settings',shortLabel:'Controller Settings',icon:'controller',domain:'controller',type:'navigation',nativeTab:'controllers',capability:null}),
 entry({id:'offline-game',sourceKeys:['offline:offline-game'],label:'Selected Game',shortLabel:'Selected Game',icon:'offline',domain:'network',type:'status',nativeTab:'offline',capability:null}),
 entry({id:'offline-readiness',sourceKeys:['offline:offline-readiness'],label:'Offline Readiness',shortLabel:'Readiness',icon:'offline',domain:'network',type:'status',nativeTab:'offline',capability:null}),
 entry({id:'offline-select',sourceKeys:['offline:offline-select'],label:'Select Game',shortLabel:'Select Game',icon:'offline',domain:'network',type:'navigation',nativeTab:'offline',capability:null}),
 entry({id:'offline-sync',sourceKeys:['offline:offline-sync'],label:'Sync Now',shortLabel:'Sync Now',icon:'offline',domain:'network',type:'action',nativeTab:'offline',capability:null,directAction:'offline-sync'}),
 entry({id:'offline-schedule',sourceKeys:['offline:offline-schedule'],label:'Sync Schedule',shortLabel:'Sync Schedule',icon:'offline',domain:'network',type:'navigation',nativeTab:'offline',capability:null}),
 entry({id:'diagnostics',sourceKeys:['settings:diagnostics'],label:'Diagnostics',shortLabel:'Diagnostics',icon:'diagnostics',domain:'system',type:'navigation',nativeTab:'settings',capability:'runtime-diagnostics'}),
 entry({id:'reset-layout',sourceKeys:['settings:reset-layout'],label:'Reset Layout',shortLabel:'Reset Layout',icon:'settings',domain:'system',type:'navigation',nativeTab:'settings',capability:'layout-storage',quickEligible:false}),
 entry({id:'tutorials',sourceKeys:['settings:tutorials'],label:'Tutorials',shortLabel:'Tutorials',icon:'about',domain:'system',type:'navigation',nativeTab:'settings',capability:'tutorials',quickEligible:true}),
 entry({id:'menu-shortcut',sourceKeys:['settings:shortcut'],label:'Menu Shortcut',shortLabel:'Menu Shortcut',icon:'shortcut',domain:'system',type:'navigation',nativeTab:null,capability:'menu-shortcut',directAction:null,quickEligible:false,nativeVisible:false}),
 entry({id:'about',sourceKeys:['settings:about'],label:'About Re-Gear',shortLabel:'About',icon:'about',domain:'system',type:'navigation',nativeTab:'settings',capability:'about',directAction:null,quickEligible:false,nativeVisible:true}),
 entry({id:'help',sourceKeys:['settings:help-guides'],label:'Help Guides',shortLabel:'Help',icon:'about',domain:'system',type:'navigation',nativeTab:null,capability:'help',directAction:null,quickEligible:false,nativeVisible:false}),
 entry({id:'quick-actions',sourceKeys:['settings:quick-actions'],label:'Quick Actions',shortLabel:'Quick Actions',icon:'quick',domain:'system',type:'navigation',nativeTab:null,capability:null,directAction:null,quickEligible:false,nativeVisible:false}),
 entry({id:'appearance',sourceKeys:['settings:appearance'],label:'Appearance',shortLabel:'Appearance',icon:'settings',domain:'system',type:'navigation',nativeTab:null,capability:null,directAction:null,quickEligible:false,nativeVisible:false}),
 entry({id:'updates',sourceKeys:['settings:updates'],label:'Updates',shortLabel:'Updates',icon:'settings',domain:'system',type:'navigation',nativeTab:null,capability:null,directAction:null,quickEligible:false,nativeVisible:false}),
 entry({id:'brightness',sourceKeys:['utility:brightness'],label:'Brightness',shortLabel:'Brightness',icon:'brightness',domain:'display',type:'slider',nativeTab:null,capability:'native-brightness',directAction:'brightness',quickEligible:false,nativeVisible:false}),
 entry({id:'volume',sourceKeys:['utility:volume'],label:'Volume',shortLabel:'Volume',icon:'volume',domain:'system',type:'slider',nativeTab:null,capability:'native-volume',directAction:'volume',quickEligible:false,nativeVisible:false}),
 entry({id:'mic',sourceKeys:['utility:mic','settings:utility-mic'],label:'Mic Mute',shortLabel:'Mic',icon:'mic',domain:'system',type:'toggle',nativeTab:'settings',capability:null,directAction:'mic',quickEligible:true,rightEligible:true,nativeVisible:false,defaultRightSlot:0}),
 entry({id:'wifi',sourceKeys:['utility:wifi','settings:utility-wifi'],label:'Wi-Fi',shortLabel:'Wi-Fi',icon:'wifi',domain:'network',type:'toggle',nativeTab:'settings',capability:null,directAction:'wifi',quickEligible:true,rightEligible:true,nativeVisible:false,defaultRightSlot:1}),
 entry({id:'overlay',sourceKeys:['utility:overlay','settings:utility-overlay'],label:'Performance Overlay',shortLabel:'Overlay',icon:'performance',domain:'performance',type:'toggle',nativeTab:'settings',capability:null,directAction:'overlay',quickEligible:true,rightEligible:true,nativeVisible:false,defaultRightSlot:2}),
 entry({id:'recording',sourceKeys:['utility:recording','settings:utility-recording'],label:'Record',shortLabel:'Record',icon:'recording',domain:'system',type:'action',nativeTab:'settings',capability:null,directAction:'recording',quickEligible:true,rightEligible:true,nativeVisible:false,defaultRightSlot:3}),
 entry({id:'audio',sourceKeys:['utility:audio','settings:utility-audio'],label:'Audio Output',shortLabel:'Audio',icon:'audio',domain:'system',type:'navigation',nativeTab:'settings',capability:null,directAction:'audio',quickEligible:true,rightEligible:true,nativeVisible:false,defaultRightSlot:null}),
];
const definitionsByKey=new Map(controlRegistry.flatMap(def=>def.sourceKeys.map(key=>[key,def] as const)));
/** Copy already-graded publisher observations; missing observations retain the
 * registered widget identity and never imply current evidence or clearance. */
export function projectRegistryWidgets(readings:Partial<Record<Tab,readonly Tile[]>>):Partial<Record<Tab,Tile[]>>{
 const result:Partial<Record<Tab,Tile[]>>={};
 for(const definition of controlRegistry){
  const mapping=definition.widgetSource;
  if(definition.type!=='widget'||!mapping||!definition.nativeTab)continue;
  const observed=readings[mapping.tab]?.find(tile=>tile.id===mapping.id);
  const primary=observed?.value??'Unknown',secondary=observed?.detail??'Observation unavailable',grade=observed?.tone??'unavailable';
  (result[definition.nativeTab]??=[]).push({id:mapping.tileId,title:definition.shortLabel,value:primary,detail:secondary,tone:grade,widget:{primary,secondary,grade}});
 }
 return result;
}
export const controlForKey=(key:string)=>definitionsByKey.get(key);
export const canonicalControlKey=(key:string)=>{const definition=controlForKey(key);return definition?`known:${definition.id}`:`unknown:${key}`;};
export function uniqueControlSlots(keys:readonly string[]):string[]{
 const seen=new Set<string>(),used=new Set(keys);
 return keys.map((key,index)=>{
  const canonical=canonicalControlKey(key);
  if(!seen.has(canonical)){seen.add(canonical);return key;}
  let blank=`empty:duplicate:${index}`;while(used.has(blank))blank+=':blank';used.add(blank);return blank;
 });
}
export function replaceControlSlot(keys:readonly string[],slot:number,key:string):string[]{
 const next=uniqueControlSlots(keys);if(slot<0||slot>=next.length)return next;
 const existing=next.findIndex(value=>canonicalControlKey(value)===canonicalControlKey(key));
 if(existing>=0&&existing!==slot)next[existing]=next[slot];
 next[slot]=key;return uniqueControlSlots(next);
}
/** Consumers retain unknown keys in the original layout but cannot offer them
 * for replacement until a definition is accepted. Never discard saved identity. */
export function registryNativeTiles(source:Partial<Record<Tab,readonly Tile[]>>):Partial<Record<Tab,readonly Tile[]>>{
 const result:Partial<Record<Tab,readonly Tile[]>>={};
 for(const [tab,tiles] of Object.entries(source) as [Tab,readonly Tile[]][]){
  result[tab]=tiles.filter(tile=>{const def=controlForKey(`${tab}:${tile.id}`);return !def||def.nativeVisible&&def.nativeTab===tab||tab==='quick'&&def.defaultQuick;});
 }
 return result;
}
