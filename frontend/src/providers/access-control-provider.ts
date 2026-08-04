import type { AccessControlProvider } from "@refinedev/core";

import {
  evaluateCan,
  getModuleIdentities,
  getModuleIdentityStatus,
} from "@/features/console/module-identity";
import { getCurrentUser } from "@/providers/session-store";

export const accessControlProvider: AccessControlProvider = {
  can: async ({ resource, action }) => {
    const user = getCurrentUser();
    if (!user) return { can: false, reason: "unauthenticated" };

    if (getModuleIdentityStatus() !== "ready") {
      return { can: false, reason: "module_identity_not_ready" };
    }

    return evaluateCan(getModuleIdentities(), user.permissions, resource, action);
  },
  options: {
    buttons: { enableAccessControl: true, hideIfUnauthorized: true },
  },
};
