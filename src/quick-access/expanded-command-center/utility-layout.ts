export const utilityIds = ["brightness", "volume", "mic", "recording", "overlay", "audio", "wifi"] as const;
export type UtilityId = typeof utilityIds[number];
export type UtilityPlacement = { id: UtilityId; side: "left" | "right" };
export const defaultUtilityLayout: readonly UtilityPlacement[] = [
  {id:"brightness",side:"left"}, {id:"volume",side:"left"},
  {id:"mic",side:"right"}, {id:"wifi",side:"right"},
  {id:"overlay",side:"right"}, {id:"recording",side:"right"},
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