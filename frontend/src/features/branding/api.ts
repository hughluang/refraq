import { apiClient } from "@/lib/api";
import {
  parsePublicBranding,
  type BrandingUpdate,
  type PublicBranding,
} from "@/features/branding/types";

export function fetchPublicBranding() {
  return apiClient<unknown>("/branding", {
    timeoutMs: 3000,
    cache: "no-store",
  }).then(parsePublicBranding);
}

export function updateBranding(values: BrandingUpdate) {
  return apiClient<unknown>("/branding", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  }).then(parsePublicBranding);
}

export async function uploadBrandingAsset(
  kind: "logo" | "favicon",
  file: File,
): Promise<void> {
  const body = new FormData();
  body.append("file", file);
  await apiClient(`/branding/assets/${kind}`, {
    method: "POST",
    body,
  });
}

export async function deleteBrandingAsset(
  kind: "logo" | "favicon",
): Promise<void> {
  await apiClient(`/branding/assets/${kind}`, { method: "DELETE" });
}

export async function resetBranding(): Promise<PublicBranding> {
  await apiClient("/branding/reset", { method: "POST" });
  return fetchPublicBranding();
}
