export const utilityIds = ["brightness", "volume", "mic", "recording", "overlay", "audio", "wifi"] as const;
export type UtilityId = typeof utilityIds[number];
export type UtilityPlacement = { id: UtilityId; side: "left" | "right" };

/** Approved Command Center utility groups. Keep these IDs stable so the visual
 * shell, controller navigation and later runtime adapters can evolve without
 * renaming or reordering the user-facing controls. */
export const commandCenterUtilityIds = ["brightness", "volume"] as const satisfies readonly UtilityId[];
export const quickActionIds = ["mic", "wifi", "overlay", "recording"] as const satisfies readonly UtilityId[];

export const defaultUtilityLayout: readonly UtilityPlacement[] = [
  ...commandCenterUtilityIds.map(id => ({id, side:"left" as const})),
  ...quickActionIds.map(id => ({id, side:"right" as const})),
];

/** Validate a future persisted preference; an empty selection is intentional.
 * Layout never changes capability or hardware state. */
export function normalizeUtilityLayout(value: unknown): UtilityPlacement[] {
  if (!Array.isArray(value)) return defaultUtilityLayout.map(item => ({...item}));
  const seen = new Set<string>();
  return value.flatMap(item => {
    if (!item || typeof item !== "object" || !utilityIds.includes(item.id)
      || !["left", "right"].includes(item.side) || seen.has(item.id)) return [];
    seen.add(item.id);
    return [{id:item.id as UtilityId,side:item.side as "left" | "right"}];
  });
}
