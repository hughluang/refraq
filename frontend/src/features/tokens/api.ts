import { apiClient } from "@/lib/api";
import type {
  CreateTokenRequest,
  CreateTokenResponse,
  TokenMetadata,
} from "@/features/tokens/types";
import type { OffsetPage, PageQuery } from "@/lib/pagination";

export function listTokens(query: PageQuery) {
  const qs = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  return apiClient<OffsetPage<TokenMetadata>>(`/tokens?${qs.toString()}`);
}

export function createToken(body: CreateTokenRequest) {
  return apiClient<CreateTokenResponse>("/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deactivateToken(id: string) {
  const data = await apiClient<{ token: TokenMetadata }>(
    `/tokens/${id}/deactivate`,
    { method: "POST" },
  );
  return data.token;
}

export async function restoreToken(id: string) {
  const data = await apiClient<{ token: TokenMetadata }>(
    `/tokens/${id}/restore`,
    { method: "POST" },
  );
  return data.token;
}

export function deleteToken(id: string) {
  return apiClient<void>(`/tokens/${id}`, { method: "DELETE" });
}
