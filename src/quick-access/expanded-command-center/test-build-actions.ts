import type { TileView } from "./tile-source";
import type { Tile } from "./model";

/** Presentation of mounted adapters only; does not grant runtime capability. */
export const unavailableTestActions: Record<string,string> = {
  "switch-handheld": "Display integration pending",
  resolution: "Display integration pending",
  "disconnect-sleep": "Sleep integration pending",
  "disconnect-shutdown": "Shutdown integration pending",
};
export function testBuildTiles(source:TileView):TileView {
  const quick=source.quick??[], egpu=source.egpu??[];
  const disconnect = quick.find(tile=>tile.id==='disconnect')??{id:'disconnect',title:'Safe Disconnect',value:'Unknown',detail:''};
  const compactDisconnect:Tile = {...disconnect, detail:"", value:disconnect.value === 'Unknown' ? 'Unknown' : 'Check readiness'};
  const unavailable=(id:string,title:string):Tile=>({id,title,value:'Unavailable',detail:unavailableTestActions[id],tone:'unavailable'});
  const status=egpu.find(tile=>tile.id==='link');
  return {...source,
    performance:source.performance?.map(tile=>tile.id === "profile" ? {...tile,title:"Profile"} : tile),
    quick:quick.map(tile=>tile.id==='disconnect'?compactDisconnect:tile),
    egpu:[unavailable('switch-handheld','Handheld'),compactDisconnect,
      unavailable('resolution','Resolution'),{id:'egpu',title:'eGPU Status',value:status?.value??'Unknown',detail:egpu.filter(tile=>tile.id!=='disconnect').map(tile=>`${tile.title}: ${tile.value}. ${tile.detail}`).join(' · ')},
      unavailable('disconnect-sleep','Disconnect + Sleep'),unavailable('disconnect-shutdown','Disconnect + Shutdown')],
  };
}
