export type MenuVisibility = { read(): boolean; subscribe(listener: () => void): () => void };

/** Menu lifetime only. Consumers retain their existing read/request owners. */
export function createMenuVisibility() {
  let visible = false;
  const listeners = new Set<() => void>();
  const source: MenuVisibility = {
    read: () => visible,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
  return { source, set(next: boolean) {
    if (visible === next) return;
    visible = next;
    for (const listener of listeners) listener();
  } };
}
