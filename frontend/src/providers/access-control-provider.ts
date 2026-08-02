import type { AccessControlProvider, CanReturnType } from "@refinedev/core";

import { getCurrentUser } from "@/providers/session-store";

const RESOURCE_PERMISSIONS: Record<string, Record<string, string>> = {
  users: {
    list: "users:read",
    show: "users:read",
    edit: "users:write",
    create: "users:write",
    delete: "users:write",
  },
  roles: {
    list: "roles:read",
    show: "roles:read",
    edit: "roles:write",
    create: "roles:write",
    delete: "roles:write",
  },
  dashboard: {
    list: "dashboard:read",
    show: "dashboard:read",
  },
};

function evaluate(resource: string | undefined, action: string): CanReturnType {
  const user = getCurrentUser();
  if (!user) return { can: false, reason: "unauthenticated" };

  if (!resource) return { can: false, reason: "unknown_resource" };
  const mapping = RESOURCE_PERMISSIONS[resource];
  if (!mapping) return { can: false, reason: "unknown_resource" };

  const required = mapping[action];
  if (!required) return { can: false, reason: "unsupported_action" };
  return user.permissions.includes(required)
    ? { can: true }
    : { can: false, reason: "missing_permission" };
}

export const accessControlProvider: AccessControlProvider = {
  can: async ({ resource, action }) => evaluate(resource, action),
  options: {
    buttons: { enableAccessControl: true, hideIfUnauthorized: true },
  },
};
