import type { ModuleIdentity } from "@/features/console/module-identity/types";
import type { PermissionCatalogEntry } from "@/features/roles/types";

function normalizeModuleId(id: string): string {
  return id.replace(/-/g, "_");
}

/** Module that owns a permission, else the key prefix. */
export function permissionGroupId(
  key: string,
  modules: readonly ModuleIdentity[],
): string {
  const prefix = key.split(":")[0];
  const exact = modules.find((module) => normalizeModuleId(module.id) === prefix);
  if (exact) return exact.id;
  const plural = modules.find((module) => normalizeModuleId(module.id) === `${prefix}s`);
  if (plural) return plural.id;
  const holders = modules.filter((module) =>
    Object.values(module.actions).some((action) => action === key),
  );
  if (holders.length === 1) return holders[0].id;
  return prefix;
}

export type PermissionGroup = {
  id: string;
  labelKey: string | null;
  entries: PermissionCatalogEntry[];
};

export function groupPermissions(
  entries: readonly PermissionCatalogEntry[],
  modules: readonly ModuleIdentity[],
): PermissionGroup[] {
  const groups: PermissionGroup[] = [];
  const buckets = new Map<string, PermissionGroup>();
  for (const entry of entries) {
    const id = permissionGroupId(entry.key, modules);
    const existing = buckets.get(id);
    if (existing) {
      existing.entries.push(entry);
      continue;
    }
    const group: PermissionGroup = {
      id,
      labelKey: modules.find((module) => module.id === id)?.label_key ?? null,
      entries: [entry],
    };
    buckets.set(id, group);
    groups.push(group);
  }
  return groups;
}
