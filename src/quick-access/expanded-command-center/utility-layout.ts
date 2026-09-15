import {controlRegistry,controlForKey} from './control-registry';
export type UtilityId='brightness'|'volume'|'mic'|'recording'|'overlay'|'audio'|'wifi';
export const utilityIds=controlRegistry.filter(def=>def.sourceKeys.some(key=>key.startsWith('utility:'))).map(def=>def.id as UtilityId);
export type UtilityPlacement={id:UtilityId;side:'left'|'right'};
export const commandCenterUtilityIds=utilityIds.filter(id=>controlForKey(`utility:${id}`)?.type==='slider');
export const quickActionIds=controlRegistry.filter(def=>def.rightEligible&&def.defaultRightSlot!==null).sort((a,b)=>a.defaultRightSlot!-b.defaultRightSlot!).map(def=>def.id as UtilityId);
export const optionalQuickActionIds=controlRegistry.filter(def=>def.rightEligible&&def.defaultRightSlot===null).map(def=>def.id as UtilityId);

export const defaultUtilityLayout: readonly UtilityPlacement[] = [
  ...commandCenterUtilityIds.map(id => ({id, side:"left" as const})),
  ...quickActionIds.map(id => ({id, side:"right" as const})),
];

/**
 * Validate a persisted preference without allowing customization to redesign
 * the Command Center. Brightness and Volume are part of the main shell and are
 * always restored to the left strip. Only supported quick actions may appear
 * on the detached right rail. Runtime capability does not change this layout
 * contract; unavailable actions remain visible/disabled rather than moving.
 */
export function normalizeUtilityLayout(value: unknown): UtilityPlacement[] {
  const base = commandCenterUtilityIds.map(id => ({id, side:"left" as const}));
  if (!Array.isArray(value)) return defaultUtilityLayout.map(item => ({...item}));

  const allowedRight = new Set<UtilityId>([...quickActionIds, ...optionalQuickActionIds]);
  const seen = new Set<string>();
  const right = value.flatMap(item => {
    if (!item || typeof item !== "object") return [];
    const id = (item as {id?: unknown}).id;
    const side = (item as {side?: unknown}).side;
    if (typeof id !== "string" || !utilityIds.includes(id as UtilityId)
      || side !== "right" || !allowedRight.has(id as UtilityId) || seen.has(id)) return [];
    seen.add(id);
    return [{id:id as UtilityId,side:"right" as const}];
  });
  return [...base, ...right];
}
