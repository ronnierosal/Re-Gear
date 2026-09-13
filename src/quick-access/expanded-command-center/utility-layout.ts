export const utilityIds = ["brightness", "volume", "mic", "recording", "overlay", "audio", "wifi"] as const;
export type UtilityId = typeof utilityIds[number];
export type UtilityPlacement = { id: UtilityId; side: "left" | "right" };

/** Approved Command Center utility groups. Keep these IDs stable so the visual
 * shell, controller navigation and later runtime adapters can evolve without
 * renaming or reordering the user-facing controls. */
export const commandCenterUtilityIds = ["brightness", "volume"] as const satisfies readonly UtilityId[];
export const quickActionIds = ["mic", "wifi", "overlay", "recording"] as const satisfies readonly UtilityId[];
export const optionalQuickActionIds = ["audio"] as const satisfies readonly UtilityId[];

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
