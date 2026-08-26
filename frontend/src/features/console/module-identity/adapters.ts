import {
  matchResourceFromRoute,
  type IResourceItem,
} from "@refinedev/core";

import type {
  MatchedModuleAction,
  ModuleIdentity,
} from "@/features/console/module-identity/types";

export type CanEvaluateResult = {
  can: boolean;
  reason?: string;
};

/** Reasons `accessControlProvider.can` returns before identities/permissions exist. */
export const ACCESS_NOT_READY_REASONS = [
  "module_identity_not_ready",
  "user_permissions_not_ready",
] as const;

export function isAccessEvaluationPending(
  isLoading: boolean,
  data: { can?: boolean; reason?: string } | undefined,
): boolean {
  if (isLoading || data === undefined) return true;
  return ACCESS_NOT_READY_REASONS.some((reason) => data.reason === reason);
}

function actionPermission(
  module: ModuleIdentity,
  action: string,
): string | null | undefined {
  const { actions } = module;
  if (action === "list") return actions.list;
  if (action === "create") return actions.create;
  if (action === "edit") return actions.edit;
  if (action === "delete") return actions.delete;
  if (action === "show") return actions.show;
  if (action === "sample") return actions.sample;
  return undefined;
}

export function toRefineResources(modules: ModuleIdentity[]): IResourceItem[] {
  return modules.map((module) => {
    const resource: IResourceItem = {
      name: module.id,
      meta: { label: module.label_key },
    };
    if (module.routes.list) {
      resource.list = module.routes.list;
    }
    if (module.routes.create) {
      resource.create = module.routes.create;
    }
    if (module.routes.edit) {
      resource.edit = module.routes.edit;
    }
    if (module.routes.show) {
      resource.show = module.routes.show;
    }
    return resource;
  });
}

export function evaluateCan(
  modules: ModuleIdentity[],
  permissions: string[],
  resource: string | undefined,
  action: string,
): CanEvaluateResult {
  if (!resource) return { can: false, reason: "unknown_resource" };
  const module = modules.find((item) => item.id === resource);
  if (!module) return { can: false, reason: "unknown_resource" };

  const required = actionPermission(module, action);
  if (required == null) return { can: false, reason: "unsupported_action" };

  return permissions.includes(required)
    ? { can: true }
    : { can: false, reason: required };
}

export function matchPath(
  pathname: string,
  modules: ModuleIdentity[],
): MatchedModuleAction | null {
  const resources = toRefineResources(modules);
  const matched = matchResourceFromRoute(pathname, resources);
  if (matched.found && matched.resource?.name && matched.action) {
    return { resource: matched.resource.name, action: matched.action };
  }
  return matchAliasPath(pathname, modules);
}

function segmentsMatch(pathname: string, pattern: string): boolean {
  const pathSegments = pathname.split("/").filter(Boolean);
  const patternSegments = pattern.split("/").filter(Boolean);
  if (pathSegments.length !== patternSegments.length) {
    return false;
  }
  return patternSegments.every((segment, index) => {
    if (segment.startsWith(":")) {
      return true;
    }
    return segment === pathSegments[index];
  });
}

export function matchAliasPath(
  pathname: string,
  modules: ModuleIdentity[],
): MatchedModuleAction | null {
  for (const module of modules) {
    const aliases = module.routes.aliases ?? [];
    for (const alias of aliases) {
      if (segmentsMatch(pathname, alias.path)) {
        return { resource: module.id, action: alias.action };
      }
    }
  }
  return null;
}
