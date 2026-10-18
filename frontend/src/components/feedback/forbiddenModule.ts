import { matchPath } from "@/features/console/module-identity/adapters";
import type { ModuleIdentity } from "@/features/console/module-identity/types";

const PERMISSION_KEY = /^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$/i;

function permissionValues(module: ModuleIdentity): string[] {
  return Object.values(module.actions).filter(
    (value): value is string => typeof value === "string" && value.length > 0,
  );
}

export function moduleForPermission(
  modules: readonly ModuleIdentity[],
  reason: string | undefined,
  pathname?: string,
): ModuleIdentity | null {
  if (!reason || !PERMISSION_KEY.test(reason)) return null;
  const holders = modules.filter((module) =>
    permissionValues(module).includes(reason),
  );
  if (holders.length === 0) return null;
  if (pathname) {
    const matched = matchPath(pathname, modules.slice());
    const current = matched
      ? holders.find((module) => module.id === matched.resource)
      : undefined;
    if (current) return current;
  }
  const resource = reason.slice(0, reason.indexOf(":"));
  const byId = holders.find((module) => module.id === resource);
  if (byId) return byId;
  if (holders.length === 1) return holders[0];
  return null;
}
