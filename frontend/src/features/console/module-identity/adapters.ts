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

function actionPermission(
  module: ModuleIdentity,
  action: string,
): string | null | undefined {
  const { actions } = module;
  if (action === "list") return actions.list;
  if (action === "create") return actions.create;
  if (action === "edit") return actions.edit;
  if (action === "delete") return actions.delete;
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
  if (!matched.found || !matched.resource?.name || !matched.action) {
    return null;
  }
  return { resource: matched.resource.name, action: matched.action };
}
