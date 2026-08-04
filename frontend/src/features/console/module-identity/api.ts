import { apiClient } from "@/lib/api";
import type { ModuleIdentitiesResponse } from "@/features/console/module-identity/types";

export function fetchModuleIdentities() {
  return apiClient<ModuleIdentitiesResponse>("/console/module-identities");
}
