/** Session-only player attestations. Never persisted, sent over RPC, or logged. */
export type OfflineTestBinding = { appId: number; buildId: number; account: string; store: object; app: object };
export class OfflineTestMemory {
  private records = new Map<number, { binding: OfflineTestBinding; at: number }>();
  private now: () => number;
  constructor(now = () => Date.now()) { this.now = now; }
  forget(appId: number) { this.records.delete(appId); }
  confirm(binding: OfflineTestBinding): boolean {
    const at = this.now();
    if (!Number.isFinite(at) || !Number.isSafeInteger(binding.appId) || binding.appId <= 0 ||
        !Number.isSafeInteger(binding.buildId) || binding.buildId <= 0 || !binding.account || !binding.store || !binding.app) return false;
    this.records.delete(binding.appId); this.records.set(binding.appId, { binding: { ...binding }, at });
    while (this.records.size > 32) this.records.delete(this.records.keys().next().value!);
    return true;
  }
  has(binding: OfflineTestBinding): boolean {
    const record = this.records.get(binding.appId); if (!record) return false;
    const age = this.now() - record.at;
    const valid = Number.isFinite(age) && age >= 0 && age < 24 * 60 * 60 * 1000 &&
      record.binding.buildId === binding.buildId && record.binding.account === binding.account &&
      record.binding.store === binding.store && record.binding.app === binding.app;
    if (!valid) this.forget(binding.appId);
    return valid;
  }
}
export const offlineTestMemory = new OfflineTestMemory();
