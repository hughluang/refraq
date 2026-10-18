import {
  getBusinessDomain,
  listBusinessDomains,
} from "@/features/business-domains/api";
import type { BusinessDomain } from "@/features/business-domains/types";
import { listDictionaries, getDictionary } from "@/features/dictionaries/api";
import type { Dictionary } from "@/features/dictionaries/types";
import { getEntity, listEntities } from "@/features/entities/api";
import type { EntityStatus } from "@/features/entities/publishStatus";
import type { BusinessEntity } from "@/features/entities/types";
import { getRole, listRoles } from "@/features/roles/api";
import type { RoleRow } from "@/features/roles/types";
import { getSource, listSources } from "@/features/sources/api/sources";
import type { Source } from "@/features/sources/types";
import { getUser, getUserGroup, listUserGroups } from "@/features/subjects/api";
import type { UserGroup } from "@/features/subjects/types";
import { listUsers } from "@/features/users/api";
import type { UserRow } from "@/features/users/types";

export const RECORD_PICKER_LIMIT = 20;

export type RecordOption = {
  id: string;
  name: string;
  key: string;
};

export type RecordPickerAdapter = {
  search: (q: string, signal: AbortSignal) => Promise<RecordOption[]>;
  resolve: (ids: readonly string[], signal?: AbortSignal) => Promise<RecordOption[]>;
};

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function trimmed(q: string): string | undefined {
  const value = q.trim();
  return value === "" ? undefined : value;
}

async function mapCached(
  ids: readonly string[],
  cache: Map<string, RecordOption>,
  load: (id: string, signal?: AbortSignal) => Promise<RecordOption | null>,
  signal?: AbortSignal,
): Promise<RecordOption[]> {
  const missing = [...new Set(ids.filter((id) => id !== "" && !cache.has(id)))];
  await Promise.all(
    missing.map(async (id) => {
      try {
        const option = await load(id, signal);
        if (option) cache.set(option.id, option);
      } catch (error) {
        if (isAbortError(error)) throw error;
      }
    }),
  );
  return ids.flatMap((id) => {
    const hit = cache.get(id);
    return hit ? [hit] : [];
  });
}

function userOption(user: UserRow): RecordOption {
  return {
    id: user.id,
    name: user.display_name.trim() || user.account,
    key: user.account,
  };
}

function roleOption(role: RoleRow): RecordOption {
  return { id: role.id, name: role.name, key: role.key };
}

function sourceOption(source: Source): RecordOption {
  return { id: source.id, name: source.name, key: source.key };
}

function groupOption(group: UserGroup): RecordOption {
  return { id: group.id, name: group.name, key: group.key };
}

function entityOption(entity: BusinessEntity): RecordOption {
  return {
    id: entity.id,
    name: entity.name.trim() || entity.table_name,
    key: entity.table_name,
  };
}

type DictionarySummary = {
  id: string;
  name: string;
  display_name: string;
  deprecated_at?: Dictionary["deprecated_at"];
};

function dictionaryOption(dictionary: DictionarySummary): RecordOption {
  return {
    id: dictionary.id,
    name: dictionary.display_name.trim() || dictionary.name,
    key: dictionary.name,
  };
}

function domainOption(domain: BusinessDomain): RecordOption {
  return { id: domain.id, name: domain.name, key: domain.code };
}

const userCache = new Map<string, RecordOption>();
const roleCache = new Map<string, RecordOption>();
const sourceCache = new Map<string, RecordOption>();
const groupCache = new Map<string, RecordOption>();
const entityCache = new Map<string, RecordOption>();
const dictionaryCache = new Map<string, RecordOption>();
const dictionaryRecords = new Map<string, DictionarySummary>();
const domainCache = new Map<string, RecordOption>();

const userAdapters = new Map<string, RecordPickerAdapter>();
const entityAdapters = new Map<string, RecordPickerAdapter>();

export function userRecordAdapter(filter?: {
  identitySource?: UserRow["identity_source"];
}): RecordPickerAdapter {
  const key = filter?.identitySource ?? "";
  const existing = userAdapters.get(key);
  if (existing) return existing;
  const identitySource = filter?.identitySource;
  const adapter: RecordPickerAdapter = {
    async search(q, signal) {
      const result = await listUsers({
        q: trimmed(q),
        identity_source: identitySource,
        limit: RECORD_PICKER_LIMIT,
        offset: 0,
        signal,
      });
      const options = result.items.map(userOption);
      for (const option of options) userCache.set(option.id, option);
      return options;
    },
    resolve(ids, signal) {
      return mapCached(
        ids,
        userCache,
        async (id, inner) => {
          const loaded = await getUser(id, { signal: inner });
          return userOption(loaded.user);
        },
        signal,
      );
    },
  };
  userAdapters.set(key, adapter);
  return adapter;
}

