type Listener = () => void;

const sources = new Map<string, boolean>();
const listeners = new Set<Listener>();
let pendingSnapshot = false;

function publish() {
  let next = false;
  for (const pending of sources.values()) {
    if (pending) {
      next = true;
      break;
    }
  }
  if (next === pendingSnapshot) return;
  pendingSnapshot = next;
  for (const listener of listeners) listener();
}

export function setNavigationPending(id: string, pending: boolean) {
  if (pending) sources.set(id, true);
  else sources.delete(id);
  publish();
}

export function subscribeNavigationPending(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getNavigationPending() {
  return pendingSnapshot;
}
