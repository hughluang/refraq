import { apiClient } from "@/lib/api";
import type { PlatformSettings } from "@/features/settings/types";

export function fetchPlatformSettings() {
  return apiClient<PlatformSettings>("/settings");
}

export function patchPlatformSettings(values: Record<string, number>) {
  return apiClient<PlatformSettings>("/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
}

export function resetPlatformSettings(keys?: string[]) {
  return apiClient<PlatformSettings>("/settings/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(keys ? { keys } : {}),
  });
}
