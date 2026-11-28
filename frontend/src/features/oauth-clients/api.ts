import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";
import type {
  OAuthClient,
  OAuthClientWrite,
} from "@/features/oauth-clients/types";

export function listOAuthClients(params?: PageQuery & { q?: string }) {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  if (params?.q) qs.set("q", params.q);
  const query = qs.toString();
  return apiClient<OffsetPage<OAuthClient>>(
    `/oauth-clients${query ? `?${query}` : ""}`,
  );
}

export function getOAuthClient(id: string) {
  return apiClient<{ oauth_client: OAuthClient }>(`/oauth-clients/${id}`);
}

export function createOAuthClient(body: OAuthClientWrite) {
  return apiClient<{ oauth_client: OAuthClient; client_secret: string | null }>(
    "/oauth-clients",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function patchOAuthClient(id: string, body: Partial<OAuthClientWrite>) {
  return apiClient<{ oauth_client: OAuthClient }>(`/oauth-clients/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function rotateOAuthClientSecret(id: string) {
  return apiClient<{ oauth_client: OAuthClient; client_secret: string }>(
    `/oauth-clients/${id}/rotate-secret`,
    { method: "POST" },
  );
}

export function deleteOAuthClient(id: string) {
  return apiClient<void>(`/oauth-clients/${id}`, { method: "DELETE" });
}
