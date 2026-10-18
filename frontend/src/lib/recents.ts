export const RECENTS_LIMIT = 20;
export const RECENTS_PALETTE_LIMIT = 8;

const STORAGE_PREFIX = "refraq.console.recents.";

export type RecentVisit = {
  moduleId: string;
  title: string;
  href: string;
  visitedAt: number;
};

export type RecentInput = {
  moduleId: string;
  title: string;
  href: string;
  visitedAt?: number;
};

const listeners = new Set<() => void>();
let storageBound = false;

function storageKey(userId: string) {
  return `${STORAGE_PREFIX}${userId}`;
}

function storage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

function emit() {
  for (const listener of listeners) listener();
}

function ensureStorageListener() {
  if (storageBound || typeof window === "undefined") return;
  storageBound = true;
  window.addEventListener("storage", (event) => {
    if (event.key?.startsWith(STORAGE_PREFIX)) emit();
  });
}

function normalize(value: unknown): RecentVisit | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Partial<RecentVisit>;
  if (
    typeof record.moduleId !== "string" ||
    typeof record.title !== "string" ||
    typeof record.href !== "string"
  ) {
    return null;
  }
  return {
    moduleId: record.moduleId,
    title: record.title,
    href: record.href,
    visitedAt: typeof record.visitedAt === "number" ? record.visitedAt : 0,
  };
}

export function readRecents(userId: string): RecentVisit[] {
  const store = storage();
  if (!store) return [];
  try {
    const raw = store.getItem(storageKey(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((item) => {
      const visit = normalize(item);
      return visit ? [visit] : [];
    }).slice(0, RECENTS_LIMIT);
  } catch {
    return [];
  }
}

export function rememberRecent(userId: string, visit: RecentInput) {
  const store = storage();
  if (!store || !visit.href) return;
  const next: RecentVisit[] = [
    {
      moduleId: visit.moduleId,
      title: visit.title,
      href: visit.href,
      visitedAt: visit.visitedAt ?? Date.now(),
    },
    ...readRecents(userId).filter((item) => item.href !== visit.href),
  ].slice(0, RECENTS_LIMIT);
  store.setItem(storageKey(userId), JSON.stringify(next));
  emit();
}

export function clearRecents(userId: string) {
  const store = storage();
  if (!store) return;
  store.removeItem(storageKey(userId));
  emit();
}

export function subscribeRecents(listener: () => void): () => void {
  ensureStorageListener();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