export function roleRecordAdapter(): RecordPickerAdapter {
  return roleAdapter;
}

const roleAdapter: RecordPickerAdapter = {
  async search(q, signal) {
    const page = await listRoles({
      q: trimmed(q),
      limit: RECORD_PICKER_LIMIT,
      offset: 0,
      signal,
    });
    const options = page.items.map(roleOption);
    for (const option of options) roleCache.set(option.id, option);
    return options;
  },
  resolve(ids, signal) {
    return mapCached(
      ids,
      roleCache,
      async (id, inner) => {
        const loaded = await getRole(id, { signal: inner });
        return roleOption(loaded.role);
      },
      signal,
    );
  },
};

export function sourceRecordAdapter(): RecordPickerAdapter {
  return sourceAdapter;
}

const sourceAdapter: RecordPickerAdapter = {
  async search(q, signal) {
    const page = await listSources({
      q: trimmed(q),
      limit: RECORD_PICKER_LIMIT,
      offset: 0,
      signal,
    });
    const options = page.items.map(sourceOption);
    for (const option of options) sourceCache.set(option.id, option);
    return options;
  },
  resolve(ids, signal) {
    return mapCached(
      ids,
      sourceCache,
      async (id, inner) => {
        const loaded = await getSource(id, { signal: inner });
        return sourceOption(loaded.source);
      },
      signal,
    );
  },
};

export function userGroupRecordAdapter(): RecordPickerAdapter {
  return groupAdapter;
}

const groupAdapter: RecordPickerAdapter = {
  async search(q, signal) {
    const page = await listUserGroups({
      q: trimmed(q),
      limit: RECORD_PICKER_LIMIT,
      offset: 0,
      signal,
    });
    const options = page.items.map(groupOption);
    for (const option of options) groupCache.set(option.id, option);
    return options;
  },
  resolve(ids, signal) {
    return mapCached(
      ids,
      groupCache,
      async (id, inner) => {
        const loaded = await getUserGroup(id, { signal: inner });
        return groupOption(loaded.group);
      },
      signal,
    );
  },
};

export function entityRecordAdapter(
  status?: readonly EntityStatus[],
): RecordPickerAdapter {
  const key = (status ?? []).join("\0");
  const existing = entityAdapters.get(key);
  if (existing) return existing;
  const adapter: RecordPickerAdapter = {
    async search(q, signal) {
      const page = await listEntities({
        q: trimmed(q),
        status,
        limit: RECORD_PICKER_LIMIT,
        offset: 0,
        signal,
      });
      const options = page.items.map(entityOption);
      for (const option of options) entityCache.set(option.id, option);
      return options;
    },
    resolve(ids, signal) {
      return mapCached(
        ids,
        entityCache,
        async (id, inner) => {
          const loaded = await getEntity(id, { signal: inner });
          return entityOption(loaded.entity);
        },
        signal,
      );
    },
  };
  entityAdapters.set(key, adapter);
  return adapter;
}

export function cachedDictionary(id: string): DictionarySummary | undefined {
  return dictionaryRecords.get(id);
}

export function rememberDictionary(dictionary: DictionarySummary) {
  dictionaryRecords.set(dictionary.id, dictionary);
  dictionaryCache.set(dictionary.id, dictionaryOption(dictionary));
}

export function dictionaryRecordAdapter(): RecordPickerAdapter {
  return dictionaryAdapter;
}

const dictionaryAdapter: RecordPickerAdapter = {
  async search(q, signal) {
    const page = await listDictionaries({
      q: trimmed(q),
      status: ["available"],
      limit: RECORD_PICKER_LIMIT,
      offset: 0,
      signal,
    });
    for (const item of page.items) rememberDictionary(item);
    return page.items.map(dictionaryOption);
  },
  resolve(ids, signal) {
    return mapCached(
      ids,
      dictionaryCache,
      async (id, inner) => {
        const loaded = await getDictionary(id, { signal: inner });
        rememberDictionary(loaded.dictionary);
        return dictionaryOption(loaded.dictionary);
      },
      signal,
    );
  },
};

export function businessDomainRecordAdapter(): RecordPickerAdapter {
  return domainAdapter;
}

const domainAdapter: RecordPickerAdapter = {
  async search(q, signal) {
    const page = await listBusinessDomains({
      q: trimmed(q),
      limit: RECORD_PICKER_LIMIT,
      offset: 0,
      signal,
    });
    const options = page.items.map(domainOption);
    for (const option of options) domainCache.set(option.id, option);
    return options;
  },
  resolve(ids, signal) {
    return mapCached(
      ids,
      domainCache,
      async (id, inner) => {
        const loaded = await getBusinessDomain(id, { signal: inner });
        return domainOption(loaded.domain);
      },
      signal,
    );
  },
};
