import type { TileView } from "./tile-source";
import type { Tile } from "./model";

/** Presentation of mounted adapters only; does not grant runtime capability. */
export const unavailableTestActions: Record<string,string> = {
  "switch-handheld": "Display integration pending",
  resolution: "Display integration pending",
};
export function testBuildTiles(source:TileView):TileView {
  const quick=source.quick??[], egpu=source.egpu??[];
  // These cards launch WholeDockControl, which owns the current readiness
  // observation. An unavailable overview reading must not masquerade as the
  // action's gate before that guarded control opens.
  const compactDisconnect:Tile = {id:'disconnect',title:'Safe Disconnect',value:'Check readiness',
    detail:'Open to evaluate current teardown conditions',tone:'warning'};
  const unavailable=(id:string,title:string):Tile=>({id,title,value:'Unavailable',detail:unavailableTestActions[id],tone:'unavailable'});
  const status=egpu.find(tile=>tile.id==='link');
  return {...source,
    performance:source.performance?.map(tile=>tile.id === "profile" ? {...tile,title:"Profile"} : tile),
    quick:quick.map(tile=>tile.id==='disconnect'?{...compactDisconnect,id:tile.id}:tile),
    egpu:[unavailable('switch-handheld','Switch to Handheld'),compactDisconnect,
      unavailable('resolution','Resolution'),{id:'egpu',title:'eGPU Status',value:status?.value??'Unknown',detail:egpu.filter(tile=>tile.id!=='disconnect').map(tile=>`${tile.title}: ${tile.value}. ${tile.detail}`).join(' · ')},
      {...compactDisconnect,id:'disconnect-sleep',title:'Safe Disconnect + Sleep'},
      {...compactDisconnect,id:'disconnect-shutdown',title:'Safe Disconnect + Shutdown'}],
  };
}
