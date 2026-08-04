import { apiClient } from "@/lib/api";
import type { PlatformSettings } from "@/features/settings/types";

export function fetchPlatformSettings() {
  return apiClient<PlatformSettings>("/settings");
}

export function patchPlatformSettings(admin_session_ttl_hours: number) {
  return apiClient<PlatformSettings>("/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ admin_session_ttl_hours }),
  });
}

export function clearPlatformSettingsOverride() {
  return apiClient<PlatformSettings>("/settings/override", {
    method: "DELETE",
  });
}
