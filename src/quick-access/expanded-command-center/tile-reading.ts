/** Publishers own evidence and freshness. This layer never polls or guesses values. */
export type TileReading = {
  availability: 'available' | 'unknown' | 'unavailable';
  primaryValue?: string | number | null;
  secondaryValue?: string | null;
  unit?: string;
  status?: string;
  freshness?: 'fresh' | 'stale' | 'unknown';
  confidence?: string;
  progress?: number | null;
};

export function tileReadingView(reading: TileReading) {
  const usable = reading.availability === 'available' && reading.freshness !== 'stale' && reading.freshness !== 'unknown';
  const value = reading.primaryValue;
  const known = usable && value !== null && value !== undefined &&
    (typeof value === 'number' ? Number.isFinite(value) : value.trim().length > 0);
  return {
    primary: reading.availability === 'unavailable' ? 'Unavailable' : known ? String(value) : '—',
    unit: reading.availability === 'unavailable' ? undefined : reading.unit,
    secondary: known ? reading.secondaryValue : undefined,
    status: known ? reading.status : undefined,
    progress: known && typeof reading.progress === 'number' && Number.isFinite(reading.progress)
      ? Math.max(0, Math.min(1, reading.progress)) : null,
    known,
  };
}

export function fpsReading(current: number | null | undefined, target: number | null | undefined,
  evidence: Pick<TileReading, 'availability' | 'freshness' | 'confidence'>): TileReading {
  const valid = typeof current === 'number' && Number.isFinite(current) && current >= 0;
  const targetKnown = typeof target === 'number' && Number.isFinite(target) && target > 0;
  return {
    ...evidence, primaryValue: valid ? current : null, unit: 'FPS',
    secondaryValue: targetKnown ? `Target ${target} FPS` : undefined,
    progress: valid && targetKnown ? Math.max(0, Math.min(1, current / target)) : null,
  };
}
