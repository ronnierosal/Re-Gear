import type {Tile} from './model';
/** No model/native binding has been accepted into this runtime yet.
 * These are absent observations, not a saved schedule or a preparation attempt.
 * The offline owner supplies the eventual model and plugin-lifetime adapter.
 */
export const offlineUnavailableReason='Offline preparation is not connected yet';
export const offlineTabTiles:readonly Tile[]=[
 {id:'offline-game',title:'Selected Game',value:'Unknown',detail:'No selected-game observation',tone:'unavailable'},
 {id:'offline-readiness',title:'Offline Readiness',value:'Unknown',detail:'No readiness observation',tone:'unavailable'},
 {id:'offline-select',title:'Select Game',value:'Unavailable',detail:offlineUnavailableReason,tone:'unavailable'},
 {id:'offline-sync',title:'Sync Now',value:'Unavailable',detail:offlineUnavailableReason,tone:'unavailable'},
 {id:'offline-schedule',title:'Sync Schedule',value:'Unavailable',detail:'Schedule is not loaded',tone:'unavailable'},
];
export const offlineUnavailableActions=Object.fromEntries(offlineTabTiles.map(tile=>[tile.id,tile.detail]));
