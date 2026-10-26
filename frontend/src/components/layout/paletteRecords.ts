import {
  dictionaryRecordAdapter,
  entityRecordAdapter,
  roleRecordAdapter,
  sourceRecordAdapter,
  userGroupRecordAdapter,
  userRecordAdapter,
} from "@/components/form/recordPickerAdapters";
import { listChannels } from "@/features/channels/api";
import { listTags } from "@/features/tags/api";
import type { ModuleIdentity } from "@/features/console/module-identity/types";

export const PALETTE_RECORD_LIMIT = 5;
export const PALETTE_SEARCH_DEBOUNCE_MS = 250;

export const PALETTE_RECORD_MODULES = [
  "users",
  "roles",
  "sources",
  "entities",
  "dictionaries",
  "tags",
  "channels",
  "user-groups",
] as const;

export type PaletteSearchResult = {
  hits: PaletteRecordHit[];
  failed: boolean;
};

export type PaletteRecordHit = {
  moduleId: string;
  id: string;
  title: string;
  href: string;
};

type HitRow = { id: string; name: string };

type Searcher = (query: string, signal: AbortSignal) => Promise<HitRow[]>;

function fromNames(rows: readonly { id: string; name: string }[]): HitRow[] {
  return rows.map((row) => ({ id: row.id, name: row.name }));
}

const SEARCHERS: Record<string, Searcher> = {
  users: (query, signal) =>
    userRecordAdapter().search(query, signal).then(fromNames),
  roles: (query, signal) =>
    roleRecordAdapter().search(query, signal).then(fromNames),
  sources: (query, signal) =>
    sourceRecordAdapter().search(query, signal).then(fromNames),
  entities: (query, signal) =>
    entityRecordAdapter().search(query, signal).then(fromNames),
  dictionaries: (query, signal) =>
    dictionaryRecordAdapter().search(query, signal).then(fromNames),
  tags: async (query, signal) => {
    const trimmed = query.trim();
    const page = await listTags({
      q: trimmed === "" ? undefined : trimmed,
      limit: PALETTE_RECORD_LIMIT,
      offset: 0,
      signal,
    });
    return page.items.map((item) => ({ id: item.id, name: item.name }));
  },
  "user-groups": (query, signal) =>
    userGroupRecordAdapter().search(query, signal).then(fromNames),
  channels: async (query) => {
    const trimmed = query.trim();
    const page = await listChannels({
      q: trimmed === "" ? undefined : trimmed,
      limit: PALETTE_RECORD_LIMIT,
      offset: 0,
    });
    return page.items.map((item) => ({ id: item.id, name: item.name }));
  },
};

export function paletteRecordHref(module: ModuleIdentity, id: string): string {
  const encoded = encodeURIComponent(id);
  const patterns = [module.routes.show, module.routes.edit, module.routes.list];
  for (const pattern of patterns) {
    if (typeof pattern === "string" && pattern.includes(":id")) {
      return pattern.split(":id").join(encoded);
    }
  }
  return module.routes.list as string;
}

export function createRoute(module: ModuleIdentity): string | null {
  const route = module.routes.create;
  if (typeof route !== "string" || route.length === 0) return null;
  return route;
}

export async function searchPaletteRecords(input: {
  query: string;
  moduleIds: readonly string[];
  identities: readonly ModuleIdentity[];
  signal: AbortSignal;
}): Promise<PaletteSearchResult> {
  const tasks = input.moduleIds.map(async (moduleId) => {
    const identity = input.identities.find((module) => module.id === moduleId) as ModuleIdentity;
    const rows = await SEARCHERS[moduleId](input.query, input.signal);
    return rows.slice(0, PALETTE_RECORD_LIMIT).map((row) => ({
      moduleId,
      id: row.id,
      title: row.name,
      href: paletteRecordHref(identity, row.id),
    }));
  });
  const settled = await Promise.allSettled(tasks);
  if (input.signal.aborted) return { hits: [], failed: false };
  return {
    hits: settled.flatMap((result) => (result.status === "fulfilled" ? result.value : [])),
    failed: settled.some((result) => result.status === "rejected"),
  };
}
